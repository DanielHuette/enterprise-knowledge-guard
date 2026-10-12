-- Enterprise Knowledge Guard: security layer
--
-- Two layers, deliberately redundant:
--   Layer 1  The application puts the filter into the WHERE clause of its search.
--   Layer 2  The same check exists as row-level security. If layer 1 disappears through
--            a bug, PostgreSQL still returns no row the user may not see. That is the
--            difference between "we filter" and "it is unreachable".

-- ---------------------------------------------------------------------------
-- Identity of the current transaction, set transaction-locally per request from a
-- signed token, never from a field the browser can fill in.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION kg_current_user_id() RETURNS INT
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT NULLIF(current_setting('app.user_id', true), '')::int
$$;

CREATE OR REPLACE FUNCTION kg_role_rank(p_role VARCHAR) RETURNS SMALLINT
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT rank FROM roles WHERE name = p_role
$$;

CREATE OR REPLACE FUNCTION kg_current_role_rank() RETURNS SMALLINT
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT kg_role_rank(u.role) FROM users u WHERE u.id = kg_current_user_id()
$$;

-- ---------------------------------------------------------------------------
-- The single source of truth about who may see what. Application and row-level
-- security both use exactly this function; there is no second copy of the rule.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION kg_visible(
    p_user_id       INT,
    p_department_id INT,
    p_min_role      VARCHAR,
    p_document_id   INT
) RETURNS BOOLEAN
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT p_user_id IS NOT NULL AND (
        -- regular access: matching department (or company-wide) and sufficient rank
        EXISTS (
            SELECT 1
              FROM users u
             WHERE u.id = p_user_id
               AND (
                     p_department_id IS NULL
                     OR p_department_id IN (
                            SELECT ud.department_id
                              FROM user_departments ud
                             WHERE ud.user_id = p_user_id
                        )
                   )
               AND kg_role_rank(u.role) >= kg_role_rank(p_min_role)
        )
        -- or a time-limited grant from an approved request
        OR EXISTS (
            SELECT 1
              FROM access_grants g
             WHERE g.user_id     = p_user_id
               AND g.document_id = p_document_id
               AND g.expires_at  > now()
        )
    )
$$;

-- ---------------------------------------------------------------------------
-- Regular access only, ignoring time-limited grants. Deciding about a document
-- requires this: whoever cannot read a document must not hand it out. SECURITY
-- DEFINER because it has to see the classification of documents the caller cannot
-- read; it returns a boolean and nothing else.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION kg_has_regular_access(p_user_id INT, p_document_id INT)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1
          FROM documents d
          JOIN users u ON u.id = p_user_id
         WHERE d.id = p_document_id
           AND (
                 d.department_id IS NULL
                 OR d.department_id IN (
                        SELECT ud.department_id
                          FROM user_departments ud
                         WHERE ud.user_id = p_user_id
                    )
               )
           AND kg_role_rank(u.role) >= kg_role_rank(d.min_required_role)
    )
$$;

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------
ALTER TABLE documents        ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks  ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_requests  ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_grants    ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log        ENABLE ROW LEVEL SECURITY;

CREATE POLICY documents_read ON documents FOR SELECT
    USING (kg_visible(kg_current_user_id(), department_id, min_required_role, id));

CREATE POLICY chunks_read ON document_chunks FOR SELECT
    USING (kg_visible(kg_current_user_id(), department_id, min_required_role, document_id));

-- Everyone may file a request, but only for themselves.
CREATE POLICY requests_insert_own ON access_requests FOR INSERT
    WITH CHECK (requester_id = kg_current_user_id());

-- Own requests, plus requests a manager may decide: for documents they can read.
CREATE POLICY requests_read ON access_requests FOR SELECT
    USING (requester_id = kg_current_user_id()
           OR (kg_current_role_rank() >= 30
               AND kg_has_regular_access(kg_current_user_id(), document_id)));

-- Deciding requires at least Manager and regular access to the document, and nobody
-- decides their own request.
CREATE POLICY requests_decide ON access_requests FOR UPDATE
    USING (kg_current_role_rank() >= 30
           AND requester_id <> kg_current_user_id()
           AND kg_has_regular_access(kg_current_user_id(), document_id))
    WITH CHECK (kg_current_role_rank() >= 30
                AND requester_id <> kg_current_user_id()
                AND kg_has_regular_access(kg_current_user_id(), document_id));

-- Only a Manager or above may grant access, always under their own id, never to
-- themselves, and only for documents they can read regularly.
CREATE POLICY grants_insert ON access_grants FOR INSERT
    WITH CHECK (granted_by = kg_current_user_id()
                AND user_id <> kg_current_user_id()
                AND kg_current_role_rank() >= 30
                AND kg_has_regular_access(kg_current_user_id(), document_id));

-- Extending a grant is reserved for whoever issued it, again Manager or above.
CREATE POLICY grants_update ON access_grants FOR UPDATE
    USING (granted_by = kg_current_user_id() AND kg_current_role_rank() >= 30)
    WITH CHECK (granted_by = kg_current_user_id()
                AND user_id <> kg_current_user_id()
                AND kg_current_role_rank() >= 30
                AND kg_has_regular_access(kg_current_user_id(), document_id));

CREATE POLICY grants_read ON access_grants FOR SELECT
    USING (user_id = kg_current_user_id()
           OR granted_by = kg_current_user_id()
           OR kg_current_role_rank() >= 30);

-- Everyone sees their own audit rows; only Admin sees all of them.
CREATE POLICY audit_read ON audit_log FOR SELECT
    USING (user_id = kg_current_user_id() OR kg_current_role_rank() >= 40);

CREATE POLICY audit_insert ON audit_log FOR INSERT
    WITH CHECK (user_id = kg_current_user_id());

-- ---------------------------------------------------------------------------
-- Counter of blocked hits: the only SECURITY DEFINER function in the system. It
-- returns a number, never content, a title or an id, so the interface can say "3 more
-- relevant hits are blocked for you" without leaking anything. SHOW_BLOCKED_COUNT=false
-- turns it off for environments where even a count is too much of a hint.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION kg_blocked_count(
    p_user_id INT,
    p_query   vector(1536),
    p_k       INT
) RETURNS INT
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    WITH topk AS (
        SELECT c.id, c.department_id, c.min_required_role, c.document_id
          FROM document_chunks c
         WHERE c.embedding IS NOT NULL
         ORDER BY c.embedding <=> p_query
         LIMIT p_k
    )
    SELECT count(*)::int
      FROM topk t
     WHERE NOT kg_visible(p_user_id, t.department_id, t.min_required_role, t.document_id)
$$;

-- ---------------------------------------------------------------------------
-- Catalog of all documents: title, department, classification, never content.
-- Deliberate: nobody can request access to a document they do not know exists. The
-- view runs with its owner's rights and therefore bypasses row-level security, but it
-- exposes no column that holds content. If even existence must stay secret, do not
-- grant the view and route requests through departments instead of documents.
-- ---------------------------------------------------------------------------
CREATE VIEW document_catalog AS
SELECT d.id,
       d.title,
       d.department_id,
       dep.name AS department,
       d.min_required_role,
       r.rank AS min_required_rank,
       d.created_at
  FROM documents d
  LEFT JOIN departments dep ON dep.id = d.department_id
  JOIN roles r ON r.name = d.min_required_role;
