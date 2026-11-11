# Manual de configuración

Toda la configuración del back está en el archivo `.env` de la raíz del repo. `.env.example` tiene todas las variables comentadas: copialo a `.env` y completalo. No uses rutas absolutas de tu máquina.

## 1) Variables del .env

### Obligatorias (sin estas el servidor no arranca)

| Variable | Para qué |
|---|---|
| `API_KEY_SERVIDOR` | Key de la API (header `X-API-Key` o `Authorization: Bearer`). Tiene que coincidir con `API_KEY` del front. |
| `DOCS_USER`, `DOCS_PASSWORD` | Usuario y contraseña de `/docs`, `/openapi.json` y `/redoc`. |
| `DB_RO_USER`, `DB_RO_PASSWORD` | Usuario de solo lectura de PostgreSQL que usa el chat. `DB_RO_USER` tiene que ser `baco_readonly` (el nombre está fijo en el SQL). El rol lo crea la reconstrucción de la base con esta contraseña. |

### Obligatorias según el flujo (fallan al usarse si faltan)

| Variable | Para qué |
|---|---|
| `DB_USER`, `DB_PASSWORD` | Usuario de escritura de PostgreSQL (reconstrucción, ingesta, embeddings). En Docker el usuario es `postgres`; solo se define `DB_PASSWORD`. |
| `OPEN_ROUTER_API_KEY` | Modelo del agente (skills de plantillas y validador) vía OpenRouter. |
| `DISCOURSE_URL`, `DISCOURSE_API_KEY`, `DISCOURSE_API_USERNAME` | Solo para descargar artículos desde Discourse (`desde-api`). |

### Con default (no hace falta tocarlas)

| Variable | Default | Para qué |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME` | `localhost`, `5432`, `baco_db` | Conexión a la base. En Docker el compose fija host y puerto. |
| `BACO_TEXTO_MAX` | `6687` | Cantidad máxima de caracteres del texto para usar las skills (plantillas / validador). |
| `BACO_CACHE_SKILLS` | `1` | Caché en disco de respuestas de las skills (`data/cache_skills.json`). Útil para pruebas: evita volver a llamar al modelo con el mismo texto. `0` la desactiva. |
| `ONNX_INTRA_OP_THREADS` | `2` | Hilos para calcular embeddings. |

Si una variable numérica queda definida vacía (`VAR=`) rompe: comentala en vez de vaciarla.

### Opcionales

`CORS_ORIGINS`, `CORS_ORIGIN_REGEX`, `DATA_DIR`, `RUTA_ARTICULOS_JSON`, `LLM_MODEL_ID`, `LLM_BASE_URL`, `DISCOURSE_PUBLIC_URL`: ver la explicación de cada una en `.env.example`.

## 2) Front

En `frontend/js/config.js`:

- `BASE_URL`: dirección del back (por defecto `http://127.0.0.1:8080`).
- `API_KEY`: tiene que ser igual a `API_KEY_SERVIDOR` del .env; si no, todo da 401.

En Docker este archivo se lee directo del repo: cambiarlo no requiere reconstruir la imagen (alcanza con recargar el navegador).

## 3) Límites

El tope de caracteres para las skills se configura con `BACO_TEXTO_MAX` (ver arriba). El front toma los límites directamente del back, así que no hay que tocar nada en el front.

## 4) baco.sh y la base

Desde Git Bash, en la raíz del repo:

| Comando | Qué hace |
|---|---|
| `./baco.sh` | Chequea Docker, el .env y la API key, y levanta todo (`docker compose up --build`). |
| `./baco.sh down` | Detiene los contenedores. La base se conserva. |
| `./baco.sh logs` | Muestra los logs de la app. |
| `./baco.sh reset-db` | Borra y reconstruye la base desde cero con `data/articulos.json`, con embeddings. |
| `./baco.sh desde-api` | Descarga los artículos de Discourse y los carga (requiere las variables `DISCOURSE_*`). |

Cada vez que se levanta, la base se actualiza sola: aplica el esquema, carga `data/articulos.json` y calcula solo los embeddings que falten (la primera vez calcula todos y tarda).

Sin el script, los equivalentes son:

```bash
docker compose run --rm rebuild python -m baco.server.db.reconstruir_db --reset --forzar --con-embeddings
docker compose run --rm rebuild python -m baco.server.db.reconstruir_db --desde-api --con-embeddings
```
