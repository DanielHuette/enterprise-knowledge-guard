"""Datenbankzugang.

Bewusst ohne Abfrage-Baukasten (ORM). Die beiden Zeilen, auf die es in diesem
Projekt ankommt -- der Sicherheitsfilter und der Vektorvergleich <=> -- sollen
im Klartext lesbar und pruefbar sein. Ein Baukasten wuerde genau sie verstecken.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings


def _configure(conn: psycopg.Connection) -> None:
    conn.row_factory = dict_row


def to_vector(values: list[float]) -> str:
    """Vektor als Textwert fuer PostgreSQL.

    Bewusst von Hand: '[0.1,0.2,...]' plus ::vector im SQL. Das spart eine
    Abhaengigkeit und macht sichtbar, was an die Datenbank geht.
    """
    return "[" + ",".join(f"{value:.7g}" for value in values) + "]"


_app_pool: ConnectionPool | None = None


def app_pool() -> ConnectionPool:
    global _app_pool
    if _app_pool is None:
        _app_pool = ConnectionPool(
            settings.app_dsn, min_size=1, max_size=10,
            configure=_configure, open=True, timeout=30,
        )
    return _app_pool


@contextmanager
def as_user(user_id: int | None) -> Iterator[psycopg.Connection]:
    """Verbindung mit gesetzter Identitaet.

    SET LOCAL gilt nur fuer diese Transaktion. Danach ist die Verbindung wieder
    identitaetslos -- eine aus dem Pool geholte Verbindung kann also nie die
    Rechte eines vorherigen Nutzers mitbringen.
    """
    with app_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.user_id', %s, true)",
                ("" if user_id is None else str(user_id),),
            )
        yield conn


@contextmanager
def as_owner() -> Iterator[psycopg.Connection]:
    """Eigentuemer-Verbindung: Einrichtung und Beispieldaten, sonst nichts."""
    with psycopg.connect(settings.owner_dsn, autocommit=False) as conn:
        _configure(conn)
        yield conn
        conn.commit()


def fetch_all(conn: psycopg.Connection, sql: str, params=None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return list(cur.fetchall())


def fetch_one(conn: psycopg.Connection, sql: str, params=None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchone()
