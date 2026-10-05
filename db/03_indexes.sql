-- Enterprise Knowledge Guard -- Indizes
--
-- Ohne Index vergleicht PostgreSQL jede Zeile mit dem Suchvektor (exakt, aber
-- linear). Der HNSW-Index (Hierarchical Navigable Small World -- ein
-- mehrstufiger Nachbarschaftsgraph) findet die naechsten Nachbarn in
-- annaehernd gleichbleibender Zeit und verliert dafuer minimal an
-- Treffergenauigkeit. scripts/bench.py zeigt den Unterschied mit echten Zahlen.

CREATE INDEX chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Die beiden Spalten stehen im Sicherheitsfilter jeder Suche.
CREATE INDEX chunks_department_idx ON document_chunks (department_id);
CREATE INDEX chunks_min_role_idx   ON document_chunks (min_required_role);
CREATE INDEX chunks_document_idx   ON document_chunks (document_id);

CREATE INDEX grants_lookup_idx ON access_grants (user_id, document_id, expires_at);
