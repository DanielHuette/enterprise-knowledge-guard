"""Agent tools, each bound to a minimum role.

Context: The same idea as for documents, applied to actions. Two layers: the model only
sees the tools its role allows, and the role is checked again right before execution, so
an invented or overheard tool name fails. Anything that passes both still hits row-level
security in the database. Every call, allowed or denied, is audited. | Input: tool name,
arguments, caller. | Output: tool result as a JSON-serialisable dict.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

import psycopg

from knowledge_guard import audit, llm
from knowledge_guard.config import get_settings
from knowledge_guard.db import Connection, as_user, fetch_all, fetch_one
from knowledge_guard.errors import ActionRejected, ToolDenied
from knowledge_guard.models import SearchResult, User
from knowledge_guard.retrieval import search

Args = dict[str, Any]
Result = dict[str, Any]
Handler = Callable[[Args, User], tuple[Result, SearchResult | None]]

COMPANY_WIDE = "company-wide"
DECISIONS = ("approved", "denied")
MIN_GRANT_DAYS = 1
MAX_GRANT_DAYS = 365
AUDIT_DEFAULT_LIMIT = 20

CATALOG_SQL = """
SELECT c.id, c.title, c.department, c.min_required_role,
       kg_visible(%(uid)s, c.department_id, c.min_required_role, c.id) AS readable
  FROM document_catalog c
 ORDER BY c.id
"""

INSERT_REQUEST_SQL = """
INSERT INTO access_requests (requester_id, document_id, reason)
VALUES (%(uid)s, %(doc)s, %(reason)s)
RETURNING id
"""

DECIDE_REQUEST_SQL = """
UPDATE access_requests
   SET status = %(status)s, decided_by = %(uid)s, decided_at = now()
 WHERE id = %(id)s AND status = 'pending'
RETURNING id, requester_id, document_id
"""

UPSERT_GRANT_SQL = """
INSERT INTO access_grants (user_id, document_id, granted_by, request_id, expires_at)
VALUES (%(uid)s, %(doc)s, %(by)s, %(req)s, %(exp)s)
ON CONFLICT (user_id, document_id)
DO UPDATE SET expires_at = EXCLUDED.expires_at,
              granted_by = EXCLUDED.granted_by,
              request_id = EXCLUDED.request_id
"""


@dataclass(frozen=True)
class Tool:
    name: str
    min_role: str
    description: str
    parameters: dict[str, Any]
    handler: Handler

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


@cache
def role_ranks() -> dict[str, int]:
    """Role ranks from the roles table, the single source of the hierarchy."""
    with as_user(None) as conn:
        return {row["name"]: row["rank"] for row in fetch_all(conn, "SELECT name, rank FROM roles")}


def rank_of(role: str) -> int:
    return role_ranks().get(role, 0)


def allowed_tools(user: User) -> list[Tool]:
    """Layer 1: tools the role may not use are never shown to the model."""
    have = rank_of(user.role)
    return [tool for tool in REGISTRY.values() if rank_of(tool.min_role) <= have]


def authorize(name: str, user: User) -> Tool:
    """Layer 2: check the role immediately before execution.

    Raises:
        ToolDenied: If the tool does not exist or the role is too low.
    """
    tool = REGISTRY.get(name)
    if tool is None:
        raise ToolDenied(name, "-", user.role)
    if rank_of(user.role) < rank_of(tool.min_role):
        raise ToolDenied(name, tool.min_role, user.role)
    return tool


def execute(name: str, args: Args, user: User) -> Result:
    """Authorise, run and audit one tool call.

    Raises:
        ToolDenied: If the caller may not use the tool; the denial is audited first.
        ActionRejected: If the data does not permit the request; audited as a denial.
    """
    try:
        tool = authorize(name, user)
    except ToolDenied as denied:
        audit.record(
            user.id, f"tool:{name}", "deny", detail={"reason": str(denied), "arguments": args}
        )
        raise
    try:
        result, searched = tool.handler(args, user)
    except ActionRejected as rejected:
        audit.record(
            user.id, f"tool:{name}", "deny", detail={"reason": str(rejected), "arguments": args}
        )
        raise
    audit.record(
        user.id,
        f"tool:{name}",
        "allow",
        question=args.get("question") or args.get("topic") or args.get("subject"),
        chunk_ids=searched.chunk_ids if searched else None,
        blocked_count=searched.blocked_count if searched else 0,
        detail={"arguments": args},
    )
    return result


def _search_knowledge(args: Args, user: User) -> tuple[Result, SearchResult]:
    question = str(args.get("question") or "").strip()
    found = search(user.id, question)
    text, mode = llm.answer(question, found.hits)
    result = {
        "answer": text,
        "mode": mode,
        "blocked_count": found.blocked_count,
        "sources": found.sources,
    }
    return result, found


def _summarize(args: Args, user: User) -> tuple[Result, SearchResult]:
    topic = str(args.get("topic") or "").strip()
    found = search(user.id, topic)
    result = {
        "summary": llm.summarize(found.hits, topic),
        "blocked_count": found.blocked_count,
        "sources": found.sources,
    }
    return result, found


def _list_catalog(_args: Args, user: User) -> tuple[Result, None]:
    with as_user(user.id) as conn:
        rows = fetch_all(conn, CATALOG_SQL, {"uid": user.id})
    documents = [
        {
            "id": row["id"],
            "title": row["title"],
            "department": row["department"] or COMPANY_WIDE,
            "min_required_role": row["min_required_role"],
            "readable": bool(row["readable"]),
        }
        for row in rows
    ]
    return {"documents": documents}, None


def _request_access(args: Args, user: User) -> tuple[Result, None]:
    document_id = int(args["document_id"])
    reason = str(args.get("reason") or "").strip() or "no reason given"
    with as_user(user.id) as conn:
        document = fetch_one(
            conn, "SELECT id, title FROM document_catalog WHERE id = %(id)s", {"id": document_id}
        )
        if document is None:
            raise ActionRejected(f"Document {document_id} does not exist.", status_code=404)
        row = fetch_one(
            conn, INSERT_REQUEST_SQL, {"uid": user.id, "doc": document_id, "reason": reason}
        )
    return {
        "request_id": row["id"] if row else None,
        "document": document["title"],
        "status": "pending",
        "note": "A manager decides. Access does not change until then.",
    }, None


def _decide_request(args: Args, user: User) -> tuple[Result, None]:
    request_id = int(args["request_id"])
    decision = str(args.get("decision") or "approved").strip().lower()
    if decision not in DECISIONS:
        raise ActionRejected("decision must be 'approved' or 'denied'.", status_code=422)
    days = _grant_days(args.get("days"))
    with as_user(user.id) as conn:
        request = fetch_one(
            conn, DECIDE_REQUEST_SQL, {"status": decision, "uid": user.id, "id": request_id}
        )
        if request is None:
            raise ActionRejected(
                f"No pending request {request_id} that you may decide. Managers decide "
                "requests for documents they can read themselves, never their own.",
                status_code=404,
            )
        if decision == "denied":
            return {"request_id": request_id, "status": "denied"}, None
        try:
            expires = _grant(conn, request, granted_by=user.id, days=days)
        except psycopg.errors.InsufficientPrivilege as error:
            raise ActionRejected("The database refused the grant.", status_code=403) from error
    return {
        "request_id": request_id,
        "status": "approved",
        "valid_until": expires.isoformat(timespec="seconds"),
        "note": "Time-limited and valid for this one document only.",
    }, None


def _grant_days(raw: object) -> int:
    if raw is None or raw == "":
        return get_settings().grant_days_default
    try:
        days = int(str(raw))
    except ValueError as error:
        raise ActionRejected(f"days must be a whole number, got {raw!r}.", 422) from error
    if not MIN_GRANT_DAYS <= days <= MAX_GRANT_DAYS:
        raise ActionRejected(
            f"days must be between {MIN_GRANT_DAYS} and {MAX_GRANT_DAYS}, got {days}.", 422
        )
    return days


def _grant(conn: Connection, request: dict[str, Any], *, granted_by: int, days: int) -> datetime:
    expires = datetime.now(UTC) + timedelta(days=days)
    conn.execute(
        UPSERT_GRANT_SQL,
        {
            "uid": request["requester_id"],
            "doc": request["document_id"],
            "by": granted_by,
            "req": request["id"],
            "exp": expires,
        },
    )
    return expires


def _draft_email(args: Args, user: User) -> tuple[Result, SearchResult]:
    recipient = str(args.get("recipient") or "").strip() or "Team"
    subject = str(args.get("subject") or "").strip()
    found = search(user.id, subject)
    if llm.provider() == "none":
        draft = _extractive_draft(recipient, subject, found, user)
    else:
        prompt = (
            f"{llm.build_context(found.hits)}\n\n<task>Draft a short, factual e-mail to "
            f"{recipient} about: {subject}. Use only content from the sources. "
            "Include a subject line.</task>"
        )
        draft = llm.complete([{"role": "user", "content": prompt}]).text
    result = {
        "draft": draft,
        "sent": False,
        "note": "Draft only. The system never sends anything on its own.",
        "sources": found.sources,
    }
    return result, found


def _extractive_draft(recipient: str, subject: str, found: SearchResult, user: User) -> str:
    facts = "\n".join(f"- {hit.content.strip()}" for hit in found.hits)
    return (
        f"Subject: {subject}\n\nHello {recipient},\n\n"
        f'on "{subject}" the released documents say:\n\n'
        f"{facts or '- no released documents found'}\n\n"
        f"Best regards\n{user.display_name}"
    )


def _read_audit_log(args: Args, user: User) -> tuple[Result, None]:
    rows = audit.read(user.id, int(args.get("limit") or AUDIT_DEFAULT_LIMIT))
    entries = [
        {
            "at": row["at"].isoformat(timespec="seconds"),
            "username": row["username"],
            "role": row["role"],
            "action": row["action"],
            "decision": row["decision"],
            "question": row["question"],
            "allowed_chunk_ids": row["allowed_chunk_ids"],
            "blocked_count": row["blocked_count"],
        }
        for row in rows
    ]
    return {"entries": entries}, None


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def _string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


REGISTRY: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "search_knowledge",
            "Intern",
            "Answers a question from the company documents released to the user.",
            _schema({"question": _string("The question in plain language.")}, ["question"]),
            _search_knowledge,
        ),
        Tool(
            "list_catalog",
            "Intern",
            "Lists all documents with department and required role. Shows no content.",
            _schema({}, []),
            _list_catalog,
        ),
        Tool(
            "request_access",
            "Intern",
            "Requests read access to a single document. Does not change access itself.",
            _schema(
                {"document_id": {"type": "integer"}, "reason": _string("Why access is needed.")},
                ["document_id", "reason"],
            ),
            _request_access,
        ),
        Tool(
            "summarize",
            "Employee",
            "Summarises the released documents on a topic.",
            _schema({"topic": _string("Topic to summarise.")}, ["topic"]),
            _summarize,
        ),
        Tool(
            "draft_email",
            "Employee",
            "Drafts an e-mail from the released documents. Sends nothing.",
            _schema(
                {"recipient": _string("Addressee."), "subject": _string("What it is about.")},
                ["recipient", "subject"],
            ),
            _draft_email,
        ),
        Tool(
            "decide_request",
            "Manager",
            "Approves or denies an access request. Approval creates time-limited read access.",
            _schema(
                {
                    "request_id": {"type": "integer"},
                    "decision": {"type": "string", "enum": list(DECISIONS)},
                    "days": {
                        "type": "integer",
                        "minimum": MIN_GRANT_DAYS,
                        "maximum": MAX_GRANT_DAYS,
                    },
                },
                ["request_id", "decision"],
            ),
            _decide_request,
        ),
        Tool(
            "read_audit_log",
            "Admin",
            "Reads the access audit log.",
            _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 200}}, []),
            _read_audit_log,
        ),
    )
}
