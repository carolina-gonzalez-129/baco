#!/usr/bin/env bash
# Baco: atajos sobre docker compose. Uso: ./baco.sh [comando]
#   up         (default) chequea .env y levanta todo con --build
#   down       detiene los contenedores (la base se conserva)
#   logs       sigue los logs de la app
#   reset-db   reconstruye la base desde cero con data/articulos.json
#   desde-api  descarga los artículos de Discourse y los carga
# En Windows: correrlo desde Git Bash con Docker Desktop abierto.
set -euo pipefail
cd "$(dirname "$0")"

chequear() {
  command -v docker >/dev/null || { echo "ERROR: falta docker en el PATH"; exit 1; }
  docker info >/dev/null 2>&1 || { echo "ERROR: Docker no está corriendo (¿Docker Desktop abierto?)"; exit 1; }
  [ -f .env ] || { echo "ERROR: falta .env en $(pwd) (copiá el que te enviaron o partí de .env.example)"; exit 1; }
  local faltan=()
  for v in API_KEY_SERVIDOR DOCS_USER DOCS_PASSWORD DB_PASSWORD DB_RO_USER DB_RO_PASSWORD OPEN_ROUTER_API_KEY; do
    grep -qE "^${v}[[:space:]]*=[[:space:]]*[^[:space:]]" .env || faltan+=("$v")
  done
  [ ${#faltan[@]} -eq 0 ] || { echo "ERROR: faltan en .env: ${faltan[*]}"; exit 1; }
  [ -f data/articulos.json ] || { echo "ERROR: falta data/articulos.json"; exit 1; }
  local key_env key_front
  key_env=$(grep -E '^API_KEY_SERVIDOR[[:space:]]*=' .env | head -1 | cut -d= -f2- | tr -d '\r"'"'" | xargs)
  key_front=$(grep -E "^\s*API_KEY:" frontend/js/config.js | sed -E "s/.*API_KEY:\s*['\"]([^'\"]*)['\"].*/\1/")
  if [ "$key_env" != "$key_front" ]; then
    echo "AVISO: API_KEY_SERVIDOR del .env no coincide con API_KEY de frontend/js/config.js: el front va a dar 401"
  fi
}

case "${1:-up}" in
  up)
    chequear
    echo "Levantando Baco. La primera vez tarda (embeddings). Listo cuando aparezca: Uvicorn running on http://0.0.0.0:8080"
    echo "Front: http://localhost:5173 | API: http://localhost:8080/docs"
    docker compose up --build ;;
  down)      docker compose down ;;
  logs)      docker compose logs -f app ;;
  reset-db)  chequear; docker compose run --rm rebuild python -m baco.server.db.reconstruir_db --reset --forzar --con-embeddings ;;
  desde-api)
    chequear
    for v in DISCOURSE_URL DISCOURSE_API_KEY DISCOURSE_API_USERNAME; do
      grep -qE "^${v}[[:space:]]*=[[:space:]]*[^[:space:]]" .env || { echo "ERROR: falta $v en .env (requerida para desde-api)"; exit 1; }
    done
    docker compose run --rm rebuild python -m baco.server.db.reconstruir_db --desde-api --con-embeddings ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
