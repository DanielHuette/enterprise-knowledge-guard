"""Record a demonstration run of the live API for the project page.

Context: the page should show what the running system does, not describe it. This script
drives the real HTTP API against a seeded PostgreSQL with pgvector, without a language model,
and writes every answer, source and blocked count it gets. | Input: APP_DATABASE_URL,
OWNER_DATABASE_URL, TOKEN_SECRET | Output: web/data/demo_run.json (path set by --output).

Usage:
    python scripts/demo_run.py
    python scripts/demo_run.py --output /tmp/demo_run.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

QUESTIONS = (
    "What is the annual salary of a senior developer?",
    "How much does the managing director earn?",
    "Is there a written warning for personnel number 4711?",
    "Which discount tier applies from 500 licences?",
    "What is the target revenue for Benelux 2027?",
    "Which measurements does the research report show for the HNSW index?",
    "How do I get my company badge on the first day?",
)
USERS = ("sarah.brandt", "miriam.kessler", "jonas.weber", "lena.fischer", "tom.schaefer")
SALARY_DOCUMENT = "Salary Bands 2026"
PERSONNEL_DOCUMENT = "Personnel File Case 4711"
INJECTION_QUESTION = "How much does the managing director earn?"
EXCERPT_CHARS = 220


def _excerpt(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": source["title"],
        "min_required_role": source["min_required_role"],
        "excerpt": source["excerpt"][:EXCERPT_CHARS],
    }


class Session:
    """One logged-in demo user talking to the API."""

    def __init__(self, client: TestClient, username: str) -> None:
        response = client.post("/auth/login", json={"username": username})
        response.raise_for_status()
        body = response.json()
        self.client = client
        self.user = body["user"]
        self.headers = {"Authorization": f"Bearer {body['token']}"}

    def ask(self, question: str) -> dict[str, Any]:
        return self._summarise(question, self.ask_raw(question))

    def ask_raw(self, question: str) -> dict[str, Any]:
        response = self.client.post("/ask", json={"question": question}, headers=self.headers)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    @staticmethod
    def _summarise(question: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "question": question,
            "answer": body["answer"],
            "sources": [_excerpt(source) for source in body["sources"]],
            "blocked_count": body["blocked_count"],
        }

    def call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.request(method, path, json=payload, headers=self.headers)
        return {"status": response.status_code, "body": response.json()}


def matrix(client: TestClient) -> list[dict[str, Any]]:
    """The same questions asked by every demo user, checked against what each may read.

    A leak is a released source whose document the catalog marks as not readable for that
    user; the catalog comes from the same API, so the check uses no knowledge of its own.
    """
    rows = []
    for username in USERS:
        session = Session(client, username)
        documents = session.call("GET", "/catalog")["body"]["documents"]
        readable = sorted(doc["title"] for doc in documents if doc["readable"])
        answers = [session.ask(q) for q in QUESTIONS]
        leaks = sum(
            source["title"] not in readable for answer in answers for source in answer["sources"]
        )
        rows.append(
            {"user": session.user, "readable": readable, "answers": answers, "leaks": leaks}
        )
    return rows


def approval_flow(client: TestClient) -> list[dict[str, Any]]:
    """Tom asks for the salary bands, Miriam approves, the personnel file stays closed."""
    tom, miriam = Session(client, "tom.schaefer"), Session(client, "miriam.kessler")
    catalog = tom.call("GET", "/catalog")["body"]["documents"]
    salary = next(doc for doc in catalog if doc["title"] == SALARY_DOCUMENT)
    steps: list[dict[str, Any]] = [
        {"step": "catalog", "actor": "tom.schaefer", "result": salary},
        {"step": "ask_before", "actor": "tom.schaefer", "result": tom.ask(QUESTIONS[0])},
    ]
    request = tom.call(
        "POST", "/requests", {"document_id": salary["id"], "reason": "Preparing my contract talk"}
    )
    steps.append({"step": "request", "actor": "tom.schaefer", "result": request})
    request_id = request["body"]["request_id"]
    own = tom.call("POST", f"/requests/{request_id}/decide", {"decision": "approved"})
    steps.append({"step": "self_approval", "actor": "tom.schaefer", "result": own})
    granted = miriam.call(
        "POST", f"/requests/{request_id}/decide", {"decision": "approved", "days": 7}
    )
    steps.append({"step": "approval", "actor": "miriam.kessler", "result": granted})
    steps.append({"step": "ask_after", "actor": "tom.schaefer", "result": tom.ask(QUESTIONS[0])})
    steps.append({"step": "still_closed", "actor": "tom.schaefer", "result": tom.ask(QUESTIONS[2])})
    return steps


def injection(client: TestClient) -> dict[str, Any]:
    """An intern's harmless question reaches the planted instruction, but no salary."""
    from knowledge_guard.seed_data import SECRET_MARKERS

    session = Session(client, "tom.schaefer")
    body = session.ask_raw(INJECTION_QUESTION)
    context = " ".join(source["excerpt"] for source in body["sources"]) + body["answer"]
    return {
        **session._summarise(INJECTION_QUESTION, body),
        "instruction_in_context": "ignore all previous instructions" in context,
        "salary_figure_in_answer": any(m in context for m in SECRET_MARKERS[SALARY_DOCUMENT]),
    }


def forged_token(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/ask", json={"question": QUESTIONS[0]}, headers={"Authorization": "Bearer forged.token"}
    )
    return {"status": response.status_code}


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "web" / "data" / "demo_run.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    os.environ.update({"LLM_PROVIDER": "none", "EMBEDDING_PROVIDER": "local"})
    os.environ["SEED_ON_START"] = "true"
    from knowledge_guard.api import app
    from knowledge_guard.seed import seed

    seed(force=True)
    with TestClient(app) as client:
        report = {
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "extractive, no language model",
            "questions": list(QUESTIONS),
            "matrix": matrix(client),
            "injection": injection(client),
            "forged_token": forged_token(client),
            "approval_flow": approval_flow(client),
        }
    seed(force=True)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{arguments.output} written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
