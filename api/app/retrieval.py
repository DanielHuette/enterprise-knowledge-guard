"""Suche mit eingebauter Rechtepruefung.

Eine einzige Abfrage macht beides gleichzeitig: Aehnlichkeit messen und
Zugriff pruefen. Es gibt keinen Zwischenschritt, in dem gesperrter Inhalt
ueberhaupt im Arbeitsspeicher der Anwendung liegt -- er verlaesst die
Datenbank nicht.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from .config import settings
from .db import as_user, to_vector
from .embeddings import embed_one

# Der Kern des Projekts. Die Zeile mit kg_visible ist der Unterschied zwischen
# einem Firmen-Chatbot und einem Datenschutzvorfall.
SEARCH_SQL = """
SELECT c.id,
       c.document_id,
       d.title,
       c.content,
       c.min_required_role,
       c.department_id,
       (c.embedding <=> %(query)s::vector) AS distance
  FROM document_chunks c
  JOIN documents d ON d.id = c.document_id
 WHERE kg_visible(%(user_id)s, c.department_id, c.min_required_role, c.document_id)
   AND c.embedding IS NOT NULL
 ORDER BY c.embedding <=> %(query)s::vector
 LIMIT %(k)s
"""


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    title: str
    content: str
    min_required_role: str
    distance: float

    def as_source(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "min_required_role": self.min_required_role,
            "distance": round(self.distance, 4),
            "excerpt": self.content[:400],
        }


@dataclass
class SearchResult:
    hits: list[Hit]
    blocked_count: int

    @property
    def chunk_ids(self) -> list[int]:
        return [hit.chunk_id for hit in self.hits]


def _enable_iterative_scan(conn: psycopg.Connection) -> None:
    """Mehr Nachbarn nachladen, wenn der Filter viele Treffer wegnimmt.

    Der Vektorindex sucht zuerst die naechsten Nachbarn und erst danach greift
    der Sicherheitsfilter. Ohne diese Einstellung koennte eine Suche bei
    strenger Einstufung weniger Treffer liefern als vorhanden -- nie zu viele,
    aber zu wenige. Aeltere pgvector-Versionen kennen die Einstellung nicht;
    dann bleibt es beim bisherigen Verhalten.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL hnsw.iterative_scan = strict_order")
    except psycopg.errors.Error:
        conn.rollback()


def search(user_id: int, question: str, k: int | None = None) -> SearchResult:
    k = k or settings.top_k
    query_vector = to_vector(embed_one(question))

    with as_user(user_id) as conn:
        _enable_iterative_scan(conn)
        with conn.cursor() as cur:
            cur.execute(
                SEARCH_SQL, {"query": query_vector, "user_id": user_id, "k": k}
            )
            rows = cur.fetchall()

        blocked = 0
        if settings.show_blocked_count:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT kg_blocked_count(%(user_id)s, %(query)s::vector, %(k)s) AS n",
                    {"user_id": user_id, "query": query_vector, "k": k},
                )
                blocked = cur.fetchone()["n"] or 0

    hits = [
        Hit(
            chunk_id=row["id"],
            document_id=row["document_id"],
            title=row["title"],
            content=row["content"],
            min_required_role=row["min_required_role"],
            distance=float(row["distance"]),
        )
        for row in rows
    ]
    return SearchResult(hits=hits, blocked_count=blocked)
