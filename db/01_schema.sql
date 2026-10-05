-- Enterprise Knowledge Guard -- Schema
-- Ausgefuehrt als Eigentuemer-Rolle (kg_owner). Die Anwendung verbindet sich
-- spaeter mit kg_app, die KEIN Tabelleneigentuemer ist und daher den
-- Zeilen-Rechten (Row Level Security) in 02_rls.sql unterliegt.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Rollen als Daten, nicht als Code.
-- Eine neue Stufe einzufuehren ist ein INSERT, kein Deployment.
-- ---------------------------------------------------------------------------
CREATE TABLE roles (
    name  VARCHAR(20) PRIMARY KEY,
    rank  SMALLINT    NOT NULL UNIQUE,
    label TEXT        NOT NULL
);

INSERT INTO roles (name, rank, label) VALUES
    ('Intern',   10, 'Praktikum'),
    ('Employee', 20, 'Mitarbeitende'),
    ('Manager',  30, 'Leitung'),
    ('Admin',    40, 'Geschaeftsfuehrung / Administration');

CREATE TABLE departments (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE users (
    id           SERIAL PRIMARY KEY,
    username     VARCHAR(50) UNIQUE NOT NULL,
    display_name TEXT        NOT NULL,
    job_title    TEXT        NOT NULL,
    role         VARCHAR(20) NOT NULL REFERENCES roles(name)
);

CREATE TABLE user_departments (
    user_id       INT NOT NULL REFERENCES users(id)       ON DELETE CASCADE,
    department_id INT NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, department_id)
);

-- Dokument = Quelle mit einer Freigabestufe.
-- department_id IS NULL bedeutet firmenweit offen.
CREATE TABLE documents (
    id                SERIAL PRIMARY KEY,
    title             TEXT        NOT NULL,
    source            TEXT        NOT NULL DEFAULT 'seed',
    department_id     INT         REFERENCES departments(id) ON DELETE CASCADE,
    min_required_role VARCHAR(20) NOT NULL REFERENCES roles(name),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Textabschnitt mit Vektor. department_id und min_required_role sind absichtlich
-- aus documents kopiert: so braucht der Sicherheitsfilter in der heissen Abfrage
-- keinen JOIN. Der Trigger unten haelt die Kopie zwingend korrekt.
CREATE TABLE document_chunks (
    id                SERIAL PRIMARY KEY,
    document_id       INT         NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index       INT         NOT NULL,
    department_id     INT         REFERENCES departments(id) ON DELETE CASCADE,
    min_required_role VARCHAR(20) NOT NULL REFERENCES roles(name),
    content           TEXT        NOT NULL,
    embedding         VECTOR(1536),
    UNIQUE (document_id, chunk_index)
);

CREATE OR REPLACE FUNCTION kg_sync_chunk_classification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    SELECT d.department_id, d.min_required_role
      INTO NEW.department_id, NEW.min_required_role
      FROM documents d
     WHERE d.id = NEW.document_id;
    RETURN NEW;
END;
$$;

-- Ein Abschnitt kann seine Freigabestufe nicht selbst setzen; sie kommt immer
-- vom Dokument. Damit ist eine falsche Einstufung durch die Anwendung unmoeglich.
CREATE TRIGGER chunk_classification
    BEFORE INSERT OR UPDATE OF document_id, department_id, min_required_role
    ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION kg_sync_chunk_classification();

CREATE OR REPLACE FUNCTION kg_reclassify_document_chunks()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    UPDATE document_chunks
       SET department_id     = NEW.department_id,
           min_required_role = NEW.min_required_role
     WHERE document_id = NEW.id;
    RETURN NEW;
END;
$$;

-- Wird ein Dokument neu eingestuft, folgen alle Abschnitte sofort nach.
CREATE TRIGGER document_reclassification
    AFTER UPDATE OF department_id, min_required_role ON documents
    FOR EACH ROW EXECUTE FUNCTION kg_reclassify_document_chunks();

-- ---------------------------------------------------------------------------
-- Freigaben auf Antrag: befristet, dokumentbezogen, mit Entscheider.
-- ---------------------------------------------------------------------------
CREATE TABLE access_requests (
    id           SERIAL PRIMARY KEY,
    requester_id INT         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id  INT         NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    reason       TEXT        NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'approved', 'denied')),
    decided_by   INT         REFERENCES users(id),
    decided_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE access_grants (
    id          SERIAL PRIMARY KEY,
    user_id     INT         NOT NULL REFERENCES users(id)     ON DELETE CASCADE,
    document_id INT         NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    granted_by  INT         NOT NULL REFERENCES users(id),
    request_id  INT         REFERENCES access_requests(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (user_id, document_id)
);

-- ---------------------------------------------------------------------------
-- Zugriffsprotokoll. Haelt fest, was freigegeben und was gesperrt wurde --
-- ohne gesperrte Inhalte zu speichern.
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
    id                BIGSERIAL   PRIMARY KEY,
    at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id           INT         REFERENCES users(id) ON DELETE SET NULL,
    action            VARCHAR(60) NOT NULL,
    decision          VARCHAR(10) NOT NULL CHECK (decision IN ('allow', 'deny')),
    question          TEXT,
    allowed_chunk_ids INT[]       NOT NULL DEFAULT '{}',
    blocked_count     INT         NOT NULL DEFAULT 0,
    detail            JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX audit_log_user_at_idx ON audit_log (user_id, at DESC);
