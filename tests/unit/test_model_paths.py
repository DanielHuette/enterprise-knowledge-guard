"""Model-backed paths of agent, answer and embedding with the HTTP layer replaced."""

from __future__ import annotations

from typing import Any

import pytest

from knowledge_guard import agent, embeddings, llm, tools
from knowledge_guard.config import get_settings
from knowledge_guard.errors import ActionRejected, ToolDenied
from knowledge_guard.models import Hit, User

TOM = User(5, "tom.schaefer", "Tom Schaefer", "Engineering Intern", "Intern")
HIT = Hit(1, 1, "Leave and Flexitime Policy", "30 working days.", "Intern", 0.1)


@pytest.fixture
def anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()


def test_answer_sends_sources_to_anthropic(
    monkeypatch: pytest.MonkeyPatch, anthropic_key: None
) -> None:
    sent: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> dict[str, Any]:
        sent.update(url=url, **kwargs)
        return {"content": [{"type": "text", "text": "30 working days."}]}

    monkeypatch.setattr(llm, "post_json", fake_post)
    text, mode = llm.answer("How much leave?", [HIT])
    assert (text, mode) == ("30 working days.", "anthropic")
    assert sent["url"] == llm.ANTHROPIC_URL
    assert sent["headers"]["x-api-key"] == "sk-test"
    assert "<source" in sent["payload"]["messages"][0]["content"]


def test_openai_receives_function_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    get_settings.cache_clear()
    sent: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> dict[str, Any]:
        sent.update(kwargs["payload"])
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(llm, "post_json", fake_post)
    spec = {"name": "list_catalog", "description": "d", "parameters": {"type": "object"}}
    completion = llm.complete([{"role": "user", "content": "hi"}], tools=[spec])
    assert completion.text == "ok"
    assert sent["tools"][0]["function"]["name"] == "list_catalog"
    assert sent["messages"][0]["role"] == "system"


def test_summary_with_model(monkeypatch: pytest.MonkeyPatch, anthropic_key: None) -> None:
    monkeypatch.setattr(llm, "complete", lambda *_a, **_k: llm.Completion("- 30 days"))
    assert llm.summarize([HIT], "leave") == "- 30 days"
    assert llm.summarize([], "leave") == llm.NO_SOURCES_SUMMARY


def test_openai_embeddings_keep_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    response = {"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0]}]}
    monkeypatch.setattr(embeddings, "post_json", lambda *_a, **_k: response)
    assert embeddings.embed(["first", "second"]) == [[1.0], [0.0, 1.0]]


def test_agent_loop_runs_tools_and_reports_denials(
    monkeypatch: pytest.MonkeyPatch, anthropic_key: None
) -> None:
    replies = iter(
        [
            llm.Completion(
                "Let me check.",
                [
                    llm.ToolCall("a", "search_knowledge", {"question": "leave"}),
                    llm.ToolCall("b", "read_audit_log", {}),
                ],
            ),
            llm.Completion("You have 30 days."),
        ]
    )
    conversations: list[list[dict[str, Any]]] = []

    def fake_complete(messages: list[dict[str, Any]], **_kwargs: Any) -> llm.Completion:
        conversations.append(list(messages))
        return next(replies)

    def fake_execute(name: str, args: dict[str, Any], user: User) -> dict[str, Any]:
        if name == "read_audit_log":
            raise ToolDenied(name, "Admin", user.role)
        return {"answer": "30 days", "sources": [HIT.as_source()], "blocked_count": 2}

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(tools, "execute", fake_execute)
    monkeypatch.setattr(tools, "allowed_tools", lambda _user: [tools.REGISTRY["search_knowledge"]])

    result = agent.run("How much leave do I have?", TOM)
    assert result.answer == "You have 30 days."
    assert result.mode == "anthropic"
    assert [step["decision"] for step in result.steps] == ["executed", "denied"]
    assert result.blocked_count == 2
    tool_results = conversations[1][-1]["content"]
    assert '"error": "not allowed"' in tool_results[1]["content"]


def test_rejected_actions_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*_args: Any) -> dict[str, Any]:
        raise ActionRejected("No pending request 3 that you may decide.", 404)

    monkeypatch.setattr(tools, "execute", reject)
    result = agent.run("approve request 3", TOM)
    assert result.steps[0]["decision"] == "rejected"
    assert result.answer.startswith("No pending request 3")


def test_rejection_is_passed_back_to_the_model(
    monkeypatch: pytest.MonkeyPatch, anthropic_key: None
) -> None:
    replies = iter(
        [
            llm.Completion("", [llm.ToolCall("a", "decide_request", {"request_id": 3})]),
            llm.Completion("That request is not yours to decide."),
        ]
    )
    monkeypatch.setattr(llm, "complete", lambda *_a, **_k: next(replies))

    def reject(*_args: Any) -> dict[str, Any]:
        raise ActionRejected("No pending request 3 that you may decide.", 404)

    monkeypatch.setattr(tools, "execute", reject)
    monkeypatch.setattr(tools, "allowed_tools", lambda _user: [])
    result = agent.run("approve request 3", TOM)
    assert result.steps == [
        {
            "tool": "decide_request",
            "decision": "rejected",
            "reason": "No pending request 3 that you may decide.",
        }
    ]


def test_agent_stops_after_the_step_limit(
    monkeypatch: pytest.MonkeyPatch, anthropic_key: None
) -> None:
    looping = llm.Completion("", [llm.ToolCall("x", "list_catalog", {})])
    monkeypatch.setattr(llm, "complete", lambda *_a, **_k: looping)
    monkeypatch.setattr(tools, "execute", lambda *_a: {"documents": []})
    monkeypatch.setattr(tools, "allowed_tools", lambda _user: [])
    result = agent.run("loop forever", TOM)
    assert result.answer == "The task needs more steps than allowed."
    assert len(result.steps) == agent.MAX_STEPS
