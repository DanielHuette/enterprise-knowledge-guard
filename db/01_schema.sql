-- Enterprise Knowledge Guard: schema
-- Runs as the owner role (kg_owner). The service later connects as kg_app, which owns
-- no table and is therefore subject to the row-level security in 02_security.sql.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Roles as data, not code: a new level is an INSERT, not a deployment.
-- ---------------------------------------------------------------------------
CREATE TABLE roles (
    name  VARCHAR(20) PRIMARY KEY,
    rank  SMALLINT    NOT NULL UNIQUE,
    label TEXT        NOT NULL
);

INSERT INTO roles (name, rank, label) VALUES
    ('Intern',   10, 'Intern'),
    ('Employee', 20, 'Employee'),
    ('Manager',  30, 'Manager'),
    ('Admin',    40, 'Management and administration');

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

-- A document is a source with one classification; department_id IS NULL means
-- company-wide.
CREATE TABLE documents (
    id                SERIAL PRIMARY KEY,
    title             TEXT        NOT NULL,
    source            TEXT        NOT NULL DEFAULT 'seed',
    department_id     INT         REFERENCES departments(id) ON DELETE CASCADE,
    min_required_role VARCHAR(20) NOT NULL REFERENCES roles(name),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Text chunk with its vector. department_id and min_required_role are copied from
-- documents on purpose, so the security filter in the hot query needs no JOIN. The
-- triggers below keep the copy correct.
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

-- A chunk cannot set its own classification; it always comes from its document.
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

-- When a document is reclassified, all its chunks follow immediately.
CREATE TRIGGER document_reclassification
    AFTER UPDATE OF department_id, min_required_role ON documents
    FOR EACH ROW EXECUTE FUNCTION kg_reclassify_document_chunks();

-- ---------------------------------------------------------------------------
-- Access on request: time-limited, per document, with the deciding manager.
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
-- Audit log: what was released and what was blocked, without storing blocked
-- content.
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
