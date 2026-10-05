-- Enterprise Knowledge Guard -- Sicherheitsschicht
--
-- Zwei Ebenen, absichtlich doppelt:
--   Ebene 1  Die Anwendung stellt den Filter in die WHERE-Klausel ihrer Suche.
--   Ebene 2  Dieselbe Pruefung liegt als Zeilen-Recht (Row Level Security) in
--            der Datenbank. Faellt Ebene 1 durch einen Programmierfehler weg,
--            liefert PostgreSQL trotzdem keine Zeile aus, die der Nutzer nicht
--            sehen darf. Das ist der Unterschied zwischen "wir filtern" und
--            "es ist nicht erreichbar".

-- ---------------------------------------------------------------------------
-- Identitaet der laufenden Transaktion.
-- Die Anwendung setzt sie per SET LOCAL je Anfrage. Sie kommt aus einem
-- signierten Token, nicht aus einem Feld, das der Browser frei fuellen kann.
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
-- Die eine Wahrheit darueber, wer was sehen darf.
-- Anwendung und Zeilen-Rechte benutzen genau diese Funktion -- es gibt keine
-- zweite, abweichende Kopie der Regel.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION kg_visible(
    p_user_id       INT,
    p_department_id INT,
    p_min_role      VARCHAR,
    p_document_id   INT
) RETURNS BOOLEAN
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT p_user_id IS NOT NULL AND (
        -- regulaere Freigabe: richtige Abteilung (oder firmenweit) und Rang hoch genug
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
        -- oder eine befristete Einzelfreigabe aus einem genehmigten Antrag
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
-- Zeilen-Rechte
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

-- Antrag stellen darf jeder -- aber nur fuer sich selbst.
CREATE POLICY requests_insert_own ON access_requests FOR INSERT
    WITH CHECK (requester_id = kg_current_user_id());

CREATE POLICY requests_read ON access_requests FOR SELECT
    USING (requester_id = kg_current_user_id() OR kg_current_role_rank() >= 30);

-- Entscheiden darf erst ab Leitung.
CREATE POLICY requests_decide ON access_requests FOR UPDATE
    USING (kg_current_role_rank() >= 30)
    WITH CHECK (kg_current_role_rank() >= 30);

-- Eine Freigabe erteilen darf nur, wer selbst mindestens Leitung ist, und sie
-- wird zwingend unter seinem Namen eingetragen.
CREATE POLICY grants_insert ON access_grants FOR INSERT
    WITH CHECK (granted_by = kg_current_user_id() AND kg_current_role_rank() >= 30);

-- Verlaengern darf, wer die Freigabe erteilt hat -- wieder ab Leitung.
CREATE POLICY grants_update ON access_grants FOR UPDATE
    USING (granted_by = kg_current_user_id() AND kg_current_role_rank() >= 30)
    WITH CHECK (granted_by = kg_current_user_id() AND kg_current_role_rank() >= 30);

CREATE POLICY grants_read ON access_grants FOR SELECT
    USING (user_id = kg_current_user_id()
           OR granted_by = kg_current_user_id()
           OR kg_current_role_rank() >= 30);

-- Das eigene Protokoll sieht jeder, das gesamte nur die Administration.
CREATE POLICY audit_read ON audit_log FOR SELECT
    USING (user_id = kg_current_user_id() OR kg_current_role_rank() >= 40);

CREATE POLICY audit_insert ON audit_log FOR INSERT
    WITH CHECK (user_id = kg_current_user_id());

-- ---------------------------------------------------------------------------
-- Zaehler fuer gesperrte Treffer.
-- Die einzige Funktion mit erweiterten Rechten im System. Sie gibt eine Zahl
-- zurueck, nie Inhalt, nie einen Titel, nie eine Kennung. So kann die
-- Oberflaeche "3 relevantere Treffer sind fuer dich gesperrt" anzeigen, ohne
-- dass dabei etwas aus den gesperrten Abschnitten nach aussen gelangt.
-- Abschaltbar ueber SHOW_BLOCKED_COUNT=false, weil schon eine Zahl in sehr
-- strengen Umgebungen ein Hinweis ist.
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
-- Verzeichnis aller Dokumente: Titel, Abteilung, Freigabestufe -- kein Inhalt.
-- Bewusste Entscheidung: wer nicht weiss, dass es ein Dokument gibt, kann auch
-- keine Freigabe dafuer beantragen. Die Sicht laeuft mit den Rechten ihrer
-- Eigentuemerin und umgeht damit die Zeilen-Rechte -- sie gibt aber keine
-- Spalte heraus, die Inhalt enthaelt.
-- Soll auch die Existenz geheim bleiben, wird das Verzeichnis nicht
-- freigegeben und der Antragsweg laeuft ueber die Abteilung statt das Dokument.
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
