"""Werkzeuge des Agenten -- jedes an eine Rolle gebunden.

Derselbe Gedanke wie bei den Dokumenten, nur fuer Handlungen: der Praktikant
darf fragen und eine Freigabe beantragen, die Leitung darf entscheiden, die
Administration darf das Protokoll lesen.

Zwei Ebenen, auch hier:
  1. Das Sprachmodell bekommt nur die Werkzeuge ueberhaupt zu sehen, die zur
     Rolle passen. Es kann nichts aufrufen, von dem es nicht weiss.
  2. Vor der Ausfuehrung wird die Rolle erneut geprueft. Selbst ein Modell,
     das einen Namen erfindet oder aus dem Kontext aufschnappt, kommt nicht
     durch.
Und was beide Ebenen passiert, scheitert immer noch an den Zeilen-Rechten in
der Datenbank.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

import psycopg

from . import audit, llm
from .config import settings
from .db import as_user, fetch_all, fetch_one
from .retrieval import search


class ToolDenied(Exception):
    def __init__(self, tool: str, needed: str, have: str):
        self.tool, self.needed, self.have = tool, needed, have
        super().__init__(
            f"Werkzeug '{tool}' erfordert mindestens '{needed}', "
            f"vorhanden ist '{have}'."
        )


_RANKS: dict[str, int] | None = None


def role_ranks() -> dict[str, int]:
    """Raenge kommen aus der Tabelle roles -- nicht aus einer Kopie im Code."""
    global _RANKS
    if _RANKS is None:
        with as_user(None) as conn:
            rows = fetch_all(conn, "SELECT name, rank FROM roles")
        _RANKS = {row["name"]: row["rank"] for row in rows}
    return _RANKS


def rank_of(role: str) -> int:
    return role_ranks().get(role, 0)


@dataclass
class Tool:
    name: str
    min_role: str
    description: str
    parameters: dict
    handler: Callable[[dict, dict], dict]
    sources: bool = field(default=False)

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# ---------------------------------------------------------------------------
# Umsetzungen
# ---------------------------------------------------------------------------
def _wissen_durchsuchen(args: dict, user: dict) -> dict:
    frage = (args.get("frage") or "").strip()
    result = search(user["id"], frage)
    text, mode = llm.answer(frage, result.hits)
    return {
        "antwort": text,
        "betriebsart": mode,
        "gesperrte_treffer": result.blocked_count,
        "quellen": [hit.as_source() for hit in result.hits],
        "_chunk_ids": result.chunk_ids,
        "_blocked": result.blocked_count,
    }


def _zusammenfassen(args: dict, user: dict) -> dict:
    thema = (args.get("thema") or "").strip()
    result = search(user["id"], thema)
    return {
        "zusammenfassung": llm.summarize(result.hits, f"Fasse zusammen: {thema}"),
        "gesperrte_treffer": result.blocked_count,
        "quellen": [hit.as_source() for hit in result.hits],
        "_chunk_ids": result.chunk_ids,
        "_blocked": result.blocked_count,
    }


def _verzeichnis_anzeigen(args: dict, user: dict) -> dict:
    with as_user(user["id"]) as conn:
        rows = fetch_all(
            conn,
            """
            SELECT c.id, c.title, c.department, c.min_required_role,
                   kg_visible(%(uid)s, c.department_id, c.min_required_role, c.id)
                       AS lesbar
              FROM document_catalog c
             ORDER BY c.id
            """,
            {"uid": user["id"]},
        )
    return {
        "dokumente": [
            {
                "id": row["id"],
                "titel": row["title"],
                "abteilung": row["department"] or "firmenweit",
                "ab_rolle": row["min_required_role"],
                "fuer_dich_lesbar": bool(row["lesbar"]),
            }
            for row in rows
        ]
    }


def _freigabe_beantragen(args: dict, user: dict) -> dict:
    document_id = int(args["dokument_id"])
    grund = (args.get("grund") or "").strip() or "kein Grund angegeben"
    with as_user(user["id"]) as conn:
        document = fetch_one(
            conn, "SELECT id, title FROM document_catalog WHERE id = %(id)s",
            {"id": document_id},
        )
        if document is None:
            return {"fehler": f"Dokument {document_id} existiert nicht."}
        row = fetch_one(
            conn,
            """
            INSERT INTO access_requests (requester_id, document_id, reason)
            VALUES (%(uid)s, %(doc)s, %(grund)s)
            RETURNING id
            """,
            {"uid": user["id"], "doc": document_id, "grund": grund},
        )
    return {
        "antrag_id": row["id"],
        "dokument": document["title"],
        "status": "pending",
        "hinweis": "Die Leitung entscheidet. Bis dahin aendert sich nichts am Zugriff.",
    }


def _freigabe_entscheiden(args: dict, user: dict) -> dict:
    antrag_id = int(args["antrag_id"])
    entscheidung = (args.get("entscheidung") or "approved").strip().lower()
    if entscheidung not in ("approved", "denied"):
        return {"fehler": "entscheidung muss 'approved' oder 'denied' sein."}
    tage = int(args.get("tage") or settings.grant_days_default)
    expires = datetime.now(timezone.utc) + timedelta(days=tage)

    with as_user(user["id"]) as conn:
        request = fetch_one(
            conn,
            """
            UPDATE access_requests
               SET status = %(status)s, decided_by = %(uid)s, decided_at = now()
             WHERE id = %(id)s AND status = 'pending'
            RETURNING id, requester_id, document_id
            """,
            {"status": entscheidung, "uid": user["id"], "id": antrag_id},
        )
        if request is None:
            return {"fehler": f"Antrag {antrag_id} ist offen nicht auffindbar."}
        if entscheidung == "denied":
            return {"antrag_id": antrag_id, "status": "denied"}
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO access_grants (user_id, document_id, granted_by,
                                               request_id, expires_at)
                    VALUES (%(uid)s, %(doc)s, %(by)s, %(req)s, %(exp)s)
                    ON CONFLICT (user_id, document_id)
                    DO UPDATE SET expires_at = EXCLUDED.expires_at,
                                  granted_by = EXCLUDED.granted_by,
                                  request_id = EXCLUDED.request_id
                    """,
                    {
                        "uid": request["requester_id"],
                        "doc": request["document_id"],
                        "by": user["id"],
                        "req": antrag_id,
                        "exp": expires,
                    },
                )
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()
            return {"fehler": "Freigabe konnte nicht eingetragen werden."}
    return {
        "antrag_id": antrag_id,
        "status": "approved",
        "gueltig_bis": expires.isoformat(timespec="seconds"),
        "hinweis": "Befristet und nur fuer dieses eine Dokument.",
    }


def _email_entwerfen(args: dict, user: dict) -> dict:
    empfaenger = (args.get("empfaenger") or "").strip() or "Team"
    anlass = (args.get("anlass") or "").strip()
    result = search(user["id"], anlass)
    if llm.provider() == "none":
        korpus = "\n".join(f"- {hit.content.strip()}" for hit in result.hits)
        entwurf = (
            f"Betreff: {anlass}\n\nHallo {empfaenger},\n\n"
            f"zum Thema \"{anlass}\" liegt aus den freigegebenen Unterlagen vor:\n\n"
            f"{korpus or '- keine freigegebenen Unterlagen gefunden'}\n\n"
            f"Viele Gruesse\n{user['username']}"
        )
    else:
        entwurf = llm.complete(
            [
                {
                    "role": "user",
                    "content": f"{llm.build_context(result.hits)}\n\n"
                    f"<auftrag>Entwirf eine kurze, sachliche E-Mail an "
                    f"{empfaenger} zum Thema: {anlass}. Nur Inhalte aus den "
                    f"Quellen. Mit Betreffzeile.</auftrag>",
                }
            ]
        )["text"]
    return {
        "entwurf": entwurf,
        "versendet": False,
        "hinweis": "Entwurf. Das System versendet nichts von sich aus.",
        "quellen": [hit.as_source() for hit in result.hits],
        "_chunk_ids": result.chunk_ids,
        "_blocked": result.blocked_count,
    }


def _protokoll_auslesen(args: dict, user: dict) -> dict:
    anzahl = min(int(args.get("anzahl") or 20), 200)
    rows = audit.read(user["id"], anzahl)
    return {
        "eintraege": [
            {
                "zeit": row["at"].isoformat(timespec="seconds"),
                "nutzer": row["username"],
                "rolle": row["role"],
                "aktion": row["action"],
                "entscheidung": row["decision"],
                "frage": row["question"],
                "freigegebene_abschnitte": row["allowed_chunk_ids"],
                "gesperrte_treffer": row["blocked_count"],
            }
            for row in rows
        ]
    }


# ---------------------------------------------------------------------------
# Verzeichnis der Werkzeuge
# ---------------------------------------------------------------------------
def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


REGISTRY: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            name="wissen_durchsuchen",
            min_role="Intern",
            description="Beantwortet eine Frage aus den fuer den Nutzer "
                        "freigegebenen Firmenunterlagen.",
            parameters=_schema(
                {"frage": {"type": "string", "description": "Die Frage im Klartext."}},
                ["frage"],
            ),
            handler=_wissen_durchsuchen,
            sources=True,
        ),
        Tool(
            name="verzeichnis_anzeigen",
            min_role="Intern",
            description="Listet alle Dokumente mit Abteilung und erforderlicher "
                        "Rolle auf. Zeigt keine Inhalte.",
            parameters=_schema({}, []),
            handler=_verzeichnis_anzeigen,
        ),
        Tool(
            name="freigabe_beantragen",
            min_role="Intern",
            description="Beantragt Leserecht fuer ein einzelnes Dokument. "
                        "Aendert selbst keinen Zugriff.",
            parameters=_schema(
                {
                    "dokument_id": {"type": "integer"},
                    "grund": {"type": "string"},
                },
                ["dokument_id", "grund"],
            ),
            handler=_freigabe_beantragen,
        ),
        Tool(
            name="zusammenfassen",
            min_role="Employee",
            description="Fasst die freigegebenen Unterlagen zu einem Thema zusammen.",
            parameters=_schema({"thema": {"type": "string"}}, ["thema"]),
            handler=_zusammenfassen,
            sources=True,
        ),
        Tool(
            name="email_entwerfen",
            min_role="Employee",
            description="Entwirft eine E-Mail aus den freigegebenen Unterlagen. "
                        "Versendet nichts.",
            parameters=_schema(
                {"empfaenger": {"type": "string"}, "anlass": {"type": "string"}},
                ["empfaenger", "anlass"],
            ),
            handler=_email_entwerfen,
            sources=True,
        ),
        Tool(
            name="freigabe_entscheiden",
            min_role="Manager",
            description="Genehmigt oder lehnt einen Freigabeantrag ab. Bei "
                        "Genehmigung entsteht ein befristetes Leserecht.",
            parameters=_schema(
                {
                    "antrag_id": {"type": "integer"},
                    "entscheidung": {"type": "string", "enum": ["approved", "denied"]},
                    "tage": {"type": "integer"},
                },
                ["antrag_id", "entscheidung"],
            ),
            handler=_freigabe_entscheiden,
        ),
        Tool(
            name="protokoll_auslesen",
            min_role="Admin",
            description="Liest das Zugriffsprotokoll des Systems.",
            parameters=_schema({"anzahl": {"type": "integer"}}, []),
            handler=_protokoll_auslesen,
        ),
    ]
}


def allowed_tools(user: dict) -> list[Tool]:
    """Ebene 1: Was die Rolle nicht darf, bekommt das Modell nicht zu sehen."""
    have = rank_of(user["role"])
    return [tool for tool in REGISTRY.values() if rank_of(tool.min_role) <= have]


def authorize(name: str, user: dict) -> Tool:
    """Ebene 2: Pruefung unmittelbar vor der Ausfuehrung."""
    tool = REGISTRY.get(name)
    if tool is None:
        raise ToolDenied(name, "-", user["role"])
    if rank_of(user["role"]) < rank_of(tool.min_role):
        raise ToolDenied(name, tool.min_role, user["role"])
    return tool


def execute(name: str, args: dict, user: dict) -> dict:
    """Fuehrt ein Werkzeug aus und protokolliert die Entscheidung."""
    try:
        tool = authorize(name, user)
    except ToolDenied as denied:
        audit.record(
            user["id"], f"tool:{name}", "deny",
            detail={"grund": str(denied), "argumente": args},
        )
        raise

    result = tool.handler(args, user)
    audit.record(
        user["id"], f"tool:{name}", "allow",
        question=args.get("frage") or args.get("thema") or args.get("anlass"),
        chunk_ids=result.pop("_chunk_ids", None),
        blocked_count=result.pop("_blocked", 0) or 0,
        detail={"argumente": args},
    )
    return result
