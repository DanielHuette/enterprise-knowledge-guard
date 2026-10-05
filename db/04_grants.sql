-- Enterprise Knowledge Guard -- Rechte der Anwendungsrolle
--
-- Die Anwendung bekommt genau die Rechte, die sie braucht. Kein DELETE auf
-- Dokumenten, kein UPDATE auf dem Protokoll, kein Recht, Einstufungen zu
-- aendern. Was sie nicht darf, kann auch ein Fehler in ihr nicht anrichten.

\set app_user `echo "$KG_APP_USER"`

GRANT USAGE ON SCHEMA public TO :"app_user";

GRANT SELECT ON roles, departments, users, user_departments,
                documents, document_chunks               TO :"app_user";
GRANT SELECT, INSERT, UPDATE ON access_grants            TO :"app_user";
GRANT SELECT, INSERT, UPDATE ON access_requests          TO :"app_user";
GRANT SELECT, INSERT         ON audit_log                TO :"app_user";

GRANT USAGE, SELECT ON SEQUENCE access_requests_id_seq, access_grants_id_seq,
                                audit_log_id_seq         TO :"app_user";

GRANT EXECUTE ON FUNCTION kg_blocked_count(INT, vector, INT) TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_visible(INT, INT, VARCHAR, INT) TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_role_rank(VARCHAR)              TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_current_user_id()               TO :"app_user";
GRANT EXECUTE ON FUNCTION kg_current_role_rank()             TO :"app_user";
GRANT SELECT ON document_catalog TO :"app_user";
