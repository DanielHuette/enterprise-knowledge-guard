"""Shared fixtures for the integration tests.

Context: These tests run against a real PostgreSQL with pgvector on purpose: the access
logic lives in the database, so it has to be tested there. A mocked database would test
exactly what is not shipped. | Input: database from docker compose. | Output: seeded
data set and lookup fixtures.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from knowledge_guard.config import get_settings
from knowledge_guard.db import as_owner, as_user, close_pool, fetch_all
from knowledge_guard.models import User
from knowledge_guard.seed import seed
from knowledge_guard.seed_data import SECRET_MARKERS
from knowledge_guard.tools import role_ranks


@pytest.fixture(scope="session", autouse=True)
def seeded_database(session_env: None) -> Iterator[None]:
    seed(force=True)
    role_ranks.cache_clear()
    yield
    close_pool()


@pytest.fixture(scope="session")
def session_env() -> Iterator[None]:
    """Integration tests never call a paid provider."""
    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_PROVIDER", "none")
    mp.setenv("EMBEDDING_PROVIDER", "local")
    get_settings.cache_clear()
    yield
    mp.undo()
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def users() -> dict[str, User]:
    with as_user(None) as conn:
        rows = fetch_all(conn, "SELECT id, username, display_name, job_title, role FROM users")
    return {row["username"]: User.from_row(row) for row in rows}


@pytest.fixture(scope="session")
def documents() -> dict[str, int]:
    with as_owner() as conn:
        rows = fetch_all(conn, "SELECT id, title FROM documents")
    return {row["title"]: row["id"] for row in rows}


@pytest.fixture(scope="session")
def chunk_ids() -> dict[str, list[int]]:
    """Chunk ids per document title: the yardstick for a leak."""
    with as_owner() as conn:
        rows = fetch_all(
            conn,
            "SELECT d.title, array_agg(c.id) AS ids FROM document_chunks c "
            "JOIN documents d ON d.id = c.document_id GROUP BY d.title",
        )
    return {row["title"]: row["ids"] for row in rows}


@pytest.fixture(scope="session")
def markers() -> dict[str, list[str]]:
    return SECRET_MARKERS
