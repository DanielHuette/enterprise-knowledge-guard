"""Load the demo data.

Context: Runs with the owner connection and is idempotent: if users exist, nothing
happens unless force is set, which truncates and reloads everything in one transaction.
All chunks are embedded in a single batch call.
| Input: seed_data constants. | Output: summary of what was loaded.

Usage:
    python -m knowledge_guard.seed [--force]
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterator
from typing import Any

from knowledge_guard.db import Connection, as_owner, fetch_one, to_vector
from knowledge_guard.embeddings import embed
from knowledge_guard.seed_data import DEPARTMENTS, DOCUMENTS, USERS

logger = logging.getLogger(__name__)

TRUNCATE_SQL = (
    "TRUNCATE audit_log, access_grants, access_requests, document_chunks, documents, "
    "user_departments, users, departments RESTART IDENTITY CASCADE"
)


def is_seeded() -> bool:
    with as_owner() as conn:
        row = fetch_one(conn, "SELECT count(*) AS n FROM users")
    return bool(row and row["n"])


def seed(*, force: bool = False) -> dict[str, Any]:
    """Load the demo data; returns counts or 'already present'."""
    if not force and is_seeded():
        return {"status": "already present"}
    texts = [chunk for document in DOCUMENTS for chunk in document["chunks"]]
    vectors = iter(embed(texts))
    with as_owner() as conn:
        if force:
            conn.execute(TRUNCATE_SQL)
        department_ids = _insert_departments(conn)
        _insert_users(conn, department_ids)
        _insert_documents(conn, department_ids, vectors)
    logger.info("Demo data loaded: %d documents, %d chunks", len(DOCUMENTS), len(texts))
    return {
        "status": "loaded",
        "users": len(USERS),
        "documents": len(DOCUMENTS),
        "chunks": len(texts),
    }


def _insert_departments(conn: Connection) -> dict[str, int]:
    ids: dict[str, int] = {}
    for name in DEPARTMENTS:
        row = fetch_one(conn, "INSERT INTO departments (name) VALUES (%s) RETURNING id", (name,))
        ids[name] = _id(row)
    return ids


def _insert_users(conn: Connection, department_ids: dict[str, int]) -> None:
    for user in USERS:
        row = fetch_one(
            conn,
            "INSERT INTO users (username, display_name, job_title, role) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (user["username"], user["display_name"], user["job_title"], user["role"]),
        )
        user_id = _id(row)
        for department in user["departments"]:
            conn.execute(
                "INSERT INTO user_departments (user_id, department_id) VALUES (%s, %s)",
                (user_id, department_ids[department]),
            )


def _insert_documents(
    conn: Connection, department_ids: dict[str, int], vectors: Iterator[list[float]]
) -> None:
    for document in DOCUMENTS:
        department = document["department"]
        row = fetch_one(
            conn,
            "INSERT INTO documents (title, department_id, min_required_role) "
            "VALUES (%s, %s, %s) RETURNING id",
            (
                document["title"],
                department_ids[department] if department else None,
                document["min_required_role"],
            ),
        )
        document_id = _id(row)
        for index, chunk in enumerate(document["chunks"]):
            conn.execute(
                "INSERT INTO document_chunks (document_id, chunk_index, content, embedding) "
                "VALUES (%s, %s, %s, %s::vector)",
                (document_id, index, chunk, to_vector(next(vectors))),
            )


def _id(row: dict[str, Any] | None) -> int:
    if row is None:
        raise RuntimeError("INSERT ... RETURNING id returned no row")
    return int(row["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the demo data.")
    parser.add_argument("--force", action="store_true", help="truncate and reload")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = seed(force=parser.parse_args().force)
    logger.info("Seed result: %s", result)


if __name__ == "__main__":
    main()
