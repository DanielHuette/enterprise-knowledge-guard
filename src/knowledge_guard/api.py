"""HTTP API.

Context: FastAPI layer over retrieval, agent, access requests and audit log. Identity comes
only from a signed bearer token; the role is re-read from the database on every request so
a role change applies immediately. Domain errors map to 401/403/404/502.
| Input: HTTP requests. | Output: JSON responses as described in the README.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from knowledge_guard import agent, audit, llm, tools
from knowledge_guard.auth import issue_token, read_token
from knowledge_guard.config import get_settings
from knowledge_guard.db import as_user, close_pool, fetch_all, fetch_one, wait_for_database
from knowledge_guard.errors import ActionRejected, AuthError, ToolDenied, UpstreamError
from knowledge_guard.models import User
from knowledge_guard.retrieval import search
from knowledge_guard.seed import seed

logger = logging.getLogger("knowledge_guard")

USER_COLUMNS = "SELECT id, username, display_name, job_title, role FROM users"
USER_LOOKUP_SQL = {
    "id": f"{USER_COLUMNS} WHERE id = %(v)s",
    "username": f"{USER_COLUMNS} WHERE username = %(v)s",
}

DEMO_USERS_SQL = """
SELECT u.id, u.username, u.display_name, u.job_title, u.role,
       coalesce(array_agg(d.name ORDER BY d.name) FILTER (WHERE d.name IS NOT NULL), '{}')
           AS departments
  FROM users u
  LEFT JOIN user_departments ud ON ud.user_id = u.id
  LEFT JOIN departments d ON d.id = ud.department_id
 GROUP BY u.id
 ORDER BY (SELECT rank FROM roles WHERE name = u.role) DESC, u.id
"""

REQUESTS_SQL = """
SELECT r.id, r.document_id, c.title, r.reason, r.status, r.created_at, r.decided_at,
       u.display_name AS requester, u.role AS requester_role,
       (r.status = 'pending'
        AND r.requester_id <> kg_current_user_id()
        AND kg_current_role_rank() >= 30
        AND kg_has_regular_access(kg_current_user_id(), r.document_id)) AS can_decide
  FROM access_requests r
  JOIN users u ON u.id = r.requester_id
  LEFT JOIN document_catalog c ON c.id = r.document_id
 ORDER BY r.id DESC
"""


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if settings.uses_demo_secret:
        logger.warning("TOKEN_SECRET is the demo default; set your own outside the demo")
    wait_for_database(settings.database_wait_seconds)
    if settings.seed_on_start:
        logger.info("Seed: %s", seed())
    yield
    close_pool()


app = FastAPI(
    title="Enterprise Knowledge Guard",
    version="1.1.0",
    description="Company knowledge with access control enforced inside the database.",
    lifespan=lifespan,
)


@app.exception_handler(ToolDenied)
async def _tool_denied(_request: Request, error: ToolDenied) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(error)})


@app.exception_handler(ActionRejected)
async def _action_rejected(_request: Request, error: ActionRejected) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


@app.exception_handler(UpstreamError)
async def _upstream_failed(_request: Request, error: UpstreamError) -> JSONResponse:
    logger.error("Upstream provider failed: %s", error)
    return JSONResponse(status_code=502, content={"detail": "The language model is unavailable."})


def current_user(authorization: Annotated[str, Header()] = "") -> User:
    """Resolve the caller from the bearer token, with the role fresh from the database."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Missing bearer token")
    try:
        claims = read_token(token.strip())
    except AuthError as error:
        raise HTTPException(401, str(error)) from error
    user = _load_user("id", claims.user_id)
    if user is None:
        raise HTTPException(401, "User no longer exists")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def _load_user(column: Literal["id", "username"], value: int | str) -> User | None:
    with as_user(None) as conn:
        row = fetch_one(conn, USER_LOOKUP_SQL[column], {"v": value})
    return User.from_row(row) if row else None


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AgentIn(BaseModel):
    task: str = Field(min_length=1, max_length=2000)


class RequestIn(BaseModel):
    document_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1000)


class DecideIn(BaseModel):
    decision: Literal["approved", "denied"]
    days: int | None = Field(default=None, ge=1, le=365)


class AnswerOut(BaseModel):
    answer: str
    mode: str
    sources: list[dict[str, Any]]
    blocked_count: int


class AgentOut(AnswerOut):
    steps: list[dict[str, Any]]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    with as_user(None) as conn:
        fetch_one(conn, "SELECT 1 AS ok")
    settings = get_settings()
    return {
        "status": "ok",
        "embedding": settings.resolved_embedding_provider(),
        "llm": settings.resolved_llm_provider(),
    }


@app.get("/demo/users")
def demo_users() -> list[dict[str, Any]]:
    """Users for the demo switcher. Returns no document content."""
    with as_user(None) as conn:
        return fetch_all(conn, DEMO_USERS_SQL)


@app.post("/auth/login")
def login(payload: LoginIn) -> dict[str, Any]:
    user = _load_user("username", payload.username)
    if user is None:
        raise HTTPException(404, "Unknown user")
    return {"token": issue_token(user), "user": user.as_dict()}


@app.get("/me")
def me(user: CurrentUser) -> dict[str, Any]:
    return {"user": user.as_dict(), "tools": [tool.name for tool in tools.allowed_tools(user)]}


@app.post("/ask")
def ask(payload: AskIn, user: CurrentUser) -> AnswerOut:
    found = search(user.id, payload.question)
    text, mode = llm.answer(payload.question, found.hits)
    audit.record(
        user.id,
        "query",
        "allow",
        question=payload.question,
        chunk_ids=found.chunk_ids,
        blocked_count=found.blocked_count,
    )
    return AnswerOut(
        answer=text, mode=mode, sources=found.sources, blocked_count=found.blocked_count
    )


@app.post("/agent")
def run_agent(payload: AgentIn, user: CurrentUser) -> AgentOut:
    result = agent.run(payload.task, user)
    return AgentOut(
        answer=result.answer,
        mode=result.mode,
        steps=result.steps,
        sources=result.sources,
        blocked_count=result.blocked_count,
    )


@app.get("/catalog")
def catalog(user: CurrentUser) -> dict[str, Any]:
    return tools.execute("list_catalog", {}, user)


@app.get("/requests")
def list_requests(user: CurrentUser) -> list[dict[str, Any]]:
    with as_user(user.id) as conn:
        return fetch_all(conn, REQUESTS_SQL)


@app.post("/requests")
def create_request(payload: RequestIn, user: CurrentUser) -> dict[str, Any]:
    return tools.execute(
        "request_access", {"document_id": payload.document_id, "reason": payload.reason}, user
    )


@app.post("/requests/{request_id}/decide")
def decide_request(request_id: int, payload: DecideIn, user: CurrentUser) -> dict[str, Any]:
    args: dict[str, Any] = {"request_id": request_id, "decision": payload.decision}
    if payload.days is not None:
        args["days"] = payload.days
    return tools.execute("decide_request", args, user)


@app.get("/audit")
def read_audit(
    user: CurrentUser, limit: Annotated[int, Query(ge=1, le=audit.MAX_READ_LIMIT)] = 50
) -> list[dict[str, Any]]:
    return audit.read(user.id, limit)


@app.post("/admin/seed")
def reseed(user: CurrentUser, force: bool = False) -> dict[str, Any]:
    """Reload the demo data. Admins only, because force wipes every table."""
    if user.role != "Admin":
        raise HTTPException(403, "Admin role required")
    return seed(force=force)
