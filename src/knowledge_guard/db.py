"""Database access.

Context: Plain SQL instead of an ORM, so the two lines that matter, the security filter
and the vector comparison `<=>`, stay readable and reviewable. The caller's identity is set
per transaction, so a pooled connection never carries a previous user's rights.
| Input: Settings, SQL with named parameters. | Output: connections and rows as dicts.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from knowledge_guard.config import get_settings

logger = logging.getLogger(__name__)

Connection = psycopg.Connection[DictRow]
Params = Mapping[str, Any] | Sequence[Any] | None

_pool: ConnectionPool[Connection] | None = None


def app_pool() -> ConnectionPool[Connection]:
    """Connection pool of the restricted application role, created on first use."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            settings.app_database_url,
            connection_class=psycopg.Connection[DictRow],
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=settings.pool_max_size,
            timeout=30,
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def as_user(user_id: int | None) -> Iterator[Connection]:
    """Yield a pooled connection whose transaction runs with the given identity.

    `set_config(..., true)` is transaction-local: once the block ends the connection is
    anonymous again. No identity means no rows, never all rows.
    """
    with app_pool().connection() as conn:
        conn.execute(
            "SELECT set_config('app.user_id', %s, true)",
            ("" if user_id is None else str(user_id),),
        )
        yield conn


@contextmanager
def as_owner() -> Iterator[Connection]:
    """Owner connection for setup and demo data only; commits on success."""
    with psycopg.connect(get_settings().owner_database_url, row_factory=dict_row) as conn:
        yield conn


def fetch_all(conn: Connection, sql: str, params: Params = None) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(conn: Connection, sql: str, params: Params = None) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def to_vector(values: Sequence[float]) -> str:
    """Render a vector literal for `::vector`; avoids an extra adapter dependency."""
    return "[" + ",".join(f"{value:.7g}" for value in values) + "]"


def wait_for_database(timeout: float, interval: float = 1.5) -> None:
    """Block until the owner connection succeeds, e.g. while the container starts.

    Raises:
        psycopg.OperationalError: If the database is not reachable within the timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            with psycopg.connect(get_settings().owner_database_url, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                raise
            logger.info("Database not reachable yet, retrying in %.1fs", interval)
            time.sleep(interval)
