"""Audit log.

Context: Every question and every tool call is recorded with user, decision, released
chunk ids and the number of blocked hits. Blocked content is never logged, so the log
cannot become a back door. Who may read which rows is decided by row-level security,
not by code here. | Input: user id and event data. | Output: log rows.
"""

from __future__ import annotations

from typing import Any, Literal

from psycopg.types.json import Jsonb

from knowledge_guard.db import as_user, fetch_all, fetch_one

Decision = Literal["allow", "deny"]
MAX_READ_LIMIT = 200

INSERT_SQL = """
INSERT INTO audit_log (user_id, action, decision, question, allowed_chunk_ids,
                       blocked_count, detail)
VALUES (%(user_id)s, %(action)s, %(decision)s, %(question)s, %(chunks)s,
        %(blocked)s, %(detail)s)
RETURNING id
"""

READ_SQL = """
SELECT a.id, a.at, a.action, a.decision, a.question, a.allowed_chunk_ids,
       a.blocked_count, a.detail, u.username, u.role
  FROM audit_log a
  LEFT JOIN users u ON u.id = a.user_id
 ORDER BY a.at DESC, a.id DESC
 LIMIT %(limit)s
"""


def record(
    user_id: int,
    action: str,
    decision: Decision,
    *,
    question: str | None = None,
    chunk_ids: list[int] | None = None,
    blocked_count: int = 0,
    detail: dict[str, Any] | None = None,
) -> int:
    """Append one entry and return its id."""
    params = {
        "user_id": user_id,
        "action": action,
        "decision": decision,
        "question": question,
        "chunks": chunk_ids or [],
        "blocked": blocked_count,
        "detail": Jsonb(detail or {}),
    }
    with as_user(user_id) as conn:
        row = fetch_one(conn, INSERT_SQL, params)
    if row is None:
        raise RuntimeError("INSERT ... RETURNING id returned no row")
    return int(row["id"])


def read(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Return the newest entries visible to the user: own rows, or all for admins."""
    with as_user(user_id) as conn:
        return fetch_all(conn, READ_SQL, {"limit": max(1, min(limit, MAX_READ_LIMIT))})
