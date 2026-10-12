#!/bin/bash
# Runs first on the database container's first start and creates the application role.
# The role deliberately owns no tables; only then does row-level security apply to it.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
    CREATE ROLE ${KG_APP_USER} LOGIN PASSWORD '${KG_APP_PASSWORD}'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${KG_APP_USER};
EOSQL
