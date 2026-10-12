"""Layer 2: what happens when the application's filter is missing?

These tests bypass the application logic and send raw SQL over the service's own
connection. If a blocked row came back here, security would be one line of Python away.
"""

from __future__ import annotations

import psycopg
import pytest

from knowledge_guard.db import as_user, fetch_all, fetch_one
from knowledge_guard.models import User

SALARY_MARKER_PATTERN = "%92,000%"


def count_chunks(user_id: int | None) -> int:
    with as_user(user_id) as conn:
        row = fetch_one(conn, "SELECT count(*) AS n FROM document_chunks")
    assert row is not None
    return int(row["n"])


def test_application_role_is_not_the_owner() -> None:
    """Row-level security would not apply to the owner."""
    with as_user(None) as conn:
        row = fetch_one(
            conn,
            """
            SELECT current_user AS who,
                   (SELECT rolsuper OR rolbypassrls FROM pg_roles
                     WHERE rolname = current_user) AS can_bypass,
                   pg_get_userbyid(c.relowner) AS owner
              FROM pg_class c WHERE c.relname = 'document_chunks'
            """,
        )
    assert row is not None
    assert row["can_bypass"] is False
    assert row["owner"] != row["who"]


def test_no_identity_means_no_rows() -> None:
    assert count_chunks(None) == 0


def test_raw_sql_bypasses_nothing(users: dict[str, User], markers: dict[str, list[str]]) -> None:
    with as_user(users["tom.schaefer"].id) as conn:
        text = " ".join(
            row["content"] for row in fetch_all(conn, "SELECT content FROM document_chunks")
        )
    for marker in markers["Salary Bands 2026"]:
        assert marker not in text


def test_targeted_search_for_the_secret_figure(users: dict[str, User]) -> None:
    with as_user(users["tom.schaefer"].id) as conn:
        rows = fetch_all(
            conn,
            "SELECT id FROM document_chunks WHERE content LIKE %(p)s",
            {"p": SALARY_MARKER_PATTERN},
        )
    assert rows == []


def test_aggregates_only_see_released_rows(users: dict[str, User]) -> None:
    assert count_chunks(users["tom.schaefer"].id) < count_chunks(users["sarah.brandt"].id)


def test_catalog_shows_titles_but_documents_stay_hidden(users: dict[str, User]) -> None:
    """Deliberate: the intern may know the salary bands exist, so he can request access."""
    with as_user(users["tom.schaefer"].id) as conn:
        catalog = [row["title"] for row in fetch_all(conn, "SELECT title FROM document_catalog")]
        visible = [row["title"] for row in fetch_all(conn, "SELECT title FROM documents")]
    assert "Salary Bands 2026" in catalog
    assert "Salary Bands 2026" not in visible


def test_application_cannot_reclassify_documents(users: dict[str, User]) -> None:
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_user(users["tom.schaefer"].id) as conn,
    ):
        conn.execute(
            "UPDATE documents SET min_required_role = 'Intern' WHERE title = 'Salary Bands 2026'"
        )


def test_application_cannot_disable_row_level_security(users: dict[str, User]) -> None:
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_user(users["tom.schaefer"].id) as conn,
    ):
        conn.execute("ALTER TABLE document_chunks DISABLE ROW LEVEL SECURITY")


def test_application_cannot_delete_audit_entries(users: dict[str, User]) -> None:
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_user(users["sarah.brandt"].id) as conn,
    ):
        conn.execute("DELETE FROM audit_log")


def test_identity_is_transaction_local(users: dict[str, User]) -> None:
    """A pooled connection never carries a previous user's rights."""
    assert count_chunks(users["sarah.brandt"].id) > 0
    assert count_chunks(None) == 0


def test_identity_setting_is_the_trust_boundary(users: dict[str, User]) -> None:
    """Documented on purpose: the database trusts app.user_id.

    Only code holding the service's connection can set it, and the service sets it only
    from a signed token. This test pins that behaviour so it cannot change unnoticed.
    """
    query = "SELECT id FROM document_chunks WHERE content LIKE %(p)s"
    with as_user(users["tom.schaefer"].id) as conn:
        before = fetch_all(conn, query, {"p": SALARY_MARKER_PATTERN})
        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(users["sarah.brandt"].id),))
        after = fetch_all(conn, query, {"p": SALARY_MARKER_PATTERN})
    assert before == []
    assert after
