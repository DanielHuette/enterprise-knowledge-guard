"""Die Schnittstelle von aussen.

Wichtigster Punkt: die Identitaet kommt aus einem signierten Token. Wer die
Nutzerkennung im Aufruf aendert, bekommt 401 -- nicht fremde Daten.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def token(username: str) -> str:
    antwort = client.post("/auth/login", json={"username": username})
    assert antwort.status_code == 200
    return antwort.json()["token"]


def kopf(username: str) -> dict:
    return {"Authorization": f"Bearer {token(username)}"}


def test_ohne_token_kein_zugriff():
    assert client.post("/ask", json={"frage": "Gehalt?"}).status_code == 401


def test_gefaelschtes_token_wird_abgewiesen():
    echt = token("tom.schaefer")
    nutzlast, signatur = echt.split(".", 1)
    gefaelscht = f"{nutzlast}.{'0' * len(signatur)}"
    antwort = client.post(
        "/ask", json={"frage": "Gehalt?"},
        headers={"Authorization": f"Bearer {gefaelscht}"},
    )
    assert antwort.status_code == 401


def test_praktikant_bekommt_keine_gehaelter_ueber_die_schnittstelle(markierungen):
    antwort = client.post(
        "/ask",
        json={"frage": "Wie hoch ist das Gehalt eines Senior Entwicklers?"},
        headers=kopf("tom.schaefer"),
    )
    assert antwort.status_code == 200
    daten = antwort.json()
    gesamt = daten["antwort"] + str(daten["quellen"])
    for marker in markierungen["Gehaltsbaender 2026"]:
        assert marker not in gesamt
    assert daten["gesperrte_treffer"] > 0


def test_geschaeftsfuehrung_bekommt_sie(markierungen):
    antwort = client.post(
        "/ask",
        json={"frage": "Wie hoch ist das Gehalt eines Senior Entwicklers?"},
        headers=kopf("sarah.brandt"),
    )
    daten = antwort.json()
    assert "92.000" in daten["antwort"] + str(daten["quellen"])


def test_entscheiden_ohne_leitungsrolle_gibt_403():
    antwort = client.post(
        "/requests/1/decide",
        json={"entscheidung": "approved"},
        headers=kopf("tom.schaefer"),
    )
    assert antwort.status_code == 403


def test_protokoll_zeigt_dem_praktikanten_nur_eigene_zeilen():
    client.post("/ask", json={"frage": "Urlaub?"}, headers=kopf("tom.schaefer"))
    client.post("/ask", json={"frage": "Urlaub?"}, headers=kopf("jonas.weber"))
    zeilen = client.get("/audit", headers=kopf("tom.schaefer")).json()
    assert zeilen
    assert {zeile["username"] for zeile in zeilen} == {"tom.schaefer"}


def test_protokoll_zeigt_der_administration_alles():
    zeilen = client.get("/audit", headers=kopf("sarah.brandt")).json()
    assert len({zeile["username"] for zeile in zeilen}) > 1


def test_werkzeugliste_haengt_an_der_rolle():
    praktikant = set(client.get("/me", headers=kopf("tom.schaefer")).json()["werkzeuge"])
    chefin = set(client.get("/me", headers=kopf("sarah.brandt")).json()["werkzeuge"])
    assert praktikant < chefin
    assert "protokoll_auslesen" not in praktikant
