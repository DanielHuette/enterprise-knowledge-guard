# Bericht über die Überarbeitung

[English version](REFACTORING_REPORT.md)

## Umfang

**Kontext:** Überarbeitung von `enterprise-knowledge-guard` zu einer englischen, typisierten Codebasis auf Produktionsniveau | **Input:** ursprünglicher Dienst (deutsche Bezeichner, Oberfläche, Daten und Tests; 74 Tests) | **Output:** gleiches Sicherheitsmodell, durchgehend englisch, 149 Tests

| Punkt | Vorher | Nachher |
|---|---|---|
| Sprache von Code, Schnittstelle, Oberfläche, Beispieldaten, Projektseite | deutsch | englisch (README zusätzlich deutsch) |
| Paket | `api/app` mit Pfadtricks in den Tests | installierbares `src/knowledge_guard` |
| Tests | 74, nur gegen die Datenbank | 149: 52 Unit-Tests, 97 Integrationstests |
| Zeilenabdeckung | nicht gemessen | 96 % |
| `mypy --strict` | nicht eingesetzt | 0 Fehler |
| Stilprüfung | keine | ruff inklusive Sicherheitsregeln (bandit) |
| Abhängigkeiten | offene Versionsbereiche je Dienst | `uv.lock`, exportierte `requirements*.txt` |
| Automatische Prüfung | keine | Stil, Typen, Unit-Tests, Integrationstests in Docker |

## Sicherheitskorrekturen

**Kontext:** Fehler, die das Rechtemodell schwächten | **Input:** ursprünglicher Code | **Output:** Korrekturen mit Regressionstests

| Befund | Änderung | Nachweis |
|---|---|---|
| `POST /admin/seed?force=true` ging ohne Anmeldung und konnte alle Tabellen leeren | Token und Admin-Rolle erforderlich | `test_reseed_requires_admin` |
| Eine Leitung konnte ihren eigenen Antrag genehmigen | Zeilen-Recht `requests_decide` verbietet die Entscheidung über eigene Anträge | `test_nobody_approves_their_own_request` |
| Eine Leitung konnte sich direkt selbst eine Freigabe eintragen | Zeilen-Recht `grants_insert` verbietet Freigaben an sich selbst | `test_managers_cannot_grant_themselves_access` |
| Eine Leitung konnte Dokumente außerhalb ihrer eigenen Rechte freigeben (HR gibt Vertriebsunterlagen frei) | Neue Funktion `kg_has_regular_access`; Entscheiden und Freigeben setzen eigenes reguläres Leserecht voraus | `test_managers_cannot_hand_out_documents_they_cannot_read` |
| Funktionen mit erweiterten Rechten waren für alle Datenbanknutzer ausführbar | `REVOKE EXECUTE ... FROM PUBLIC`, nur für den Dienst freigegeben | `db/04_grants.sql` |
| Eine Token-Signatur mit Sonderzeichen führte zu HTTP 500 | Signaturen werden als Bytes verglichen | `test_malformed_tokens_are_rejected` |
| Unmögliche Entscheidungen gaben HTTP 200 mit Fehlerfeld zurück und wurden als erlaubt protokolliert | `ActionRejected` → 404/422, protokolliert als `deny`; die Oberfläche zeigt Knöpfe nur, wo der Server eine Entscheidung zulässt | `test_impossible_decision_is_404_and_audited` |
| Der Agent konnte Freigaben mit negativer oder unbegrenzter Dauer anlegen | Tage auf jedem Weg auf 1 bis 365 geprüft | `test_invalid_decisions_are_rejected` |
| Ein beschädigtes Token führte zu HTTP 500 | Lesefehler ergeben 401 | `test_malformed_tokens_are_rejected` |
| Bei pgvector < 0.8 setzte die Ausweichlogik die Transaktion zurück und verlor die Identität | Sicherungspunkt um die optionale Einstellung | `retrieval._enable_iterative_scan` |
| Container liefen als root | Eigener Nutzer ohne Sonderrechte in beiden Images | `Dockerfile`, `ui/Dockerfile` |
| Dokumenttitel gingen ungeschützt in die Prompt-Auszeichnung | Titel werden maskiert | `test_context_marks_documents_as_material_and_escapes_titles` |

## Robustheit

**Kontext:** Verhalten unter Last und bei Fehlern | **Input:** Einzelversuche, pauschale Ausnahmen | **Output:** begrenzte Wiederholversuche, genaue Fehler

| Befund | Änderung | Nachweis |
|---|---|---|
| Modell- und Embedding-Aufrufe ohne Wiederholung | Exponentiell wartende Wiederholversuche bei 429/5xx/Netzfehlern, begrenzt und einstellbar | `tests/unit/test_llm_and_upstream.py` |
| Anbieterfehler endeten als HTTP 500 mit Traceback | `UpstreamError` → HTTP 502 mit klarer Meldung | `api._upstream_failed` |
| Startwartezeit fing jede Ausnahme ab | Wartet nur auf `OperationalError`, mit Frist | `db.wait_for_database` |
| Verbindungspool wurde nie geschlossen | Wird beim Herunterfahren geschlossen | `api.lifespan` |
| Einstellungen beim Import über `os.getenv` | `pydantic-settings`, geprüfte Wertebereiche, Schlüssel als `SecretStr` | `tests/unit/test_auth_and_config.py` |
| Stichwortzuordnung hängte alle Ziffern aneinander („Dokument 4 für 7 Tage" → 47) | Nur die erste Zahl, Wortgrenzen | `test_request_uses_the_first_number_only` |
| Messung löschte ihre Zeilen per Titel | Läuft in einer Transaktion und wird zurückgerollt | `scripts/bench.py` |
| Planprüfung der Messung meldete nach dem breiten Lauf einen sequenziellen Durchlauf | Suchbreite vor der Prüfung zurückgesetzt | Ausgabe der Messung |
| Das Rauschen der Messung war so groß, dass die „Themenhaufen" reine Zufallsvektoren waren | Rauschen an die Dimension angepasst; der gefilterte Lauf erbt die breite Sucheinstellung nicht mehr | Leistungsabschnitt im README |

## Struktur

**Kontext:** Eine Aufgabe je Funktion, Typisierung | **Input:** Module voller loser Dictionaries | **Output:** typisierte Module

| Befund | Änderung | Nachweis |
|---|---|---|
| Nutzer als Dictionary herumgereicht | Datenklassen `User`, `Hit`, `SearchResult` | `models.py` |
| Doppelter HTTP-Code in `llm.py` und `embeddings.py` | Ein gemeinsames `upstream.post_json` | `upstream.py` |
| Agentenschleife mit 100 Zeilen | Aufgeteilt in Zuordnung, Modellschleife, Werkzeugaufruf | `agent.py` |
| Antworten der Schnittstelle untypisiert | Pydantic-Modelle für Anfrage und Antwort | `/docs` |
| Interne Schlüssel `_chunk_ids` in Werkzeugergebnissen | Ergebnis und Suche getrennt zurückgegeben | `tools.Handler` |

## Veröffentlichung

**Kontext:** Die überarbeitete Fassung auf GitHub und auf die Projektseite bringen | **Input:** die lokale Überarbeitung, die deutsche Projektseite | **Output:** CI, ein aufgezeichneter Probelauf, eine zweisprachige Seite

| Befund | Änderung | Nachweis |
|---|---|---|
| Die README zeigt ein CI-Abzeichen, einen Ablauf gab es nicht | `.github/workflows/ci.yml`: pgvector-Dienst, Rollen und Schema wie im Container, ruff, mypy, pytest | CI-Lauf beim ersten Hochladen |
| Die Projektseite beschrieb das System, zeigte aber keinen Lauf | `scripts/demo_run.py` zeichnet fünf Nutzer × sieben Fragen, den Antragsweg, die eingeschleuste Anweisung und ein gefälschtes Token über die echte Schnittstelle auf | `web/data/demo_run.json`, 0 Lecks |
| Die Seite war deutsch und nannte die deutsche Oberfläche der alten Fassung | eine Seite auf Deutsch und Englisch; zitierte Ausgaben, Knopf- und Reiternamen sind die der englischen Oberfläche | Browserdurchgang bei 390 px und 1280 px, beide Sprachen |

## Abschlussprüfung

**Kontext:** Abnahme vor der Veröffentlichung | **Input:** frische Images, frische Datenbank | **Output:** alle Prüfungen bestanden

| Prüfung | Ergebnis |
|---|---|
| `ruff format --check`, `ruff check` (src, tests, scripts, ui) | bestanden |
| `mypy --strict src scripts` | 0 Fehler |
| `pytest` lokal gegen pgvector | 149 bestanden, 96 % Abdeckung, Warnungen gelten als Fehler |
| Bau der Images für Dienst, Tests und Oberfläche | bestanden |
| Gesamter Stapel: Gesundheitsprüfung, Oberfläche erreichbar, 149 Tests im Testcontainer | bestanden |
| Messung im Container | läuft, hinterlässt keine Zeilen |
| Durchgang durch die Oberfläche (Nutzer wechseln, fragen, Verzeichnis) im Browser | wie in der Anleitung beschrieben |
| `scripts/demo_run.py` gegen PostgreSQL 16 mit pgvector 0.8.1 | 35 Antworten, 0 Lecks, Selbstgenehmigung 403, gefälschtes Token 401 |
| `scripts/bench.py` mit 5.015 und 50.015 Abschnitten | Index 28- und 105-mal schneller als die exakte Suche, Trefferquote 100 % und 96 % bei ef_search 40 |
| Suche nach Schlüsseln, lokalen Pfaden, deutschen Resten, TODO, Debug-Ausgaben | nichts gefunden |
| Unabhängige Sicherheits- und Codeprüfung | 10 Befunde, alle mit Regressionstests behoben |
