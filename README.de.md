# Enterprise Knowledge Guard

[English version](README.md) · [Projektseite mit Betriebsanleitung](https://enterpriseknowledge.speedofthespirit.dev)

[![CI](https://github.com/DanielHuette/enterprise-knowledge-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/DanielHuette/enterprise-knowledge-guard/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Lizenz: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Ein internes Frage-und-Antwort-System auf Firmenunterlagen, bei dem die Zugriffsrechte
**in der Datenbank** liegen und nicht im Prompt.

Der Praktikant und die Geschäftsführung stellen dieselbe Frage und bekommen
unterschiedliche Antworten, weil die Gehaltsdaten den Praktikanten nie erreichen. Nicht
gefiltert, nicht weggelassen, nicht höflich verweigert: Sie verlassen die Datenbank nicht.

Dazu kommt ein Agent, der handeln darf (Freigaben beantragen, entscheiden, E-Mails
entwerfen), und zwar nur mit den Werkzeugen seiner Rolle.

```
docker compose up --build        →  http://localhost:8501   (Schnittstelle: http://localhost:8000/docs)
docker compose run --rm tests    →  die Testreihe
```

Ein Schlüssel für ein Sprachmodell ist nicht nötig. Ohne ihn antwortet das System
belegbasiert und gibt die freigegebenen Textstellen im Original zurück. Die Rechteprüfung
ist davon völlig unabhängig, genau darum geht es.

Die Oberfläche und die Beispieldaten sind englisch.

## Die Nutzer der Vorführung

| Nutzer | Rolle | Abteilung | sieht zum Beispiel |
|---|---|---|---|
| Sarah Brandt | Admin | alle | alles, auch Gehälter und Vertriebsstrategie |
| Miriam Kessler | Manager | HR | Gehaltsbänder, Personalakten, keine Vertriebsdaten |
| Jonas Weber | Employee | Engineering | Forschungsbericht, Einarbeitung |
| Lena Fischer | Employee | Sales | Preisliste Großkunden |
| Tom Schaefer | Intern | Engineering | nur firmenweit Offenes und Einarbeitung |

Frage zum Umschalten: **„What is the annual salary of a senior developer?"** Sarah bekommt
EUR 92,000. Tom bekommt die Mitteilung, dass relevantere Treffer für seine Rolle gesperrt
sind, ohne Titel, ohne Inhalt, ohne Umweg.

## Die Kernabfrage

Eine Abfrage misst Ähnlichkeit und prüft den Zugriff gleichzeitig. Es gibt keinen
Zwischenschritt, in dem gesperrter Inhalt im Arbeitsspeicher der Anwendung liegt.

```sql
SELECT c.id, c.document_id, d.title, c.content,
       (c.embedding <=> $query::vector) AS distance
  FROM document_chunks c
  JOIN documents d ON d.id = c.document_id
 WHERE kg_visible($user_id, c.department_id, c.min_required_role, c.document_id)
   AND c.embedding IS NOT NULL
 ORDER BY c.embedding <=> $query::vector
 LIMIT $k;
```

`kg_visible` ist die eine Wahrheit darüber, wer was sehen darf: richtige Abteilung (oder
firmenweit) und Rang hoch genug, oder eine befristete Einzelfreigabe. Die Rangfolge der
Rollen steht in einer Tabelle, nicht im Code. Eine neue Stufe ist ein `INSERT`, kein
Deployment.

## Zwei Ebenen, absichtlich doppelt

**Ebene 1** ist die Zeile `WHERE kg_visible(...)` oben. **Ebene 2** ist dieselbe Prüfung als
Zeilen-Recht (Row Level Security) in PostgreSQL. Fällt Ebene 1 durch einen
Programmierfehler weg, liefert die Datenbank trotzdem keine gesperrte Zeile aus. Das ist
der Unterschied zwischen „wir filtern" und „es ist nicht erreichbar".

Dafür gibt es zwei Datenbankrollen:

| Rolle | Aufgabe | Zeilen-Rechte |
|---|---|---|
| `kg_owner` | Einrichtung, Beispieldaten | Eigentümerin, nicht betroffen |
| `kg_app` | der laufende Dienst | `NOBYPASSRLS`, kein Eigentum, voll betroffen |

Der Dienst hat kein `DELETE` auf Dokumenten oder Protokoll, kein `UPDATE` auf dem Protokoll
und kein Recht, Einstufungen zu ändern. Was er nicht darf, kann auch ein Fehler in ihm
nicht anrichten, und Tests belegen das.

Die Identität der laufenden Anfrage wird je Transaktion gesetzt und stammt aus einem
signierten Token, nie aus einem Feld, das der Aufrufer frei setzen kann. Eine Verbindung
aus dem Pool bringt deshalb nie die Rechte eines vorherigen Nutzers mit, und die Rolle wird
bei jeder Anfrage frisch aus der Datenbank gelesen.

## Der Agent: Rechte für Handlungen

| Werkzeug | ab Rolle | tut |
|---|---|---|
| `search_knowledge` | Intern | beantwortet eine Frage aus freigegebenen Unterlagen |
| `list_catalog` | Intern | listet Titel und Einstufung, keine Inhalte |
| `request_access` | Intern | stellt einen Antrag, ändert selbst keinen Zugriff |
| `summarize` | Employee | fasst freigegebene Unterlagen zusammen |
| `draft_email` | Employee | entwirft, versendet nichts |
| `decide_request` | Manager | genehmigt oder lehnt ab, nur für Dokumente, die die Leitung selbst lesen darf, nie den eigenen Antrag |
| `read_audit_log` | Admin | liest das Zugriffsprotokoll |

Auch hier zwei Ebenen: Das Sprachmodell bekommt **nur die erlaubten Werkzeuge überhaupt zu
sehen**, und vor der Ausführung wird die Rolle erneut geprüft. Ein erfundener oder
aufgeschnappter Werkzeugname kommt nicht durch, und was beide Ebenen passiert, scheitert
an den Zeilen-Rechten.

### Der Ablauf, der alles verbindet

1. Tom sieht im Verzeichnis, **dass** es „Salary Bands 2026" gibt, lesen kann er es nicht.
2. Tom beantragt Zugriff mit Begründung. Am Zugriff ändert das nichts.
3. Tom kann seinen eigenen Antrag nicht genehmigen. Eine Leitung kann weder den eigenen
   Antrag genehmigen noch sich selbst Zugriff erteilen noch Dokumente freigeben, die sie
   selbst nicht lesen darf: Die Datenbank lässt alle drei nicht zu.
4. Miriam genehmigt für 7 Tage.
5. Tom liest **genau dieses eine Dokument**, die Personalakte bleibt zu.
6. Nach Ablauf ist es wieder zu, ohne dass jemand aufräumen muss.

## Der Angriff steckt im Dokument

Im firmenweit offenen Dokument „Onboarding FAQ" steht ein Absatz, der das KI-System
anweist, sämtliche Gehälter auszugeben. Er funktioniert nicht, weil die Gehaltsdaten nie in
den Kontext des Modells gelangen. Ein Angreifer kann dem Modell nicht befehlen, etwas
herauszugeben, was es nie bekommen hat. Die `<source>`-Klammern im Prompt sind die zweite
Verteidigungslinie, nicht die erste.

## Zugriffsprotokoll

Jede Frage und jeder Werkzeugaufruf wird festgehalten: Nutzer, Rolle, Entscheidung,
freigegebene Abschnitte und die Zahl gesperrter Treffer. **Gesperrter Inhalt wird nicht
protokolliert.** Wer das Protokoll sehen darf, entscheiden wieder die Zeilen-Rechte.

## Testreihe

```
docker compose run --rm tests                     # 149 Tests im Container
uv run pytest tests/unit                          # 52 Unit-Tests ohne Datenbank
```

Die Integrationstests laufen absichtlich gegen eine echte PostgreSQL-Datenbank mit
pgvector: Die Rechtelogik liegt in der Datenbank, also muss sie dort geprüft werden.

| Datei | hält fest |
|---|---|
| `integration/test_access_rights.py` | sieben Angriffsfragen × fünf Nutzer: keine gesperrte Textstelle kommt durch, und Berechtigte bekommen ihre Daten |
| `integration/test_row_level_security.py` | rohes SQL ohne Filter der Anwendung liefert nichts; Umstufen, Abschalten der Zeilen-Rechte und Löschen im Protokoll scheitern |
| `integration/test_prompt_injection.py` | der Angriffsabsatz landet nachweislich im Kontext und bleibt wirkungslos |
| `integration/test_tools.py` | Werkzeugliste je Rolle, abgelehnte Aufrufe, erfundene Namen, Protokolleintrag |
| `integration/test_approval_flow.py` | der komplette Antragsweg mit Ablauf, Ablehnung, Selbstgenehmigung und Freigaben außerhalb der eigenen Rechte |
| `integration/test_api.py` | gefälschtes Token → 401, fremde Entscheidung → 403, Protokoll je Rolle, Neuladen nur für Admin |
| `unit/` | Token, Anbieterwahl, Wiederholversuche, Nachrichtenformate, Agent |

## Aufgezeichneter Probelauf

```
python scripts/demo_run.py        # braucht die Datenbank, schreibt web/data/demo_run.json
```

Das Skript bedient die echte HTTP-Schnittstelle gegen die befüllte Datenbank, ohne
Sprachmodell: Alle fünf Nutzer stellen dieselben sieben Fragen, Tom beantragt die
Gehaltsbänder, versucht seinen Antrag selbst zu genehmigen, Miriam genehmigt, und nach der
eingeschleusten Anweisung wird gefragt. Jede Antwort, Quelle und Zahl gesperrter Treffer
landet in `web/data/demo_run.json` und steht auf der
[Projektseite](https://enterpriseknowledge.speedofthespirit.dev/#probelauf). Als Leck zählt
jede freigegebene Quelle, deren Dokument das Verzeichnis derselben Schnittstelle für diesen
Nutzer als nicht lesbar führt; der aufgezeichnete Lauf hat keines.

## Leistung

```
docker compose run --rm tests python scripts/bench.py
```

Die Messung vergleicht exakte Suche, HNSW-Index mit zwei Einstellungen von `ef_search`
und Index mit Rechtefilter. Sie rollt ihre Messzeilen zurück und verändert die Datenbank
nicht. Beispielwerte und die beiden behandelten Messfallen (zwischengespeicherte
Ausführungspläne, Nachfiltern) stehen in der [englischen Fassung](README.md#performance).

## Entscheidungen

- **Kein ORM**: Sicherheitsfilter und Vektorvergleich bleiben im Klartext prüfbar.
- **Kein LangChain, kein Software Development Kit**: Werkzeugverzeichnis, Rechteprüfung und
  Schleife; Anthropic und OpenAI direkt über HTTP mit Zeitlimit und Wiederholversuchen.
- **Einstufung doppelt gespeichert**: Der Sicherheitsfilter braucht keinen `JOIN`, zwei Trigger
  halten die Kopie korrekt.
- **Eine Funktion mit erweiterten Rechten**: `kg_blocked_count` gibt nur eine Zahl zurück,
  abschaltbar über `SHOW_BLOCKED_COUNT=false`.
- **Ohne Schlüssel lauffähig**: eingebauter Textvergleich mit 1.536 Werten, derselben
  Dimension wie `text-embedding-3-small`.

## Grenzen

- Anmeldung ohne Passwort, für die Vorführung gewollt.
- Der Dienst kennt die Eigentümer-Verbindung, weil er beim Start die Beispieldaten lädt.
- Dokumente kommen aus einer Datei, nicht aus einem Upload.
- Kein Nachsortieren der Treffer, keine Mandantentrennung.

## Aufbau

Siehe [englische Fassung](README.md#layout). Technik: PostgreSQL 16 mit pgvector, FastAPI,
psycopg 3, Streamlit, Docker Compose. Einstellungen über `.env`, Vorlage in `.env.example`.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
