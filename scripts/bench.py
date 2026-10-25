"""Benchmark: exact search versus the vector index.

Context: Inserts synthetic chunks inside one owner transaction, measures the same search
in four variants and rolls everything back, so the database is unchanged afterwards.
Recall is the share of the exact top 5 that the fast variant also finds. The filtered
variant measures the cost of kg_visible inside the query; row-level security is not part of
it because the benchmark rows exist only inside the owner's uncommitted transaction.
| Input: BENCH_ROWS and BENCH_QUERIES environment variables. | Output: timing table.

Usage:
    docker compose run --rm tests python scripts/bench.py
    BENCH_ROWS=50000 docker compose run --rm tests python scripts/bench.py
"""

from __future__ import annotations

import os
import random
import statistics
import time
from dataclasses import dataclass

from knowledge_guard.db import Connection, as_owner, fetch_all, fetch_one, to_vector
from knowledge_guard.embeddings import EMBEDDING_DIM

ROWS = int(os.getenv("BENCH_ROWS", "5000"))
QUERIES = int(os.getenv("BENCH_QUERIES", "20"))
TOPIC_CENTRES = 64
TOPIC_SPREAD = 0.35 / EMBEDDING_DIM**0.5
SEED = 42
BENCH_TITLE = "__benchmark__"

EXACT_SQL = """
SELECT c.id FROM document_chunks c
 WHERE c.embedding IS NOT NULL
 ORDER BY c.embedding <=> %(query)s::vector LIMIT 5
"""

FILTERED_SQL = """
SELECT c.id FROM document_chunks c
 WHERE kg_visible(%(uid)s, c.department_id, c.min_required_role, c.document_id)
   AND c.embedding IS NOT NULL
 ORDER BY c.embedding <=> %(query)s::vector LIMIT 5
"""

INDEX_OFF = ("SET LOCAL enable_indexscan = off", "SET LOCAL enable_bitmapscan = off")
INDEX_ON = (
    "SET LOCAL enable_indexscan = on",
    "SET LOCAL enable_bitmapscan = on",
    "SET LOCAL hnsw.ef_search = 40",
)
WIDE_SEARCH = (*INDEX_ON, "SET LOCAL hnsw.ef_search = 200")


@dataclass(frozen=True)
class Measurement:
    median_ms: float
    hits: list[list[int]]


def normalise(values: list[float]) -> list[float]:
    norm = sum(value * value for value in values) ** 0.5
    return [value / norm for value in values]


def topic_centres(rng: random.Random) -> list[list[float]]:
    return [
        normalise([rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)]) for _ in range(TOPIC_CENTRES)
    ]


def topic_vector(rng: random.Random, centres: list[list[float]]) -> list[float]:
    """A vector near a topic centre.

    Uniform random vectors would mislead: in high dimensions they are almost equidistant,
    which forces any neighbourhood graph to visit nearly everything. Real document
    embeddings form topic clusters, which this imitates.
    """
    centre = rng.choice(centres)
    return normalise([value + rng.gauss(0.0, TOPIC_SPREAD) for value in centre])


def insert_rows(conn: Connection, rng: random.Random, centres: list[list[float]]) -> None:
    row = fetch_one(
        conn,
        "INSERT INTO documents (title, department_id, min_required_role) "
        "VALUES (%s, NULL, 'Intern') RETURNING id",
        (BENCH_TITLE,),
    )
    if row is None:
        raise RuntimeError("benchmark document was not created")
    with (
        conn.cursor() as cur,
        cur.copy(
            "COPY document_chunks (document_id, chunk_index, content, embedding) FROM STDIN"
        ) as copy,
    ):
        for index in range(ROWS):
            copy.write_row(
                (row["id"], index, f"row {index}", to_vector(topic_vector(rng, centres)))
            )


def measure(
    conn: Connection,
    sql: str,
    vectors: list[str],
    settings: tuple[str, ...],
    uid: int | None = None,
) -> Measurement:
    timings: list[float] = []
    hits: list[list[int]] = []
    for vector in vectors:
        for statement in settings:
            conn.execute(statement)
        start = time.perf_counter()
        rows = fetch_all(conn, sql, {"query": vector, "uid": uid})
        timings.append((time.perf_counter() - start) * 1000.0)
        hits.append([row["id"] for row in rows])
    return Measurement(statistics.median(timings), hits)


def recall(exact: Measurement, fast: Measurement) -> float:
    return statistics.mean(
        len(set(a) & set(b)) / len(a) for a, b in zip(exact.hits, fast.hits, strict=True) if a
    )


def uses_index(conn: Connection, vector: str) -> bool:
    """Check the plan of the default fast run; ef_search affects the planner's cost."""
    for statement in INDEX_ON:
        conn.execute(statement)
    plan = fetch_all(conn, "EXPLAIN " + EXACT_SQL, {"query": vector})
    return any("chunks_embedding_hnsw" in row["QUERY PLAN"] for row in plan)


def report(total: int, exact: Measurement, rows: list[tuple[str, Measurement, str]]) -> None:
    print(f"\nChunks in the database:  {total}")
    print(f"Queries per variant:     {QUERIES} (median)\n")
    print(f"  {'exact (every row)':<28}{exact.median_ms:8.2f} ms   recall 100.0 %")
    for label, result, extra in rows:
        print(f"  {label:<28}{result.median_ms:8.2f} ms   {extra}")


def main() -> None:
    rng = random.Random(SEED)
    with as_owner() as conn:
        # psycopg caches prepared plans, and a plan switch via enable_indexscan does not
        # invalidate a cached plan; without this the indexed run would reuse the exact plan.
        conn.prepare_threshold = None
        centres = topic_centres(rng)
        print(f"Inserting {ROWS} benchmark rows ...", flush=True)
        insert_rows(conn, rng, centres)
        conn.execute("ANALYZE document_chunks")
        total_row = fetch_one(conn, "SELECT count(*) AS n FROM document_chunks")
        admin = fetch_one(conn, "SELECT id FROM users WHERE role = 'Admin' ORDER BY id LIMIT 1")
        vectors = [to_vector(topic_vector(rng, centres)) for _ in range(QUERIES)]

        exact = measure(conn, EXACT_SQL, vectors, INDEX_OFF)
        default = measure(conn, EXACT_SQL, vectors, INDEX_ON)
        wide = measure(conn, EXACT_SQL, vectors, WIDE_SEARCH)
        filtered = measure(conn, FILTERED_SQL, vectors, INDEX_ON, admin["id"] if admin else None)
        indexed = uses_index(conn, vectors[0])
        conn.rollback()

    report(
        int(total_row["n"]) if total_row else 0,
        exact,
        [
            ("index, ef_search 40", default, _summary(exact, default)),
            ("index, ef_search 200", wide, _summary(exact, wide)),
            ("index + access filter", filtered, "same index, access check in the same query"),
        ],
    )
    print(f"\n  Plan of the fast run: {'vector index' if indexed else 'sequential scan'}")


def _summary(exact: Measurement, fast: Measurement) -> str:
    return (
        f"recall {recall(exact, fast) * 100:5.1f} %   "
        f"{exact.median_ms / fast.median_ms:.1f}x faster"
    )


if __name__ == "__main__":
    main()
