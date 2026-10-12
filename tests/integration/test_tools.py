"""Rights for actions, not only for documents.

Every tool is bound to a role twice: the model only sees allowed tools, and the role is
checked again before execution.
"""

from __future__ import annotations

import pytest

from knowledge_guard import agent, tools
from knowledge_guard.db import as_user, fetch_all
from knowledge_guard.errors import ToolDenied
from knowledge_guard.models import User


def tool_names(user: User) -> set[str]:
    return {tool.name for tool in tools.allowed_tools(user)}


def test_intern_gets_read_and_request_tools_only(users: dict[str, User]) -> None:
    names = tool_names(users["tom.schaefer"])
    assert {"search_knowledge", "list_catalog", "request_access"} == names


def test_manager_may_decide_but_not_read_the_audit_log(users: dict[str, User]) -> None:
    names = tool_names(users["miriam.kessler"])
    assert "decide_request" in names
    assert "read_audit_log" not in names


def test_admin_sees_every_tool(users: dict[str, User]) -> None:
    assert tool_names(users["sarah.brandt"]) == set(tools.REGISTRY)


def test_calling_a_forbidden_tool_fails(users: dict[str, User]) -> None:
    with pytest.raises(ToolDenied, match="requires at least role 'Manager'"):
        tools.execute(
            "decide_request", {"request_id": 1, "decision": "approved"}, users["tom.schaefer"]
        )


def test_invented_tool_name_fails(users: dict[str, User]) -> None:
    with pytest.raises(ToolDenied):
        tools.execute("release_everything", {}, users["tom.schaefer"])


def test_denied_call_is_audited(users: dict[str, User]) -> None:
    tom = users["tom.schaefer"]
    with pytest.raises(ToolDenied):
        tools.execute("read_audit_log", {}, tom)
    with as_user(tom.id) as conn:
        rows = fetch_all(
            conn,
            "SELECT action FROM audit_log WHERE user_id = %(uid)s AND decision = 'deny' "
            "ORDER BY id DESC LIMIT 5",
            {"uid": tom.id},
        )
    assert "tool:read_audit_log" in [row["action"] for row in rows]


def test_draft_is_never_sent(users: dict[str, User]) -> None:
    result = tools.execute(
        "draft_email", {"recipient": "Team", "subject": "leave policy"}, users["jonas.weber"]
    )
    assert result["sent"] is False
    assert result["draft"].startswith("Subject: leave policy")


def test_catalog_shows_readability_but_no_content(users: dict[str, User]) -> None:
    result = tools.execute("list_catalog", {}, users["tom.schaefer"])
    entry = next(d for d in result["documents"] if d["title"] == "Salary Bands 2026")
    assert entry["readable"] is False
    assert set(entry) == {"id", "title", "department", "min_required_role", "readable"}


def test_summary_uses_released_sources_only(users: dict[str, User]) -> None:
    result = tools.execute("summarize", {"topic": "leave and flexitime"}, users["jonas.weber"])
    assert result["summary"]
    assert all(source["title"] != "Salary Bands 2026" for source in result["sources"])


def test_admin_reads_the_audit_log(users: dict[str, User]) -> None:
    result = tools.execute("read_audit_log", {"limit": 5}, users["sarah.brandt"])
    assert 0 < len(result["entries"]) <= 5


def test_agent_without_model_routes_and_reports_denials(users: dict[str, User]) -> None:
    denied = agent.run("show me the audit log", users["tom.schaefer"])
    assert denied.steps == [
        {"tool": "read_audit_log", "decision": "denied", "reason": denied.steps[0]["reason"]}
    ]
    answered = agent.run("How many days of annual leave do I get?", users["tom.schaefer"])
    assert answered.steps[0]["tool"] == "search_knowledge"
    assert "30 working days" in answered.answer
