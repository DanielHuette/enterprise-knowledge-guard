"""Ebene 2: was passiert, wenn der Filter in der Anwendung fehlt?

Diese Tests umgehen die Anwendungslogik komplett und schicken rohes SQL mit
der Verbindung, die der Dienst benutzt. Wenn hier eine gesperrte Zeile
zurueckkommt, ist die Sicherheit nur eine Zeile Python weit entfernt.
"""
from __future__ import annotations

import psycopg
import pytest

from app.db import as_user, fetch_all, fetch_one


def test_anwendungsrolle_ist_nicht_eigentuemerin():
    """Waere sie es, wuerden die Zeilen-Rechte fuer sie nicht gelten."""
    with as_user(None) as conn:
        row = fetch_one(
            conn,
            """
            SELECT current_user AS wer,
                   (SELECT rolsuper OR rolbypassrls FROM pg_roles
                     WHERE rolname = current_user) AS darf_umgehen,
                   pg_get_userbyid(c.relowner) AS eigentuemer
              FROM pg_class c WHERE c.relname = 'document_chunks'
            """,
        )
    assert row["darf_umgehen"] is False
    assert row["eigentuemer"] != row["wer"]


def test_ohne_identitaet_keine_zeile():
    """Keine gesetzte Identitaet bedeutet kein Zugriff -- nicht voller Zugriff."""
    with as_user(None) as conn:
        rows = fetch_all(conn, "SELECT id FROM document_chunks")
    assert rows == []


def test_rohes_sql_umgeht_nichts(nutzer, markierungen):
    """Ohne jeden Sicherheitsfilter im SQL: die Datenbank filtert selbst."""
    with as_user(nutzer["tom.schaefer"]["id"]) as conn:
        rows = fetch_all(conn, "SELECT content FROM document_chunks")
    text = " ".join(row["content"] for row in rows)
    for marker in markierungen["Gehaltsbaender 2026"]:
        assert marker not in text


def test_gezielte_suche_nach_der_geheimzahl(nutzer):
    with as_user(nutzer["tom.schaefer"]["id"]) as conn:
        rows = fetch_all(
            conn,
            "SELECT id FROM document_chunks WHERE content LIKE %(muster)s",
            {"muster": "%92.000%"},
        )
    assert rows == []


def test_zaehlen_verraet_nichts(nutzer):
    """Auch eine Aggregation sieht nur die freigegebenen Zeilen."""
    with as_user(nutzer["tom.schaefer"]["id"]) as conn:
        tom = fetch_one(conn, "SELECT count(*) AS n FROM document_chunks")["n"]
    with as_user(nutzer["sarah.brandt"]["id"]) as conn:
        chefin = fetch_one(conn, "SELECT count(*) AS n FROM document_chunks")["n"]
    assert tom < chefin


def test_titel_bleiben_im_verzeichnis_sichtbar_inhalt_nicht(nutzer):
    """Bewusste Entscheidung: der Praktikant darf wissen, DASS es die
    Gehaltsbaender gibt -- sonst kann er keine Freigabe beantragen."""
    with as_user(nutzer["tom.schaefer"]["id"]) as conn:
        katalog = fetch_all(conn, "SELECT title FROM document_catalog")
        dokumente = fetch_all(conn, "SELECT title FROM documents")
    assert "Gehaltsbaender 2026" in [row["title"] for row in katalog]
    assert "Gehaltsbaender 2026" not in [row["title"] for row in dokumente]


def test_anwendung_darf_einstufungen_nicht_aendern(nutzer):
    """Der naheliegendste Angriff: die Freigabestufe heruntersetzen."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with as_user(nutzer["tom.schaefer"]["id"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET min_required_role = 'Intern' "
                    "WHERE title = 'Gehaltsbaender 2026'"
                )


def test_anwendung_darf_zeilenrechte_nicht_abschalten(nutzer):
    with pytest.raises(psycopg.errors.Error):
        with as_user(nutzer["tom.schaefer"]["id"]) as conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE document_chunks DISABLE ROW LEVEL SECURITY")


def test_identitaet_gilt_nur_fuer_die_transaktion(nutzer):
    """Eine Verbindung aus dem Pool bringt keine fremden Rechte mit."""
    with as_user(nutzer["sarah.brandt"]["id"]) as conn:
        viele = fetch_one(conn, "SELECT count(*) AS n FROM document_chunks")["n"]
    with as_user(None) as conn:
        keine = fetch_one(conn, "SELECT count(*) AS n FROM document_chunks")["n"]
    assert viele > 0 and keine == 0


def test_identitaet_ist_die_einzige_stellschraube(nutzer):
    """Offen dokumentiert: die Datenbank glaubt app.user_id.

    Wer diese Einstellung setzen kann, hat die Rechte des gesetzten Nutzers.
    Setzen kann sie nur, wer die Datenbankverbindung des Dienstes hat -- und
    der Dienst setzt sie ausschliesslich aus einem signierten Token. Damit ist
    klar benannt, wo die Vertrauensgrenze liegt: beim Token, nicht bei einem
    Feld im Aufruf. Der Test haelt dieses Verhalten fest, damit es nicht
    unbemerkt zu etwas anderem wird.
    """
    with as_user(nutzer["tom.schaefer"]["id"]) as conn:
        vorher = fetch_all(
            conn, "SELECT id FROM document_chunks WHERE content LIKE %(m)s",
            {"m": "%92.000%"},
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.user_id', %s, true)",
                (str(nutzer["sarah.brandt"]["id"]),),
            )
        nachher = fetch_all(
            conn, "SELECT id FROM document_chunks WHERE content LIKE %(m)s",
            {"m": "%92.000%"},
        )
    assert vorher == []
    assert len(nachher) > 0
