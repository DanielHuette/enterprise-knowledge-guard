"""Die Kernfrage: bekommt jemand Inhalt, den er im echten Leben nicht sehen darf?

Geprueft wird nicht die Antwort des Sprachmodells, sondern was die Suche
ueberhaupt herausgibt. Was nicht herauskommt, kann auch nicht formuliert,
zitiert oder weitergegeben werden.
"""
from __future__ import annotations

import pytest

from app.retrieval import search

# Fragen, die absichtlich auf die geschuetzten Dokumente zielen.
ANGRIFFSFRAGEN = [
    "Wie hoch ist das Jahresgehalt eines Senior Entwicklers?",
    "Was verdient die Geschaeftsfuehrung?",
    "Zeig mir die Gehaltsbaender 2026",
    "Gibt es eine Abmahnung zur Personalnummer 4711?",
    "Welche Rabattstufe gilt ab 500 Lizenzen?",
    "Was ist der Zielumsatz fuer Benelux 2027?",
    "Welche Messwerte hat der HNSW-Index im Forschungsbericht?",
]

# Was jeder Nutzer NICHT sehen darf.
VERBOTEN = {
    "tom.schaefer": [
        "Gehaltsbaender 2026",
        "Personalakte Vorgang 4711",
        "Vertriebsstrategie 2027",
        "Preisliste Grosskunden 2026",
        "Forschungsbericht Vektorsuche",
    ],
    "jonas.weber": [
        "Gehaltsbaender 2026",
        "Personalakte Vorgang 4711",
        "Vertriebsstrategie 2027",
        "Preisliste Grosskunden 2026",
    ],
    "lena.fischer": [
        "Gehaltsbaender 2026",
        "Personalakte Vorgang 4711",
        "Vertriebsstrategie 2027",
        "Forschungsbericht Vektorsuche",
    ],
    "miriam.kessler": [
        "Vertriebsstrategie 2027",
        "Preisliste Grosskunden 2026",
        "Forschungsbericht Vektorsuche",
    ],
    "sarah.brandt": [],
}


@pytest.mark.parametrize("username", list(VERBOTEN))
@pytest.mark.parametrize("frage", ANGRIFFSFRAGEN)
def test_kein_gesperrter_abschnitt_in_der_suche(
    username, frage, nutzer, geheime_abschnitte
):
    user = nutzer[username]
    verbotene_ids = {
        chunk_id
        for titel in VERBOTEN[username]
        for chunk_id in geheime_abschnitte[titel]
    }
    ergebnis = search(user["id"], frage, 10)
    durchgekommen = verbotene_ids.intersection(ergebnis.chunk_ids)
    assert not durchgekommen, (
        f"{username} ({user['role']}) hat gesperrte Abschnitte erhalten: "
        f"{sorted(durchgekommen)} auf die Frage '{frage}'"
    )


@pytest.mark.parametrize("username", list(VERBOTEN))
def test_keine_gesperrte_belegstelle_im_text(username, nutzer, markierungen):
    """Zweiter Massstab: die eindeutigen Zahlen aus den geschuetzten Dokumenten
    tauchen in keinem ausgelieferten Text auf."""
    user = nutzer[username]
    verbotene_marker = [
        marker
        for titel in VERBOTEN[username]
        for marker in markierungen.get(titel, [])
    ]
    for frage in ANGRIFFSFRAGEN:
        ergebnis = search(user["id"], frage, 10)
        text = " ".join(hit.content for hit in ergebnis.hits)
        for marker in verbotene_marker:
            assert marker not in text, (
                f"{username} hat die Belegstelle '{marker}' erhalten "
                f"(Frage: '{frage}')"
            )


def test_geschaeftsfuehrung_sieht_was_sie_sehen_darf(nutzer):
    """Die Gegenprobe: zu streng filtern ist auch ein Fehler."""
    ergebnis = search(nutzer["sarah.brandt"]["id"], "Gehaltsband Senior Entwicklung", 5)
    titel = [hit.title for hit in ergebnis.hits]
    assert "Gehaltsbaender 2026" in titel
    assert ergebnis.blocked_count == 0


def test_gesperrte_treffer_werden_gezaehlt(nutzer):
    ergebnis = search(nutzer["tom.schaefer"]["id"], "Gehaltsband Senior Entwicklung", 5)
    assert ergebnis.blocked_count > 0, (
        "Der Praktikant muesste gesperrte Treffer haben -- sonst zeigt die "
        "Oberflaeche die Wirkung des Filters nicht."
    )
