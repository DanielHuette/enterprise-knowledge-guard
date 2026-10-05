"""Rechte fuer Handlungen, nicht nur fuer Dokumente.

Hier wird geprueft, was den Unterschied zwischen einer Suche und einem Agenten
macht: der Agent handelt. Jedes Werkzeug ist an eine Rolle gebunden, und zwar
zweifach -- das Modell sieht nur erlaubte Werkzeuge, und vor der Ausfuehrung
wird erneut geprueft.
"""
from __future__ import annotations

import pytest

from app import tools
from app.db import as_user, fetch_all


def werkzeugnamen(user: dict) -> set[str]:
    return {tool.name for tool in tools.allowed_tools(user)}


def test_praktikant_sieht_nur_lesende_werkzeuge(nutzer):
    namen = werkzeugnamen(nutzer["tom.schaefer"])
    assert "wissen_durchsuchen" in namen
    assert "freigabe_beantragen" in namen
    assert "freigabe_entscheiden" not in namen
    assert "protokoll_auslesen" not in namen


def test_leitung_darf_entscheiden_aber_kein_protokoll(nutzer):
    namen = werkzeugnamen(nutzer["miriam.kessler"])
    assert "freigabe_entscheiden" in namen
    assert "protokoll_auslesen" not in namen


def test_administration_sieht_alles(nutzer):
    assert werkzeugnamen(nutzer["sarah.brandt"]) == set(tools.REGISTRY)


def test_aufruf_eines_gesperrten_werkzeugs_scheitert(nutzer):
    with pytest.raises(tools.ToolDenied):
        tools.execute(
            "freigabe_entscheiden",
            {"antrag_id": 1, "entscheidung": "approved"},
            nutzer["tom.schaefer"],
        )


def test_erfundener_werkzeugname_scheitert(nutzer):
    with pytest.raises(tools.ToolDenied):
        tools.execute("alles_freigeben", {}, nutzer["tom.schaefer"])


def test_abgelehnter_aufruf_steht_im_protokoll(nutzer):
    user = nutzer["tom.schaefer"]
    with pytest.raises(tools.ToolDenied):
        tools.execute("protokoll_auslesen", {}, user)
    with as_user(user["id"]) as conn:
        rows = fetch_all(
            conn,
            """
            SELECT action, decision FROM audit_log
             WHERE user_id = %(uid)s AND decision = 'deny'
             ORDER BY id DESC LIMIT 5
            """,
            {"uid": user["id"]},
        )
    assert any(row["action"] == "tool:protokoll_auslesen" for row in rows)


def test_entwurf_wird_nicht_versendet(nutzer):
    ergebnis = tools.execute(
        "email_entwerfen",
        {"empfaenger": "Team", "anlass": "Urlaubsregelung"},
        nutzer["jonas.weber"],
    )
    assert ergebnis["versendet"] is False
    assert ergebnis["entwurf"]


def test_verzeichnis_zeigt_lesbarkeit_aber_keinen_inhalt(nutzer):
    ergebnis = tools.execute("verzeichnis_anzeigen", {}, nutzer["tom.schaefer"])
    eintrag = next(
        item for item in ergebnis["dokumente"] if item["titel"] == "Gehaltsbaender 2026"
    )
    assert eintrag["fuer_dich_lesbar"] is False
    assert "inhalt" not in eintrag
