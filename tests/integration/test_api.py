"""The HTTP API from the outside.

Identity comes from a signed token: changing the user id in a call yields 401, never
someone else's data.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from knowledge_guard.api import app

SALARY_QUESTION = {"question": "What is the annual salary of a senior developer?"}


@pytest.fixture(scope="module")
def client(monkeypatch_module: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def monkeypatch_module() -> Iterator[pytest.MonkeyPatch]:
    mp = pytest.MonkeyPatch()
    mp.setenv("SEED_ON_START", "false")
    mp.setenv("DATABASE_WAIT_SECONDS", "5")
    from knowledge_guard.config import get_settings

    get_settings.cache_clear()
    yield mp
    mp.undo()
    get_settings.cache_clear()


def headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok", "embedding": "local", "llm": "none"}


def test_demo_users_list_roles_and_departments(client: TestClient) -> None:
    users = client.get("/demo/users").json()
    assert users[0]["username"] == "sarah.brandt"
    assert users[0]["departments"] == ["Engineering", "HR", "Sales"]


def test_unknown_login_is_404(client: TestClient) -> None:
    assert client.post("/auth/login", json={"username": "mallory"}).status_code == 404


def test_no_token_no_access(client: TestClient) -> None:
    assert client.post("/ask", json=SALARY_QUESTION).status_code == 401


def test_forged_token_is_rejected(client: TestClient) -> None:
    token = headers(client, "tom.schaefer")["Authorization"].split(" ", 1)[1]
    payload, signature = token.split(".", 1)
    forged = {"Authorization": f"Bearer {payload}.{'0' * len(signature)}"}
    assert client.post("/ask", json=SALARY_QUESTION, headers=forged).status_code == 401


def test_intern_gets_no_salaries(client: TestClient, markers: dict[str, list[str]]) -> None:
    response = client.post("/ask", json=SALARY_QUESTION, headers=headers(client, "tom.schaefer"))
    data = response.json()
    released = data["answer"] + str(data["sources"])
    assert response.status_code == 200
    assert data["mode"] == "extractive"
    assert data["blocked_count"] > 0
    for marker in markers["Salary Bands 2026"]:
        assert marker not in released


def test_admin_gets_them(client: TestClient) -> None:
    data = client.post("/ask", json=SALARY_QUESTION, headers=headers(client, "sarah.brandt")).json()
    assert "92,000" in data["answer"] + str(data["sources"])


def test_deciding_without_manager_role_is_403(client: TestClient) -> None:
    response = client.post(
        "/requests/1/decide", json={"decision": "approved"}, headers=headers(client, "tom.schaefer")
    )
    assert response.status_code == 403


def test_request_endpoints_round_trip(client: TestClient) -> None:
    tom, miriam = headers(client, "tom.schaefer"), headers(client, "miriam.kessler")
    catalog = client.get("/catalog", headers=tom).json()["documents"]
    target = next(d for d in catalog if d["title"] == "Personnel File Case 4711")
    created = client.post(
        "/requests", json={"document_id": target["id"], "reason": "case review"}, headers=tom
    ).json()
    pending = client.get("/requests", headers=miriam).json()
    assert created["request_id"] in [item["id"] for item in pending]
    decided = client.post(
        f"/requests/{created['request_id']}/decide",
        json={"decision": "denied"},
        headers=miriam,
    ).json()
    assert decided == {"request_id": created["request_id"], "status": "denied"}


def test_audit_log_is_scoped_by_role(client: TestClient) -> None:
    client.post("/ask", json={"question": "leave?"}, headers=headers(client, "tom.schaefer"))
    client.post("/ask", json={"question": "leave?"}, headers=headers(client, "jonas.weber"))
    own = client.get("/audit", headers=headers(client, "tom.schaefer")).json()
    everything = client.get("/audit", headers=headers(client, "sarah.brandt")).json()
    assert {row["username"] for row in own} == {"tom.schaefer"}
    assert len({row["username"] for row in everything}) > 1


def test_impossible_decision_is_404_and_audited(client: TestClient) -> None:
    tom, miriam = headers(client, "tom.schaefer"), headers(client, "miriam.kessler")
    catalog = client.get("/catalog", headers=tom).json()["documents"]
    sales = next(d for d in catalog if d["title"] == "Sales Strategy 2027")
    created = client.post(
        "/requests", json={"document_id": sales["id"], "reason": "curious"}, headers=tom
    ).json()
    listed = {item["id"]: item for item in client.get("/requests", headers=miriam).json()}
    assert created["request_id"] not in listed
    response = client.post(
        f"/requests/{created['request_id']}/decide", json={"decision": "approved"}, headers=miriam
    )
    assert response.status_code == 404
    audit = client.get("/audit", headers=headers(client, "sarah.brandt")).json()
    assert audit[0]["action"] == "tool:decide_request"
    assert audit[0]["decision"] == "deny"


def test_requests_carry_the_server_side_decision_right(client: TestClient) -> None:
    tom, miriam = headers(client, "tom.schaefer"), headers(client, "miriam.kessler")
    catalog = client.get("/catalog", headers=tom).json()["documents"]
    salaries = next(d for d in catalog if d["title"] == "Salary Bands 2026")
    created = client.post(
        "/requests", json={"document_id": salaries["id"], "reason": "project"}, headers=tom
    ).json()
    as_manager = {item["id"]: item for item in client.get("/requests", headers=miriam).json()}
    as_requester = {item["id"]: item for item in client.get("/requests", headers=tom).json()}
    assert as_manager[created["request_id"]]["can_decide"] is True
    assert as_requester[created["request_id"]]["can_decide"] is False


def test_tool_list_depends_on_role(client: TestClient) -> None:
    intern = set(client.get("/me", headers=headers(client, "tom.schaefer")).json()["tools"])
    admin = set(client.get("/me", headers=headers(client, "sarah.brandt")).json()["tools"])
    assert intern < admin
    assert "read_audit_log" not in intern


def test_agent_endpoint(client: TestClient) -> None:
    data = client.post(
        "/agent", json={"task": "list the catalog"}, headers=headers(client, "jonas.weber")
    ).json()
    assert data["steps"][0] == {"tool": "list_catalog", "decision": "executed", "arguments": {}}


def test_reseed_requires_admin(client: TestClient) -> None:
    assert client.post("/admin/seed", headers=headers(client, "miriam.kessler")).status_code == 403
    assert client.post("/admin/seed").status_code == 401
    response = client.post("/admin/seed", headers=headers(client, "sarah.brandt"))
    assert response.json() == {"status": "already present"}


def test_invalid_payload_is_422(client: TestClient) -> None:
    response = client.post("/ask", json={"question": ""}, headers=headers(client, "tom.schaefer"))
    assert response.status_code == 422
