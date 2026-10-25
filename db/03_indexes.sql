-- Enterprise Knowledge Guard: indexes
--
-- Without an index PostgreSQL compares every row with the query vector (exact, but
-- linear). The HNSW index (Hierarchical Navigable Small World, a layered neighbourhood
-- graph) finds nearest neighbours in near-constant time at a small cost in recall.
-- scripts/bench.py measures the difference.

CREATE INDEX chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Both columns appear in the security filter of every search.
CREATE INDEX chunks_department_idx ON document_chunks (department_id);
CREATE INDEX chunks_min_role_idx   ON document_chunks (min_required_role);
CREATE INDEX chunks_document_idx   ON document_chunks (document_id);

CREATE INDEX grants_lookup_idx ON access_grants (user_id, document_id, expires_at);
