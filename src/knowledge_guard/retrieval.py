"""Vector search with the access check inside the same query.

Context: One query measures similarity and checks access at once; there is no step in
which blocked content sits in the application's memory, because it never leaves the
database. | Input: user id and question. | Output: released hits and the number of
blocked hits among the global top k.
"""

from __future__ import annotations

import psycopg

from knowledge_guard.config import get_settings
from knowledge_guard.db import Connection, as_user, fetch_all, fetch_one, to_vector
from knowledge_guard.embeddings import embed_one
from knowledge_guard.models import Hit, SearchResult

# The kg_visible line is the difference between a company chatbot and a data breach.
SEARCH_SQL = """
SELECT c.id,
       c.document_id,
       d.title,
       c.content,
       c.min_required_role,
       (c.embedding <=> %(query)s::vector) AS distance
  FROM document_chunks c
  JOIN documents d ON d.id = c.document_id
 WHERE kg_visible(%(user_id)s, c.department_id, c.min_required_role, c.document_id)
   AND c.embedding IS NOT NULL
 ORDER BY c.embedding <=> %(query)s::vector
 LIMIT %(k)s
"""

BLOCKED_COUNT_SQL = "SELECT kg_blocked_count(%(user_id)s, %(query)s::vector, %(k)s) AS n"


def search(user_id: int, question: str, k: int | None = None) -> SearchResult:
    """Return the k nearest chunks the user may read."""
    settings = get_settings()
    limit = k or settings.top_k
    params = {"query": to_vector(embed_one(question)), "user_id": user_id, "k": limit}
    with as_user(user_id) as conn:
        _enable_iterative_scan(conn)
        rows = fetch_all(conn, SEARCH_SQL, params)
        blocked = _blocked_count(conn, params) if settings.show_blocked_count else 0
    hits = [
        Hit(
            chunk_id=row["id"],
            document_id=row["document_id"],
            title=row["title"],
            content=row["content"],
            min_required_role=row["min_required_role"],
            distance=float(row["distance"]),
        )
        for row in rows
    ]
    return SearchResult(hits=hits, blocked_count=blocked)


def _blocked_count(conn: Connection, params: dict[str, object]) -> int:
    row = fetch_one(conn, BLOCKED_COUNT_SQL, params)
    return int(row["n"] or 0) if row else 0


def _enable_iterative_scan(conn: Connection) -> None:
    """Let the vector index fetch more neighbours when the access filter removes many.

    The index finds nearest neighbours first and the filter applies afterwards; without
    iterative scans a strict classification could return fewer hits than exist (never
    more). pgvector before 0.8 does not know the setting, so a savepoint keeps the
    transaction usable there.
    """
    try:
        with conn.transaction():
            conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
    except (psycopg.errors.UndefinedObject, psycopg.errors.InvalidParameterValue):
        return
