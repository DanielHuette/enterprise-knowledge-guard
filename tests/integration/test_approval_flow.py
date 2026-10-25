"""The flow that ties everything together: request, decide, expire.

An approved request does not make the intern a manager. It applies to exactly one
document, for a limited time, recorded under the deciding manager's name.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from knowledge_guard import tools
from knowledge_guard.db import as_owner, as_user
from knowledge_guard.errors import ActionRejected, ToolDenied
from knowledge_guard.models import User
from knowledge_guard.retrieval import search

QUESTION = "salary band senior software engineering annual salary"
SALARY_BANDS = "Salary Bands 2026"


def visible_titles(user_id: int, question: str = QUESTION) -> list[str]:
    return [hit.title for hit in search(user_id, question, 10).hits]


def expire_grant(user_id: int, document_id: int) -> None:
    with as_owner() as conn:
        conn.execute(
            "UPDATE access_grants SET expires_at = %(at)s "
            "WHERE user_id = %(uid)s AND document_id = %(doc)s",
            {"at": datetime.now(UTC) - timedelta(days=1), "uid": user_id, "doc": document_id},
        )


def test_complete_flow(
    users: dict[str, User], documents: dict[str, int], markers: dict[str, list[str]]
) -> None:
    tom, miriam = users["tom.schaefer"], users["miriam.kessler"]
    document_id = documents[SALARY_BANDS]
    assert SALARY_BANDS not in visible_titles(tom.id)

    request = tools.execute(
        "request_access", {"document_id": document_id, "reason": "HR project task"}, tom
    )
    assert request["status"] == "pending"
    assert SALARY_BANDS not in visible_titles(tom.id)

    with pytest.raises(ToolDenied):
        tools.execute(
            "decide_request", {"request_id": request["request_id"], "decision": "approved"}, tom
        )

    decision = tools.execute(
        "decide_request",
        {"request_id": request["request_id"], "decision": "approved", "days": 7},
        miriam,
    )
    assert decision["status"] == "approved"
    assert SALARY_BANDS in visible_titles(tom.id)

    personnel = " ".join(
        hit.content for hit in search(tom.id, "written warning personnel number 4711", 10).hits
    )
    for marker in markers["Personnel File Case 4711"]:
        assert marker not in personnel

    expire_grant(tom.id, document_id)
    assert SALARY_BANDS not in visible_titles(tom.id)


def test_denied_request_grants_nothing(users: dict[str, User], documents: dict[str, int]) -> None:
    jonas, miriam = users["jonas.weber"], users["miriam.kessler"]
    request = tools.execute(
        "request_access", {"document_id": documents[SALARY_BANDS], "reason": "curious"}, jonas
    )
    decision = tools.execute(
        "decide_request", {"request_id": request["request_id"], "decision": "denied"}, miriam
    )
    assert decision["status"] == "denied"
    assert SALARY_BANDS not in visible_titles(jonas.id)


def test_nobody_approves_their_own_request(
    users: dict[str, User], documents: dict[str, int]
) -> None:
    miriam = users["miriam.kessler"]
    request = tools.execute(
        "request_access",
        {"document_id": documents["Sales Strategy 2027"], "reason": "planning"},
        miriam,
    )
    with pytest.raises(ActionRejected, match="never their own"):
        tools.execute(
            "decide_request", {"request_id": request["request_id"], "decision": "approved"}, miriam
        )
    assert "Sales Strategy 2027" not in visible_titles(miriam.id, "Benelux target revenue 2027")


def test_managers_cannot_hand_out_documents_they_cannot_read(
    users: dict[str, User], documents: dict[str, int]
) -> None:
    """Miriam leads HR; the sales strategy is not hers to release."""
    tom, miriam = users["tom.schaefer"], users["miriam.kessler"]
    request = tools.execute(
        "request_access", {"document_id": documents["Sales Strategy 2027"], "reason": "x"}, tom
    )
    with pytest.raises(ActionRejected) as rejected:
        tools.execute(
            "decide_request", {"request_id": request["request_id"], "decision": "approved"}, miriam
        )
    assert rejected.value.status_code == 404
    assert "Sales Strategy 2027" not in visible_titles(tom.id, "Benelux target revenue 2027")


def test_managers_cannot_grant_themselves_access(
    users: dict[str, User], documents: dict[str, int]
) -> None:
    miriam = users["miriam.kessler"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(miriam.id) as conn:
        conn.execute(
            "INSERT INTO access_grants (user_id, document_id, granted_by, expires_at) "
            "VALUES (%(me)s, %(doc)s, %(me)s, now() + interval '1 day')",
            {"me": miriam.id, "doc": documents["Sales Strategy 2027"]},
        )


def test_managers_cannot_grant_documents_outside_their_reach(
    users: dict[str, User], documents: dict[str, int]
) -> None:
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_user(users["miriam.kessler"].id) as conn,
    ):
        conn.execute(
            "INSERT INTO access_grants (user_id, document_id, granted_by, expires_at) "
            "VALUES (%(tom)s, %(doc)s, %(me)s, now() + interval '1 day')",
            {
                "tom": users["tom.schaefer"].id,
                "me": users["miriam.kessler"].id,
                "doc": documents["Sales Strategy 2027"],
            },
        )


def test_requests_on_behalf_of_others_are_rejected(
    users: dict[str, User], documents: dict[str, int]
) -> None:
    """Row-level security requires requester_id to be the caller."""
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_user(users["tom.schaefer"].id) as conn,
    ):
        conn.execute(
            "INSERT INTO access_requests (requester_id, document_id, reason) "
            "VALUES (%(other)s, %(doc)s, 'on behalf of someone else')",
            {"other": users["jonas.weber"].id, "doc": documents[SALARY_BANDS]},
        )


def test_request_for_unknown_document(users: dict[str, User]) -> None:
    with pytest.raises(ActionRejected, match="Document 99999 does not exist"):
        tools.execute(
            "request_access", {"document_id": 99999, "reason": "x"}, users["tom.schaefer"]
        )


@pytest.mark.parametrize(
    "args",
    [
        {"request_id": 1, "decision": "maybe"},
        {"request_id": 1, "decision": "approved", "days": 0},
        {"request_id": 1, "decision": "approved", "days": -3},
        {"request_id": 1, "decision": "approved", "days": 400},
        {"request_id": 1, "decision": "approved", "days": "soon"},
    ],
)
def test_invalid_decisions_are_rejected(users: dict[str, User], args: dict[str, object]) -> None:
    with pytest.raises(ActionRejected) as rejected:
        tools.execute("decide_request", args, users["miriam.kessler"])
    assert rejected.value.status_code == 422
