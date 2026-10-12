"""Provider payload handling and the retry policy, without network access."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from knowledge_guard import llm, upstream
from knowledge_guard.errors import UpstreamError
from knowledge_guard.models import Hit

HIT = Hit(7, 2, 'Leave & "Flexitime"', "30 working days per year.", "Intern", 0.12)


def scripted_client(responses: list[httpx.Response]) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upstream.time, "sleep", lambda _seconds: None)


def call(client: httpx.Client, retries: int = 2) -> dict[str, Any]:
    return upstream.post_json(
        "https://api.example.com/v1",
        headers={},
        payload={},
        timeout=1,
        retries=retries,
        client=client,
    )


def test_transient_errors_are_retried() -> None:
    client, seen = scripted_client(
        [httpx.Response(529), httpx.Response(429), httpx.Response(200, json={"ok": True})]
    )
    assert call(client) == {"ok": True}
    assert len(seen) == 3


def test_client_errors_are_not_retried() -> None:
    client, seen = scripted_client([httpx.Response(401, text="bad key")])
    with pytest.raises(UpstreamError, match="HTTP 401"):
        call(client)
    assert len(seen) == 1


def test_retries_are_bounded() -> None:
    client, seen = scripted_client([httpx.Response(503)] * 3)
    with pytest.raises(UpstreamError, match=r"api\.example\.com"):
        call(client, retries=2)
    assert len(seen) == 3


def test_network_errors_are_retried() -> None:
    attempts = iter([httpx.ConnectError("down"), httpx.Response(200, json={"ok": 1})])

    def handler(request: httpx.Request) -> httpx.Response:
        outcome = next(attempts)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert call(client) == {"ok": 1}


def test_context_marks_documents_as_material_and_escapes_titles() -> None:
    context = llm.build_context([HIT])
    assert context.startswith('<source title="Leave &amp; &quot;Flexitime&quot;" chunk="7">')
    assert llm.build_context([]) == "<no-source/>"


def test_extractive_mode_without_keys() -> None:
    text, mode = llm.answer("leave?", [HIT])
    assert mode == "extractive"
    assert "30 working days per year." in text
    assert llm.answer("leave?", []) == (llm.NO_SOURCES_ANSWER, "extractive")


def test_complete_without_provider_raises() -> None:
    with pytest.raises(UpstreamError, match="No language model"):
        llm.complete([{"role": "user", "content": "hi"}])


def test_parse_anthropic_response() -> None:
    completion = llm.parse_anthropic(
        {
            "content": [
                {"type": "text", "text": "Checking. "},
                {"type": "tool_use", "id": "t1", "name": "list_catalog", "input": {}},
            ]
        }
    )
    assert completion.text == "Checking."
    assert completion.tool_calls == [llm.ToolCall("t1", "list_catalog", {})]


def test_parse_openai_response() -> None:
    message = {
        "content": None,
        "tool_calls": [
            {"id": "c1", "function": {"name": "summarize", "arguments": '{"topic": "leave"}'}}
        ],
    }
    completion = llm.parse_openai({"choices": [{"message": message}]})
    assert completion.text == ""
    assert completion.tool_calls == [llm.ToolCall("c1", "summarize", {"topic": "leave"})]


def test_tool_conversation_translates_to_openai() -> None:
    messages = [
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "c1", "name": "list_catalog", "input": {}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "c1", "content": {"n": 1}}],
        },
    ]
    converted = llm.to_openai_messages(messages)
    assert converted[0] == {"role": "user", "content": "task"}
    assert converted[1]["tool_calls"][0]["function"] == {"name": "list_catalog", "arguments": "{}"}
    assert converted[2] == {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"n": 1})}
