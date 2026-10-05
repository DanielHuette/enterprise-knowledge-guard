# Enterprise Knowledge Guard

Ein internes Frage-und-Antwort-System auf Firmenunterlagen, bei dem die
Zugriffsrechte **in der Datenbank** liegen und nicht im Prompt.

Der Praktikant und die Geschäftsführung stellen dieselbe Frage und bekommen
unterschiedliche Antworten — weil die Gehaltsdaten den Praktikanten nie
erreichen. Nicht gefiltert, nicht weggelassen, nicht höflich verweigert:
sie verlassen die Datenbank nicht.

Dazu ein Agent, der handeln darf — Freigaben beantragen, entscheiden,
E-Mails entwerfen — und zwar nur mit den Werkzeugen seiner Rolle.

```
docker compose up --build        →  http://localhost:8501
docker compose run --rm tests    →  die Testreihe
```

Kein Zugang zu einem Sprachmodell nötig. Fehlt der Schlüssel, antwortet das
System belegbasiert: es gibt die freigegebenen Textstellen im Original
zurück. Die Rechteprüfung ist davon völlig unberührt — das ist der Punkt.

---

## Die fünf Nutzer der Vorführung

| Nutzer | Rolle | Abteilung | sieht zum Beispiel |
|---|---|---|---|
| Sarah Brandt | Admin | alle | alles, auch Gehälter und Vertriebsstrategie |
| Miriam Kessler | Manager | HR | Gehaltsbänder, Personalakten — keine Vertriebsdaten |
| Jonas Weber | Employee | Engineering | Forschungsberichte, Einarbeitung |
| Lena Fischer | Employee | Sales | Preisliste Großkunden |
| Tom Schäfer | Intern | Engineering | nur firmenweit Offenes und Einarbeitung |

Frage zum Umschalten: **„Wie hoch ist das Jahresgehalt eines Senior
Entwicklers?"** Sarah bekommt 92.000 EUR. Tom bekommt die Mitteilung, dass
drei relevantere Treffer für seine Rolle gesperrt sind — ohne Titel, ohne
Inhalt, ohne Umweg.

---

## Die Kernabfrage

Eine Abfrage macht beides gleichzeitig: Ähnlichkeit messen und Zugriff prüfen.
Es gibt keinen Zwischenschritt, in dem gesperrter Inhalt im Arbeitsspeicher der
Anwendung liegt.

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

`kg_visible` ist die eine Wahrheit darüber, wer was sehen darf:

```sql
CREATE FUNCTION kg_visible(p_user_id INT, p_department_id INT,
                           p_min_role VARCHAR, p_document_id INT)
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
    SELECT p_user_id IS NOT NULL AND (
        EXISTS (                              -- reguläre Freigabe
            SELECT 1 FROM users u
             WHERE u.id = p_user_id
               AND (p_department_id IS NULL                -- firmenweit offen
                    OR p_department_id IN (SELECT department_id
                                             FROM user_departments
                                            WHERE user_id = p_user_id))
               AND kg_role_rank(u.role) >= kg_role_rank(p_min_role))
        OR EXISTS (                           -- befristete Einzelfreigabe
            SELECT 1 FROM access_grants g
             WHERE g.user_id = p_user_id AND g.document_id = p_document_id
               AND g.expires_at > now()))
$$;
```

Die Rangfolge der Rollen steht in einer Tabelle, nicht in einem `CASE` im
Code. Eine neue Stufe einzuführen ist ein `INSERT` — kein Deployment.

---

## Zwei Ebenen, absichtlich doppelt

**Ebene 1** ist die Zeile `WHERE kg_visible(...)` oben.

**Ebene 2** ist dieselbe Prüfung als Zeilen-Recht (Row Level Security) in
PostgreSQL:

```sql
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY chunks_read ON document_chunks FOR SELECT
    USING (kg_visible(kg_current_user_id(), department_id,
                      min_required_role, document_id));
```

Fällt Ebene 1 durch einen Programmierfehler weg, liefert die Datenbank
trotzdem keine gesperrte Zeile aus. Das ist der Unterschied zwischen
„wir filtern" und „es ist nicht erreichbar".

Damit das greift, gibt es **zwei Datenbankrollen**:

| Rolle | Aufgabe | Zeilen-Rechte |
|---|---|---|
| `kg_owner` | Einrichtung, Beispieldaten | Eigentümerin — nicht betroffen |
| `kg_app` | der laufende Dienst | `NOBYPASSRLS`, kein Eigentum → voll betroffen |

Die Anwendung hat kein `DELETE` auf Dokumenten, kein `UPDATE` auf dem
Protokoll und kein Recht, Einstufungen zu ändern. Was sie nicht darf, kann
auch ein Fehler in ihr nicht anrichten — dafür gibt es Tests.

Die Identität der laufenden Anfrage wird je Transaktion gesetzt:

```sql
SELECT set_config('app.user_id', $1, true);   -- true = nur diese Transaktion
```

Sie stammt aus einem signierten Token, nicht aus einem Feld, das der Aufrufer
frei setzen kann. Eine Verbindung aus dem Pool bringt deshalb nie die Rechte
eines vorherigen Nutzers mit.

---

## Der Agent: Rechte für Handlungen

Dieselbe Idee, nur für Tätigkeiten statt Dokumente.

| Werkzeug | ab Rolle | tut |
|---|---|---|
| `wissen_durchsuchen` | Intern | beantwortet eine Frage aus freigegebenen Unterlagen |
| `verzeichnis_anzeigen` | Intern | listet Titel und Einstufung, keine Inhalte |
| `freigabe_beantragen` | Intern | stellt einen Antrag, ändert selbst keinen Zugriff |
| `zusammenfassen` | Employee | fasst freigegebene Unterlagen zusammen |
| `email_entwerfen` | Employee | entwirft, versendet nichts |
| `freigabe_entscheiden` | Manager | genehmigt oder lehnt ab |
| `protokoll_auslesen` | Admin | liest das Zugriffsprotokoll |

Auch hier zwei Ebenen: das Sprachmodell bekommt **nur die erlaubten Werkzeuge
überhaupt zu sehen**, und vor der Ausführung wird die Rolle erneut geprüft.
Ein Modell, das sich einen Werkzeugnamen ausdenkt oder aus dem Kontext
aufschnappt, kommt nicht durch — und was beide Ebenen passiert, scheitert
immer noch an den Zeilen-Rechten.

### Der Ablauf, der alles verbindet

1. Tom sieht im Verzeichnis, **dass** es „Gehaltsbänder 2026" gibt — lesen kann er es nicht.
2. Tom beantragt Zugriff mit Begründung. Am Zugriff ändert das nichts.
3. Tom kann seinen eigenen Antrag nicht genehmigen. Die Datenbank lässt es nicht zu.
4. Miriam genehmigt für 7 Tage.
5. Tom liest **genau dieses eine Dokument** — die Personalakte bleibt zu.
6. Nach Ablauf ist es wieder zu, ohne dass jemand aufräumen muss.

Eine genehmigte Freigabe heißt nicht „Tom ist jetzt Manager".

---

## Der Angriff steckt im Dokument

Im firmenweit offenen Dokument „Onboarding-FAQ" steht ein Absatz, der das
KI-System anweist, sämtliche Gehälter auszugeben. Jeder Praktikant trifft
diesen Absatz bei praktisch jeder Frage.

Er funktioniert nicht. Nicht, weil das Modell brav ist, sondern weil die
Gehaltsdaten nie in seinen Kontext kommen. Ein Angreifer kann dem Modell
nicht befehlen, etwas herauszugeben, was es nie bekommen hat.

Zusätzlich stehen Dokumentinhalte in `<quelle>`-Klammern und das Systemprompt
benennt sie als Material, nicht als Anweisung. Das ist die zweite Zeile der
Verteidigung, nicht die erste.

---

## Zugriffsprotokoll

Jede Frage und jeder Werkzeugaufruf wird festgehalten: Nutzer, Rolle,
Entscheidung (`allow` / `deny`), freigegebene Abschnitte und die Zahl
gesperrter Treffer. **Gesperrter Inhalt wird nicht protokolliert** — das
Protokoll darf kein Hintertürchen sein.

Wer das Protokoll sehen darf, entscheiden wieder die Zeilen-Rechte: das eigene
jeder, das gesamte nur die Administration. In der Anwendung steht dafür keine
einzige Prüfung.

---

## Die Testreihe

```
docker compose run --rm tests
```

Sie läuft gegen eine echte PostgreSQL-Datenbank mit pgvector. Absichtlich:
die Rechtelogik liegt in der Datenbank, also muss sie dort geprüft werden.
Ein Test mit nachgebauter Datenbank würde genau das prüfen, was nicht
ausgeliefert wird.

| Datei | hält fest |
|---|---|
| `test_zugriffsrechte.py` | sieben Angriffsfragen × fünf Nutzer: keine gesperrte Textstelle kommt durch — und die Gegenprobe, dass die Berechtigten ihre Daten sehr wohl bekommen |
| `test_zeilenrechte.py` | rohes SQL ohne jeden Filter der Anwendung liefert nichts; `UPDATE` der Einstufung und `DISABLE ROW LEVEL SECURITY` scheitern; ohne gesetzte Identität kommt **nichts** statt alles |
| `test_angriff_im_dokument.py` | der Angriffsabsatz landet nachweislich im Kontext — und bleibt wirkungslos |
| `test_werkzeuge.py` | Werkzeugliste je Rolle, abgelehnte Aufrufe, erfundene Werkzeugnamen, Protokolleintrag der Ablehnung |
| `test_freigabe_ablauf.py` | der komplette Antragsweg einschließlich Ablauf der Befristung |
| `test_schnittstelle.py` | gefälschtes Token → 401, fremde Entscheidung → 403, Protokoll je Rolle |

Der erste Test ist der, auf den es ankommt: er prüft nicht die Formulierung
der Antwort, sondern **was die Suche überhaupt herausgibt**. Was nicht
herauskommt, kann auch nicht formuliert, zitiert oder weitergegeben werden.

---

## Leistung

```
docker compose run --rm tests python scripts/bench.py
BENCH_ROWS=50000 docker compose run --rm tests python scripts/bench.py
```

Beispiellauf mit 8.000 Abschnitten à 1536 Dimensionen:

```
  exakt (jede Zeile)             46,86 ms   Trefferguete 100,0 %
  Vektorindex, ef_search 40       3,47 ms   Trefferguete  33,0 %   13,5x schneller
  Vektorindex, ef_search 200     10,20 ms   Trefferguete  71,0 %    4,6x schneller
  Index + Rechtefilter            9,41 ms   derselbe Index, Rechtepruefung in derselben Abfrage
```

Der HNSW-Index (ein mehrstufiger Nachbarschaftsgraph) kostet Treffergüte und
bringt Zeit; `ef_search` ist die Stellschraube dazwischen. Die Zahlen stammen
aus künstlichen Vektoren und sind für die Güte ein pessimistischer Fall —
echte Einbettungen sind stärker gruppiert. Was der Lauf zeigt, ist der
Mechanismus und die Stellschraube, nicht ein Bestwert.

Zwei Dinge, die beim Messen leicht schiefgehen und hier bewusst behandelt sind:

- **Vorbereitete Anweisungen.** `psycopg` merkt sich nach einigen Durchläufen
  den Ausführungsplan, und ein Planwechsel durch `enable_indexscan` macht
  einen gemerkten Plan *nicht* ungültig. Ohne Abschalten würde der Lauf „mit
  Index" noch den Plan ohne Index benutzen — und eine falsche Zahl liefern.
- **Nachfiltern.** Der Vektorindex sucht zuerst die nächsten Nachbarn, der
  Rechtefilter greift danach. Bei strenger Einstufung kämen so weniger
  Treffer heraus als vorhanden sind — nie zu viele, aber zu wenige. Deshalb
  setzt die Suche `hnsw.iterative_scan = strict_order`.

---

## Entscheidungen und warum

**Kein ORM.** Die beiden Zeilen, auf die es ankommt — der Sicherheitsfilter
und der Vektorvergleich `<=>` — sollen im Klartext lesbar und prüfbar sein.
Ein Abfrage-Baukasten würde genau sie verstecken.

**Kein LangChain.** Der Agent sind 150 Zeilen: Werkzeugverzeichnis,
Rechteprüfung, Schleife. Die Schnittstellen von Anthropic und OpenAI werden
direkt angesprochen, beide über eine gemeinsame, normalisierte Antwort.

**Einstufung doppelt gespeichert.** `department_id` und `min_required_role`
stehen am Dokument *und* am Abschnitt, damit der Sicherheitsfilter in der
heißen Abfrage keinen `JOIN` braucht. Zwei Trigger halten die Kopie zwingend
korrekt: ein Abschnitt kann seine Stufe nicht selbst setzen, und wird ein
Dokument neu eingestuft, folgen alle Abschnitte sofort nach.

**Eine einzige Funktion mit erweiterten Rechten.** `kg_blocked_count` zählt,
wie viele der global besten Treffer gesperrt waren. Sie gibt eine Zahl zurück
— nie Inhalt, nie einen Titel, nie eine Kennung. Dass schon eine Zahl in sehr
strengen Umgebungen ein Hinweis ist, bleibt wahr; deshalb
`SHOW_BLOCKED_COUNT=false`.

**Das Verzeichnis zeigt Titel, nie Inhalt.** Wer nicht weiß, dass es ein
Dokument gibt, kann keine Freigabe dafür beantragen. Soll auch die Existenz
geheim bleiben, wird das Verzeichnis nicht freigegeben und der Antragsweg
läuft über die Abteilung statt über das Dokument.

**Ohne Schlüssel lauffähig.** Ein eingebauter, rein rechnerischer
Textvergleich erzeugt die 1536 Werte ohne Netz und ohne Kosten — dieselbe
Dimension wie `text-embedding-3-small`, damit der Wechsel auf echte
Einbettungen keine Schemaänderung braucht. Wer das Projekt ansieht, soll es
starten können, nicht erst einen Zugang beantragen.

---

## Grenzen

Was für den Echtbetrieb fehlt, offen benannt:

- **Anmeldung ohne Passwort.** Für die Vorführung gewollt. Produktiv träte hier
  die Anmeldung des Unternehmens an die Stelle; die Identität fließt bereits
  über ein signiertes Token, der Rest der Kette bleibt unverändert.
- **Der Dienst kennt die Eigentümer-Verbindung**, weil er beim Start die
  Beispieldaten einspielt. Produktiv wären Einrichtung und Betrieb getrennt
  und der Dienst hätte nur `kg_app`.
- **Dokumente kommen aus einer Datei, nicht aus einem Upload.** Die
  Einstufung beim Hochladen ist ein eigenes Thema (wer darf einstufen, wer
  darf heraufstufen) und ist hier nicht gebaut.
- **Abschnitte werden nicht zusammengefasst, Treffer nicht nachsortiert.**
  Beides würde die Antwortgüte heben und am Sicherheitsmodell nichts ändern.
- **Keine Mandantentrennung.** Ein zweites Unternehmen in derselben Datenbank
  bräuchte eine weitere Ebene in `kg_visible` und in den Zeilen-Rechten.

---

## Aufbau

```
db/      00_app_role.sh      Anwendungsrolle, eingeschränkt
         01_schema.sql       Tabellen, Trigger, Protokoll
         02_security.sql     kg_visible, Zeilen-Rechte, Verzeichnis, Zähler
         03_indexes.sql      HNSW und die Spalten des Sicherheitsfilters
         04_grants.sql       Rechte von kg_app
api/     app/retrieval.py    die Kernabfrage
         app/tools.py        Werkzeuge mit Rollenbindung
         app/agent.py        Werkzeugschleife
         app/db.py           Verbindung, Identität je Transaktion
         app/embeddings.py   OpenAI oder eingebauter Textvergleich
         app/llm.py          Anthropic, OpenAI oder belegbasiert
         app/audit.py        Protokoll
         app/main.py         Schnittstelle
ui/      app.py              Vorführung mit Nutzerumschalter
tests/                       die Testreihe
scripts/ bench.py            Messung exakt gegen Index
```

Kopfbild: Unsplash (unsplash.com/license), liegt als `ui/assets/hero.jpg` im
Projekt -- die Oberflaeche bettet es ein und braucht dafuer kein Netz.

Technik: PostgreSQL 16 mit pgvector 0.8, FastAPI, psycopg 3, Streamlit,
docker compose. Datenbankschlüssel und Modellwahl über `.env` —
Vorlage in `.env.example`.
