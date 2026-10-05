"""Beispieldaten einspielen. Laeuft mit der Eigentuemer-Verbindung und ist
wiederholbar: ist schon etwas drin, passiert nichts.
"""
from __future__ import annotations

from .db import as_owner, fetch_one, to_vector
from .embeddings import embed
from .seed_data import DEPARTMENTS, DOCUMENTS, USERS


def is_seeded() -> bool:
    with as_owner() as conn:
        row = fetch_one(conn, "SELECT count(*) AS n FROM users")
    return (row["n"] or 0) > 0


def seed(force: bool = False) -> dict:
    if is_seeded() and not force:
        return {"status": "bereits vorhanden"}

    with as_owner() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute(
                    "TRUNCATE audit_log, access_grants, access_requests, "
                    "document_chunks, documents, user_departments, users, "
                    "departments RESTART IDENTITY CASCADE"
                )

            dept_ids: dict[str, int] = {}
            for name in DEPARTMENTS:
                cur.execute(
                    "INSERT INTO departments (name) VALUES (%s) RETURNING id", (name,)
                )
                dept_ids[name] = cur.fetchone()["id"]

            for user in USERS:
                cur.execute(
                    """
                    INSERT INTO users (username, display_name, job_title, role)
                    VALUES (%s, %s, %s, %s) RETURNING id
                    """,
                    (
                        user["username"],
                        user["display_name"],
                        user["job_title"],
                        user["role"],
                    ),
                )
                user_id = cur.fetchone()["id"]
                for dept in user["departments"]:
                    cur.execute(
                        "INSERT INTO user_departments (user_id, department_id) "
                        "VALUES (%s, %s)",
                        (user_id, dept_ids[dept]),
                    )

            # Alle Abschnitte in einem Durchgang einbetten -- ein Aufruf statt
            # einem pro Abschnitt.
            texts = [
                chunk for document in DOCUMENTS for chunk in document["chunks"]
            ]
            vectors = embed(texts)
            position = 0

            for document in DOCUMENTS:
                cur.execute(
                    """
                    INSERT INTO documents (title, department_id, min_required_role)
                    VALUES (%s, %s, %s) RETURNING id
                    """,
                    (
                        document["title"],
                        dept_ids.get(document["department"])
                        if document["department"]
                        else None,
                        document["min_required_role"],
                    ),
                )
                document_id = cur.fetchone()["id"]
                for index, chunk in enumerate(document["chunks"]):
                    cur.execute(
                        """
                        INSERT INTO document_chunks
                            (document_id, chunk_index, content, embedding)
                        VALUES (%s, %s, %s, %s::vector)
                        """,
                        (document_id, index, chunk, to_vector(vectors[position])),
                    )
                    position += 1

    return {
        "status": "eingespielt",
        "nutzer": len(USERS),
        "dokumente": len(DOCUMENTS),
        "abschnitte": len(texts),
    }


if __name__ == "__main__":
    import sys

    print(seed(force="--force" in sys.argv))
