"""HTTP-Schnittstelle."""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import agent, audit, llm, tools
from .auth import AuthError, issue_token, read_token
from .config import settings
from .db import as_owner, as_user, fetch_all, fetch_one
from .retrieval import search
from .seed import seed


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
def _wait_for_db(timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(settings.owner_dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except Exception as exc:  # noqa: BLE001 -- Start, jeder Fehler bedeutet warten
            last = exc
            time.sleep(1.5)
    raise RuntimeError(f"Datenbank nicht erreichbar: {last}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _wait_for_db()
    # Beispieldaten nur fuer die Vorfuehrung. Im Echtbetrieb haette der Dienst
    # keine Eigentuemer-Verbindung -- Einrichtung und Betrieb sind getrennte
    # Aufgaben.
    if os.getenv("SEED_ON_START", "true").strip().lower() in ("1", "true", "yes"):
        seed(force=False)
    yield


app = FastAPI(
    title="Enterprise Knowledge Guard",
    version="1.0.0",
    description="Firmenwissen mit Rechtepruefung in der Datenbank.",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Identitaet
# ---------------------------------------------------------------------------
def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Kein Token")
    try:
        body = read_token(authorization.split(" ", 1)[1].strip())
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc

    # Rolle frisch aus der Datenbank: eine Rollenaenderung wirkt sofort und
    # nicht erst, wenn das Token ablaeuft.
    with as_user(None) as conn:
        user = fetch_one(
            conn,
            "SELECT id, username, display_name, job_title, role FROM users "
            "WHERE id = %(id)s",
            {"id": body["uid"]},
        )
    if user is None:
        raise HTTPException(401, "Nutzer existiert nicht mehr")
    return user


# ---------------------------------------------------------------------------
# Modelle
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str


class AskIn(BaseModel):
    frage: str = Field(min_length=1)


class AgentIn(BaseModel):
    auftrag: str = Field(min_length=1)


class RequestIn(BaseModel):
    dokument_id: int
    grund: str = Field(min_length=1)


class DecideIn(BaseModel):
    entscheidung: str = Field(pattern="^(approved|denied)$")
    tage: int | None = None


# ---------------------------------------------------------------------------
# Endpunkte
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> dict:
    with as_user(None) as conn:
        fetch_one(conn, "SELECT 1 AS ok")
    return {
        "status": "ok",
        "einbettung": settings.resolved_embedding_provider(),
        "sprachmodell": llm.provider(),
    }


@app.get("/demo/users")
def demo_users() -> list[dict]:
    """Nur fuer den Nutzerumschalter der Vorfuehrung. Gibt keine Inhalte."""
    with as_user(None) as conn:
        return fetch_all(
            conn,
            """
            SELECT u.id, u.username, u.display_name, u.job_title, u.role,
                   coalesce(array_agg(d.name) FILTER (WHERE d.name IS NOT NULL),
                            '{}') AS departments
              FROM users u
              LEFT JOIN user_departments ud ON ud.user_id = u.id
              LEFT JOIN departments d ON d.id = ud.department_id
             GROUP BY u.id
             ORDER BY (SELECT rank FROM roles WHERE name = u.role) DESC, u.id
            """,
        )


@app.post("/auth/login")
def login(payload: LoginIn) -> dict:
    with as_user(None) as conn:
        user = fetch_one(
            conn,
            "SELECT id, username, display_name, job_title, role FROM users "
            "WHERE username = %(name)s",
            {"name": payload.username},
        )
    if user is None:
        raise HTTPException(404, "Unbekannter Nutzer")
    return {"token": issue_token(user), "user": user}


@app.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {
        "user": user,
        "werkzeuge": [tool.name for tool in tools.allowed_tools(user)],
    }


@app.post("/ask")
def ask(payload: AskIn, user: dict = Depends(current_user)) -> dict:
    result = search(user["id"], payload.frage)
    text, mode = llm.answer(payload.frage, result.hits)
    audit.record(
        user["id"], "query", "allow",
        question=payload.frage,
        chunk_ids=result.chunk_ids,
        blocked_count=result.blocked_count,
    )
    return {
        "antwort": text,
        "betriebsart": mode,
        "quellen": [hit.as_source() for hit in result.hits],
        "gesperrte_treffer": result.blocked_count,
    }


@app.post("/agent")
def run_agent(payload: AgentIn, user: dict = Depends(current_user)) -> dict:
    return agent.run(payload.auftrag, user)


@app.get("/catalog")
def catalog(user: dict = Depends(current_user)) -> dict:
    return tools.execute("verzeichnis_anzeigen", {}, user)


@app.get("/requests")
def list_requests(user: dict = Depends(current_user)) -> list[dict]:
    with as_user(user["id"]) as conn:
        return fetch_all(
            conn,
            """
            SELECT r.id, r.document_id, c.title, r.reason, r.status,
                   r.created_at, r.decided_at,
                   u.display_name AS requester, u.role AS requester_role
              FROM access_requests r
              JOIN users u ON u.id = r.requester_id
              LEFT JOIN document_catalog c ON c.id = r.document_id
             ORDER BY r.id DESC
            """,
        )


@app.post("/requests")
def create_request(payload: RequestIn, user: dict = Depends(current_user)) -> dict:
    return tools.execute(
        "freigabe_beantragen",
        {"dokument_id": payload.dokument_id, "grund": payload.grund},
        user,
    )


@app.post("/requests/{request_id}/decide")
def decide_request(
    request_id: int, payload: DecideIn, user: dict = Depends(current_user)
) -> dict:
    try:
        return tools.execute(
            "freigabe_entscheiden",
            {
                "antrag_id": request_id,
                "entscheidung": payload.entscheidung,
                "tage": payload.tage or settings.grant_days_default,
            },
            user,
        )
    except tools.ToolDenied as denied:
        raise HTTPException(403, str(denied)) from denied


@app.get("/audit")
def read_audit(limit: int = 50, user: dict = Depends(current_user)) -> list[dict]:
    return audit.read(user["id"], min(limit, 200))


@app.post("/admin/seed")
def reseed(force: bool = False) -> dict:
    """Beispieldaten neu einspielen -- nur fuer die Vorfuehrung."""
    with as_owner() as conn:
        fetch_one(conn, "SELECT 1")
    return seed(force=force)
