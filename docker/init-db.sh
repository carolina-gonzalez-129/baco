#!/usr/bin/env bash
set -euo pipefail

if [ -z "${DB_RO_PASSWORD:-}" ]; then
  echo "[BACO init-db] ERROR: La variable de entorno DB_RO_PASSWORD es requerida para crear el rol baco_readonly." >&2
  exit 1
fi

echo "[BACO init-db] Aplicando schema_completo.sql y cargando seed.sql sintético..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ro_password="$DB_RO_PASSWORD" <<'EOSQL'
SELECT set_config('baco.ro_password', :'ro_password', false);
\i /opt/baco/db/schema_completo.sql
\i /opt/baco/db/seed.sql
EOSQL

echo "[BACO init-db] Base de datos inicializada correctamente."
