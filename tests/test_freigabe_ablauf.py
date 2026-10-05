"""Der Ablauf, der alles verbindet: beantragen, entscheiden, auslaufen.

Eine genehmigte Freigabe ist nicht "der Praktikant ist jetzt Manager". Sie
gilt fuer genau ein Dokument, befristet, mit Namen des Entscheiders.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import tools
from app.db import as_owner
from app.retrieval import search


def sichtbare_titel(user_id: int, frage: str) -> list[str]:
    return [hit.title for hit in search(user_id, frage, 10).hits]


FRAGE = "Gehaltsband Senior Entwicklung Jahresgehalt"


def test_vollstaendiger_ablauf(nutzer, dokumente, markierungen):
    tom = nutzer["tom.schaefer"]
    miriam = nutzer["miriam.kessler"]
    dokument = dokumente["Gehaltsbaender 2026"]

    # 1. Vorher: nichts zu sehen.
    assert "Gehaltsbaender 2026" not in sichtbare_titel(tom["id"], FRAGE)

    # 2. Antrag stellen darf der Praktikant selbst.
    antrag = tools.execute(
        "freigabe_beantragen",
        {"dokument_id": dokument["id"], "grund": "Aufgabe im Personalprojekt"},
        tom,
    )
    assert antrag["status"] == "pending"

    # 3. Der Antrag allein aendert nichts.
    assert "Gehaltsbaender 2026" not in sichtbare_titel(tom["id"], FRAGE)

    # 4. Der Praktikant kann seinen eigenen Antrag nicht genehmigen.
    with pytest.raises(tools.ToolDenied):
        tools.execute(
            "freigabe_entscheiden",
            {"antrag_id": antrag["antrag_id"], "entscheidung": "approved"},
            tom,
        )
    assert "Gehaltsbaender 2026" not in sichtbare_titel(tom["id"], FRAGE)

    # 5. Die Leitung genehmigt -- befristet.
    entscheidung = tools.execute(
        "freigabe_entscheiden",
        {"antrag_id": antrag["antrag_id"], "entscheidung": "approved", "tage": 7},
        miriam,
    )
    assert entscheidung["status"] == "approved"

    # 6. Jetzt ist genau dieses eine Dokument lesbar.
    titel = sichtbare_titel(tom["id"], FRAGE)
    assert "Gehaltsbaender 2026" in titel

    # 7. Aber nur dieses -- die Personalakte bleibt zu.
    alle = " ".join(
        hit.content
        for hit in search(tom["id"], "Abmahnung Personalnummer 4711", 10).hits
    )
    for marker in markierungen["Personalakte Vorgang 4711"]:
        assert marker not in alle

    # 8. Nach Ablauf ist es wieder zu. Hier vorgezogen, damit der Test nicht
    #    sieben Tage wartet.
    with as_owner() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE access_grants SET expires_at = %(gestern)s "
                "WHERE user_id = %(uid)s AND document_id = %(doc)s",
                {
                    "gestern": datetime.now(timezone.utc) - timedelta(days=1),
                    "uid": tom["id"],
                    "doc": dokument["id"],
                },
            )
    assert "Gehaltsbaender 2026" not in sichtbare_titel(tom["id"], FRAGE)


def test_antrag_fuer_fremde_ist_nicht_moeglich(nutzer, dokumente):
    """Die Pruefung liegt in den Zeilen-Rechten: requester_id muss der
    aufrufende Nutzer sein."""
    import psycopg

    from app.db import as_user

    with pytest.raises(psycopg.errors.Error):
        with as_user(nutzer["tom.schaefer"]["id"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO access_requests (requester_id, document_id, reason) "
                    "VALUES (%(fremd)s, %(doc)s, 'im Namen eines anderen')",
                    {
                        "fremd": nutzer["jonas.weber"]["id"],
                        "doc": dokumente["Gehaltsbaender 2026"]["id"],
                    },
                )
