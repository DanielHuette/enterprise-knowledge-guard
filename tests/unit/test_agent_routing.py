"""Keyword routing used when no language model is configured."""

from __future__ import annotations

import pytest

from knowledge_guard.agent import AgentResult, route


@pytest.mark.parametrize(
    ("task", "tool", "args"),
    [
        ("Which documents exist?", "list_catalog", {}),
        ("show the audit log", "read_audit_log", {"limit": 20}),
        ("Please log in", "search_knowledge", {"question": "Please log in"}),
        ("approve request 12", "decide_request", {"request_id": 12, "decision": "approved"}),
        ("deny request 3 please", "decide_request", {"request_id": 3, "decision": "denied"}),
        ("summarize the leave policy", "summarize", {"topic": "summarize the leave policy"}),
        ("How much leave do I get?", "search_knowledge", {"question": "How much leave do I get?"}),
    ],
)
def test_route(task: str, tool: str, args: dict[str, object]) -> None:
    assert route(task) == (tool, args)


def test_request_uses_the_first_number_only() -> None:
    name, args = route("request document 4 for 7 days")
    assert name == "request_access"
    assert args["document_id"] == 4


def test_login_is_not_the_audit_log() -> None:
    assert route("how do I login to the laptop")[0] == "search_knowledge"


def test_mail_routes_to_draft() -> None:
    assert route("write a mail about the leave policy")[0] == "draft_email"


def test_collect_deduplicates_sources_and_keeps_the_highest_block_count() -> None:
    result = AgentResult(answer="", mode="extractive")
    source = {"chunk_id": 1}
    result.collect({"sources": [source], "blocked_count": 2})
    result.collect({"sources": [source], "blocked_count": 1})
    assert result.sources == [source]
    assert result.blocked_count == 2
