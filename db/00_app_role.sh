#!/bin/bash
# Laeuft als erstes beim ersten Start des Datenbank-Containers.
# Erzeugt die Anwendungsrolle. Sie ist absichtlich NICHT Eigentuemerin der
# Tabellen -- nur dadurch greifen die Zeilen-Rechte ueberhaupt.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
    CREATE ROLE ${KG_APP_USER} LOGIN PASSWORD '${KG_APP_PASSWORD}'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${KG_APP_USER};
EOSQL
