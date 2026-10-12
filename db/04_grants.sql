-- Enterprise Knowledge Guard: privileges of the application role
--
-- The service gets exactly what it needs: no DELETE on documents, no UPDATE on the
-- audit log, no way to change classifications. What it may not do, a bug in it cannot
-- do either.

\set app_user `echo "$KG_APP_USER"`

GRANT USAGE ON SCHEMA public TO :"app_user";

-- SECURITY DEFINER functions are executable by PUBLIC by default; only the service may.
REVOKE EXECUTE ON FUNCTION kg_blocked_count(INT, vector, INT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION kg_has_regular_access(INT, INT)    FROM PUBLIC;

GRANT SELECT ON roles, departments, users, user_departments,
                documents, document_chunks               TO :"app_user";
GRANT SELECT, INSERT, UPDATE ON access_grants            TO :"app_user";
GRANT SELECT, INSERT, UPDATE ON access_requests          TO :"app_user";
GRANT SELECT, INSERT         ON audit_log                TO :"app_user";

GRANT USAGE, SELECT ON SEQUENCE access_requests_id_seq, access_grants_id_seq,
                                audit_log_id_seq         TO :"app_user";

GRANT EXECUTE ON FUNCTION kg_blocked_count(INT, vector, INT) TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_visible(INT, INT, VARCHAR, INT) TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_has_regular_access(INT, INT)    TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_role_rank(VARCHAR)              TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_current_user_id()               TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_current_role_rank()             TO :"app_user";
GRANT SELECT ON document_catalog TO :"app_user";
