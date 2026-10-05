"""Zugriffsprotokoll.

Jede Frage und jeder Werkzeugaufruf landet hier -- mit Nutzer, Entscheidung,
den freigegebenen Abschnitten und der Zahl gesperrter Treffer. Gesperrter
Inhalt wird nicht protokolliert; das Protokoll darf kein Hintertuerchen sein.
"""
from __future__ import annotations

from .db import as_user, fetch_all
from psycopg.types.json import Jsonb

INSERT_SQL = """
INSERT INTO audit_log (user_id, action, decision, question, allowed_chunk_ids,
                       blocked_count, detail)
VALUES (%(user_id)s, %(action)s, %(decision)s, %(question)s, %(chunks)s,
        %(blocked)s, %(detail)s)
RETURNING id
"""


def record(
    user_id: int,
    action: str,
    decision: str,
    question: str | None = None,
    chunk_ids: list[int] | None = None,
    blocked_count: int = 0,
    detail: dict | None = None,
) -> int:
    with as_user(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                INSERT_SQL,
                {
                    "user_id": user_id,
                    "action": action,
                    "decision": decision,
                    "question": question,
                    "chunks": chunk_ids or [],
                    "blocked": blocked_count,
                    "detail": Jsonb(detail or {}),
                },
            )
            return cur.fetchone()["id"]


READ_SQL = """
SELECT a.id, a.at, a.action, a.decision, a.question, a.allowed_chunk_ids,
       a.blocked_count, a.detail, u.username, u.role
  FROM audit_log a
  LEFT JOIN users u ON u.id = a.user_id
 ORDER BY a.at DESC, a.id DESC
 LIMIT %(limit)s
"""


def read(user_id: int, limit: int = 50) -> list[dict]:
    """Zeigt, was die Zeilen-Rechte durchlassen: eigene Zeilen, alles nur fuer
    die Administration. Es braucht hier keine Prüfung im Code."""
    with as_user(user_id) as conn:
        return fetch_all(conn, READ_SQL, {"limit": limit})
