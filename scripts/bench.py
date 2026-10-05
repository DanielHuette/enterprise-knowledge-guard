"""Messung: exakte Suche gegen Vektorindex.

Legt kuenstliche Abschnitte an, misst dieselbe Suche dreimal und raeumt wieder
auf. Die drei Zeilen zeigen genau das, was bei einem Firmenbestand mit vielen
Dokumenten ueber Brauchbarkeit entscheidet:

  exakt            jede Zeile wird verglichen -- immer korrekt, waechst linear
  Vektorindex      Nachbarschaftsgraph (HNSW) -- annaehernd gleichbleibend schnell
  Index + Rechte   derselbe Index mit dem Sicherheitsfilter der Anwendung

Dazu die Trefferguete: wie viele der fuenf Treffer der schnellen Suche
stimmen mit der exakten Suche ueberein.

  docker compose run --rm tests python scripts/bench.py
  BENCH_ROWS=50000 docker compose run --rm tests python scripts/bench.py
"""
from __future__ import annotations

import os
import random
import statistics
import sys
import time
from pathlib import Path

for _kandidat in (Path("/app"), Path(__file__).resolve().parents[1] / "api"):
    if (_kandidat / "app" / "__init__.py").exists():
        sys.path.insert(0, str(_kandidat))
        break

from app.db import as_owner, to_vector  # noqa: E402
from app.config import settings  # noqa: E402

ZEILEN = int(os.getenv("BENCH_ROWS", "5000"))
ABFRAGEN = int(os.getenv("BENCH_QUERIES", "20"))
TITEL = "__messreihe__"


def _normieren(werte: list[float]) -> list[float]:
    norm = sum(wert * wert for wert in werte) ** 0.5
    return [wert / norm for wert in werte]


def mittelpunkte(rng: random.Random, anzahl: int = 64) -> list[list[float]]:
    return [
        _normieren([rng.gauss(0.0, 1.0) for _ in range(settings.embedding_dim)])
        for _ in range(anzahl)
    ]


def themenvektor(rng: random.Random, zentren: list[list[float]]) -> list[float]:
    """Vektor in der Naehe eines Themenmittelpunkts.

    Reine Zufallsvektoren waeren fuer diese Messung irrefuehrend: in hohen
    Dimensionen sind sie fast alle gleich weit voneinander entfernt, und dann
    muss auch ein Nachbarschaftsgraph praktisch alles durchsuchen. Echte
    Einbettungen von Firmenunterlagen bilden Themenhaeufungen -- genau das wird
    hier nachgebildet.
    """
    zentrum = rng.choice(zentren)
    return _normieren(
        [wert + rng.gauss(0.0, 0.35) for wert in zentrum]
    )


def anlegen(conn, rng: random.Random, zentren: list[list[float]]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (title, department_id, min_required_role) "
            "VALUES (%s, NULL, 'Intern') RETURNING id",
            (TITEL,),
        )
        document_id = cur.fetchone()["id"]
        with cur.copy(
            "COPY document_chunks (document_id, chunk_index, content, embedding) "
            "FROM STDIN"
        ) as kopie:
            for index in range(ZEILEN):
                kopie.write_row(
                    (document_id, index, f"Messzeile {index}",
                     to_vector(themenvektor(rng, zentren)))
                )
    return document_id


def aufraeumen(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE title = %s", (TITEL,))


def messen(conn, sql: str, vektoren: list[str], vorlauf: list[str],
           uid: int | None = None) -> tuple[float, list[list[int]]]:
    zeiten, treffer = [], []
    for vektor in vektoren:
        with conn.cursor() as cur:
            for zeile in vorlauf:
                cur.execute(zeile)
            start = time.perf_counter()
            cur.execute(sql, {"query": vektor, "uid": uid})
            reihen = cur.fetchall()
            zeiten.append((time.perf_counter() - start) * 1000.0)
            treffer.append([reihe["id"] for reihe in reihen])
    return statistics.median(zeiten), treffer


EXAKT = """
SELECT c.id FROM document_chunks c
 WHERE c.embedding IS NOT NULL
 ORDER BY c.embedding <=> %(query)s::vector LIMIT 5
"""

MIT_RECHTEN = """
SELECT c.id FROM document_chunks c
 WHERE kg_visible(%(uid)s, c.department_id, c.min_required_role, c.document_id)
   AND c.embedding IS NOT NULL
 ORDER BY c.embedding <=> %(query)s::vector LIMIT 5
"""


def main() -> None:
    rng = random.Random(42)
    with as_owner() as conn:
        # Vorbereitete Anweisungen hier abschalten: psycopg merkt sich nach
        # einigen Durchlaeufen den Ausfuehrungsplan, und ein Planwechsel durch
        # enable_indexscan macht einen gemerkten Plan NICHT ungueltig. Ohne
        # diese Zeile wuerde die Messung mit Index noch den Plan ohne Index
        # benutzen -- und ein falsches Ergebnis liefern.
        conn.prepare_threshold = None
        aufraeumen(conn)
        print(f"Lege {ZEILEN} Messzeilen an ...", flush=True)
        zentren = mittelpunkte(rng)
        anlegen(conn, rng, zentren)
        with conn.cursor() as cur:
            cur.execute("ANALYZE document_chunks")
            cur.execute("SELECT count(*) AS n FROM document_chunks")
            gesamt = cur.fetchone()["n"]
            # Fuer die dritte Messung ein Nutzer, der alles sehen darf --
            # sonst filtert die Rechtepruefung alles weg und die Zeit waere
            # ohne Aussage.
            cur.execute(
                "SELECT id FROM users WHERE role = 'Admin' ORDER BY id LIMIT 1"
            )
            zeile = cur.fetchone()
            admin_id = zeile["id"] if zeile else None

        vektoren = [to_vector(themenvektor(rng, zentren)) for _ in range(ABFRAGEN)]

        # SET LOCAL gilt bis zum Ende der Transaktion -- deshalb wird der
        # Index fuer die schnellen Durchlaeufe ausdruecklich wieder angeschaltet.
        ohne_index = ["SET LOCAL enable_indexscan = off",
                      "SET LOCAL enable_bitmapscan = off"]
        mit_index = ["SET LOCAL enable_indexscan = on",
                     "SET LOCAL enable_bitmapscan = on"]
        # ef_search bestimmt, wie viele Nachbarn der Graph unterwegs
        # betrachtet: mehr davon kostet Zeit und bringt Trefferguete.
        breiter = mit_index + ["SET LOCAL hnsw.ef_search = 200"]
        zeit_exakt, treffer_exakt = messen(conn, EXAKT, vektoren, ohne_index)
        zeit_index, treffer_index = messen(conn, EXAKT, vektoren, mit_index)
        zeit_breit, treffer_breit = messen(conn, EXAKT, vektoren, breiter)
        zeit_rechte, _ = messen(conn, MIT_RECHTEN, vektoren, mit_index, admin_id)

        def guete(treffer: list[list[int]]) -> float:
            return statistics.mean(
                len(set(a) & set(b)) / len(a)
                for a, b in zip(treffer_exakt, treffer)
                if a
            )

        guete_standard = guete(treffer_index)
        guete_breit = guete(treffer_breit)

        # Nachweis, dass der schnelle Durchlauf wirklich den Index benutzt.
        with conn.cursor() as cur:
            cur.execute("SET LOCAL enable_indexscan = on")
            cur.execute("EXPLAIN " + EXAKT, {"query": vektoren[0], "uid": None})
            plan = " ".join(zeile["QUERY PLAN"] for zeile in cur.fetchall())

        aufraeumen(conn)

    print()
    print(f"Abschnitte in der Datenbank: {gesamt}")
    print(f"Abfragen je Variante:        {ABFRAGEN} (Median)")
    print()
    print(f"  exakt (jede Zeile)          {zeit_exakt:8.2f} ms   "
          f"Trefferguete 100,0 %")
    print(f"  Vektorindex, ef_search 40   {zeit_index:8.2f} ms   "
          f"Trefferguete {guete_standard * 100:5.1f} %".replace(".", ",") + "   "
          f"{zeit_exakt / zeit_index:.1f}x schneller".replace(".", ","))
    print(f"  Vektorindex, ef_search 200  {zeit_breit:8.2f} ms   "
          f"Trefferguete {guete_breit * 100:5.1f} %".replace(".", ",") + "   "
          f"{zeit_exakt / zeit_breit:.1f}x schneller".replace(".", ","))
    print(f"  Index + Rechtefilter        {zeit_rechte:8.2f} ms   "
          f"derselbe Index, Rechtepruefung in derselben Abfrage")
    print()
    print("  Trefferguete = Anteil der fuenf exakten Treffer, die auch die")
    print("  schnelle Suche findet. ef_search ist die Stellschraube zwischen")
    print("  Zeit und Guete.")
    benutzt = "chunks_embedding_hnsw" in plan
    print(f"  Plan des schnellen Durchlaufs: "
          f"{'Vektorindex' if benutzt else 'sequenzieller Durchlauf'}")


if __name__ == "__main__":
    main()
