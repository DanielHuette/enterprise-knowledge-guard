"""Gemeinsame Vorbereitung der Testreihe.

Die Tests laufen gegen eine echte PostgreSQL-Datenbank mit pgvector. Das ist
Absicht: die Rechtelogik liegt in der Datenbank, also muss sie dort geprueft
werden. Ein Test mit nachgebauter Datenbank wuerde genau das pruefen, was
nicht ausgeliefert wird.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Funktioniert im Container (/app) wie auch direkt im Projektordner.
for _kandidat in (
    Path(__file__).resolve().parents[1] / "api",
    Path("/app"),
    Path(__file__).resolve().parents[1],
):
    if (_kandidat / "app" / "__init__.py").exists():
        sys.path.insert(0, str(_kandidat))
        break

from app.db import as_owner, as_user, fetch_all, fetch_one  # noqa: E402
from app.seed import seed  # noqa: E402
from app.seed_data import SECRET_MARKERS  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def bestand():
    """Frischer Beispielbestand fuer den gesamten Durchlauf."""
    seed(force=True)


@pytest.fixture(scope="session")
def nutzer() -> dict[str, dict]:
    with as_user(None) as conn:
        rows = fetch_all(conn, "SELECT id, username, display_name, role FROM users")
    return {row["username"]: row for row in rows}


@pytest.fixture(scope="session")
def dokumente() -> dict[str, dict]:
    with as_owner() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT d.id, d.title, d.min_required_role, dep.name AS department
              FROM documents d
              LEFT JOIN departments dep ON dep.id = d.department_id
            """,
        )
    return {row["title"]: row for row in rows}


@pytest.fixture(scope="session")
def geheime_abschnitte() -> dict[str, list[int]]:
    """Abschnittskennungen je Dokumenttitel -- der Massstab fuer ein Leck."""
    with as_owner() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT d.title, array_agg(c.id) AS ids
              FROM document_chunks c JOIN documents d ON d.id = c.document_id
             GROUP BY d.title
            """,
        )
    return {row["title"]: row["ids"] for row in rows}


@pytest.fixture(scope="session")
def markierungen() -> dict[str, list[str]]:
    return SECRET_MARKERS


def app_connection_role() -> str:
    with as_user(None) as conn:
        row = fetch_one(conn, "SELECT current_user AS who")
    return row["who"]
