# Baco

Asistente para la carga de artículos en la Base de Conocimiento (Discourse). El usuario redacta el artículo en un chat guiado. El backend:

- detecta duplicados por búsqueda léxica y semántica (embeddings ONNX + pgvector),
- valida formato, longitud y datos personales (PII),
- reestructura y audita el borrador con skills de un LLM (`plantillas` y `validador`),
- gestiona el contenido adicional al actualizar o enriquecer un artículo existente.

El proyecto tiene tres partes:

- **Backend**: FastAPI + PostgreSQL, en `baco/server`.
- **Front**: estático, en `frontend/`.
- **Scripts de sincronización** con Discourse.

## Cómo funciona

### Un asistente no conversacional

Baco no es un chatbot de diálogo libre. El chat es la interfaz, pero el flujo lo conduce una máquina de estados extendida del lado del servidor (`baco/server/services/orquestador/`, endpoint `POST /chat`). El front solo envía eventos y renderiza lo que devuelve el servidor. El LLM no decide el próximo paso ni conversa con la persona: se lo invoca en puntos acotados del flujo, con una entrada ya validada y una tarea cerrada.

```
título → duplicados (título, luego texto) → tipo de plantilla → skills e imágenes
→ edición → validaciones (tipo y metadatos) → edición → finalizar
```

La anonimización de PII se aplica en todo el flujo, y desde cualquier paso se puede volver al anterior.

### Pipeline determinista previo al LLM

Las decisiones críticas se resuelven sin el modelo:

1. **Deduplicación en capas**, de la más barata a la más cara, que prioriza actualizar o enriquecer un artículo existente antes que crear uno nuevo.
2. **Validaciones**: longitud de título y texto, cantidad de etiquetas (`GET /limites`) y reglas de estilo del título.
3. Recién después, **el LLM con skills**, que recibe como contexto el resultado del pipeline.

La **anonimización de PII**, que es autosanitizante, no es un paso más: se aplica en todo el flujo. Cubre documentos de identidad, mails, datos financieros, tokens y llaves de API.

Discourse es la fuente de verdad. La base PostgreSQL es una copia derivada y reconstruible (ver [sección 8](#8-actualización-periódica-desde-discourse)).

### Búsqueda de duplicados e índices

| Capa | Técnica | Índice |
| :--- | :--- | :--- |
| Título exacto | `md5(normalizar_texto(titulo))`, columna generada | B-tree |
| Series | Igualdad por `base_titulo` (título sin números de serie, meses, años, etc.); solo entran títulos con `titulo_normalizado <> base_titulo` | B-tree |
| Título parcial | Similitud de trigramas (`pg_trgm`) sobre `titulo_normalizado` | GIN |
| Texto exacto | Hash del texto normalizado, con y sin headers de plantilla | B-tree |
| Texto semántico | Embeddings ONNX de título y texto (ver [sección 11](#11-modelos-de-embeddings)) | HNSW (pgvector) |

La base se organiza en dos schemas:

- `public`: tablas y UDF que calculan los campos derivados. Incluye la normalización (`normalizar_texto`, IMMUTABLE, con `unaccent`), `base_titulo`, los trigramas y los embeddings (con un modelo de Python). Así la ingesta y la búsqueda usan el mismo cálculo.
- `duplicados`: la lógica de detección que usa el servidor, construida sobre las funciones de `public`.

**Semánticas de exclusión.** Para reducir falsos positivos, algunos candidatos se descartan antes de puntuar:

- Los embeddings se comparan sin los headers de plantilla (`limpiar_headers`), para que la estructura compartida no infle la similitud.
- La búsqueda semántica por texto solo corre a partir de 400 caracteres, porque los textos cortos (por ejemplo, las series periódicas) dan cosenos altos sin ser duplicados.
- Se descartan los pares que difieren en entidades discriminantes, como el país o el organismo impositivo. Dos artículos casi iguales que refieren a distintas jurisdicciones no son duplicados.
- Se usa un `k` reducido, umbrales calibrados y un puntaje combinado de texto y título.

### LLM

- **Rol**: agente acotado dentro de un flujo determinista. Es la capa cognitiva y no detecta duplicados ni PII.
- **Proveedor**: API compatible con OpenAI (`LLM_BASE_URL`, `LLM_MODEL_ID`). Por defecto, OpenRouter.
- **Skills** (`SKILL.md` + `references/`):
  - `plantillas` (`POST /chat/aplicar-plantilla`): reestructura el borrador como `instructivo` o `soluciones`, tomando como referencia las plantillas de la Base de Conocimiento.
  - `validador` (`POST /chat/auditar-semantica`): audita el borrador contra las pautas de redacción y devuelve `texto_corregido`.
- **Control posterior**: el resultado vuelve al pipeline determinista (`POST /chat/revalidar-post-skill`) y se muestra en Vista previa. El original se conserva en el Editor y la persona decide si lo usa.

---

## Índice

1. [Requisitos](#1-requisitos)
2. [Instalación](#2-instalación)
3. [Variables de entorno](#3-variables-de-entorno)
4. [Base de datos](#4-base-de-datos)
5. [Servidor](#5-servidor)
6. [Front](#6-front)
7. [Docker](#7-docker)
8. [Actualización periódica desde Discourse](#8-actualización-periódica-desde-discourse)
9. [Tests](#9-tests)
10. [Endpoints](#10-endpoints)
11. [Modelos de embeddings](#11-modelos-de-embeddings)

---

## 1. Requisitos

| Componente | Detalle |
| :--- | :--- |
| Python | `>= 3.10` |
| PostgreSQL | Probado con PostgreSQL 16 (imagen `pgvector/pgvector:pg16`). Extensiones necesarias: `unaccent`, `pg_trgm` y `vector` (pgvector). |
| Proveedor LLM | API compatible con OpenAI. Por defecto, OpenRouter. Lo usan las skills `plantillas` y `validador`. |
| Discourse | API key de la instancia (`DISCOURSE_URL`). Se usa para la descarga inicial y la sincronización. |
| Hugging Face Hub | Acceso a internet en la primera ejecución, para descargar los modelos ONNX. |
| Docker | Opcional. Para levantar todo con Docker Compose (ver [sección 7](#7-docker)) y para los tests de integración (`testcontainers`). |
| Node.js | Opcional. Lo usan los tests de frontend. |
| Windows Task Scheduler | Opcional. Lo usa la actualización periódica. |

---

## 2. Instalación

```powershell
git clone https://github.com/carolina-gonzalez-129/baco.git
cd baco
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # completar los valores (ver sección 3)
```

Las dependencias se declaran en `pyproject.toml`. `requirements.txt` contiene solo `-e .[test]`: instala el paquete `baco` en modo editable junto con las dependencias de test (`pytest`, `respx`, `testcontainers`). Para instalar solo las dependencias de ejecución: `pip install .`.

> `sentence-transformers` requiere PyTorch aunque los embeddings se calculen con ONNX. En Windows, pip instala la versión para CPU. En Linux instala por defecto la versión con CUDA (varios GB). Para evitarlo, instalar antes `pip install torch --index-url https://download.pytorch.org/whl/cpu`.

> Los scripts de actualización programada esperan el entorno virtual en `.venv\Scripts\python.exe`.

---

## 3. Variables de entorno

Se leen de `.env`. La plantilla está en `.env.example`.

### Obligatorias (sin estas el servidor no arranca)

| Variable | Uso |
| :--- | :--- |
| `API_KEY_SERVIDOR` | API key que valida el header `X-API-Key` (o `Authorization: Bearer`). Debe coincidir con `API_KEY` en `frontend/js/config.js`. |
| `DOCS_USER` / `DOCS_PASSWORD` | Credenciales de HTTP Basic Auth para `/docs`, `/redoc` y `/openapi.json`. |
| `DB_RO_USER` | Rol de solo lectura que usa el servidor. **Debe valer `baco_readonly`**. |
| `DB_RO_PASSWORD` | Contraseña de `baco_readonly`. La toma `reconstruir_db` al crear el rol. |

### Obligatorias según el flujo (fallan al usarse si faltan)

| Variable | Uso |
| :--- | :--- |
| `OPEN_ROUTER_API_KEY` | API key del proveedor LLM. Sin ella fallan las skills. |
| `DISCOURSE_URL` | URL de la instancia de Discourse que se usa para descargar y sincronizar. |
| `DISCOURSE_API_KEY` / `DISCOURSE_API_USERNAME` | Credenciales de la API de Discourse. Las exigen los scripts de sincronización. |

### Con valor por defecto

| Variable | Default | Uso |
| :--- | :--- | :--- |
| `DB_HOST` | `localhost` | Host de PostgreSQL. |
| `DB_PORT` | `5432` | Puerto de PostgreSQL. |
| `DB_NAME` | `baco_db` | Nombre de la base. |
| `DB_USER` | `postgres` | Rol de escritura y administración (dueño del schema `duplicados`). |
| `DB_PASSWORD` | sin valor | Contraseña de `DB_USER`. Si está vacía, se omite en el DSN. |
| `BACO_TEXTO_MAX` | `6687` | Largo máximo recomendado del texto. |
| `BACO_CACHE_SKILLS` | `1` | Cache de skills. Con `0` se deshabilita. |
| `ONNX_INTRA_OP_THREADS` | `2` | Hilos de ONNX Runtime. |
| `CORS_ORIGINS` | `localhost` / `127.0.0.1` en los puertos 3000 y 5173 | Orígenes CORS, separados por coma. |
| `CORS_ORIGIN_REGEX` | sin valor | Regex de orígenes CORS. |
| `DATA_DIR` | `<repo>/data` | Directorio de datos. |
| `RUTA_ARTICULOS_JSON` | `DATA_DIR/articulos.json` | JSON de artículos para la carga inicial. |
| `LLM_MODEL_ID` | `openrouter/free` | Modelo LLM. |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | Endpoint del proveedor LLM. |
| `DISCOURSE_PUBLIC_URL` | `https://bc.finneg.com` | Instancia pública. Se consulta al enriquecer un artículo existente. |

Las variables que se usan solo en tests están en la [sección 9](#9-tests).

---

## 4. Base de datos

### Puesta en marcha

1. Crear la base vacía:

   ```powershell
   psql -U postgres -c "CREATE DATABASE baco_db;"
   ```

2. Aplicar el schema, cargar los artículos y generar los embeddings con un solo comando:

   ```powershell
   python -m baco.server.db.reconstruir_db --cargar-json --con-embeddings
   ```

   Este comando:
   - aplica `schema_completo.sql` (extensiones, tablas, índices, rol `baco_readonly` y schema `duplicados`),
   - carga `data/articulos.json` (incluido en el repo),
   - calcula los embeddings,
   - audita la base.

> ⚠️ No ejecutes `schema_completo.sql` directamente con `psql`: falla al crear `baco_readonly`, porque necesita `DB_RO_PASSWORD`. `reconstruir_db` la inyecta en la sesión.
>
> Sin flags, `reconstruir_db` solo reaplica el schema y audita. No carga artículos ni genera embeddings.

### Variantes de `reconstruir_db`

| Flags | Efecto |
| :--- | :--- |
| `--cargar-json` | Carga `data/articulos.json`. |
| `--desde-api --con-embeddings` | Descarga primero los artículos desde Discourse y después carga y genera embeddings. |
| `--reset --forzar --con-embeddings` | **Destructivo**: hace `DROP SCHEMA public CASCADE` y reconstruye todo desde cero. |
| `--con-embeddings` | Calcula los embeddings de título y texto que falten o estén desactualizados. |
| `--todo-embeddings` | Recalcula todos los embeddings, incluso los ya calculados. |

### Alternativa paso a paso

```powershell
# 1. (Opcional) Descargar los artículos de Discourse a data/articulos.json
python -m baco.server.discourse.descargar_articulos

# 2. Aplicar el schema y cargar el JSON
python -m baco.server.db.reconstruir_db --cargar-json

# 3. Generar los embeddings que falten o estén desactualizados
python -m baco.server.db.generar_embeddings
```

### Archivos de `baco/server/db` y `baco/server/discourse`

| Archivo | Rol |
| :--- | :--- |
| `discourse/descargar_articulos.py` | Descarga temas y artículos de Discourse a `data/articulos.json`. |
| `db/schema_completo.sql` | Schema completo. **Ya incluye** el contenido de `duplicados_schema.sql`. |
| `db/duplicados_schema.sql` | Schema `duplicados` con las funciones de búsqueda de duplicados. No hace falta correrlo por separado. |
| `db/ingesta.py` | Librería de normalización y upsert. No se ejecuta directamente. |
| `db/reconstruir_db.py` | Orquestador de la puesta en marcha. |
| `db/generar_embeddings.py` | Valida los modelos contra `embeddings_meta` y calcula, en lotes, los embeddings faltantes o desactualizados. |

---

## 5. Servidor

```powershell
uvicorn baco.server.app.main:app --host 0.0.0.0 --port 8080
```

Al iniciar, `lifespan.py` hace lo siguiente:

1. Abre el pool de conexiones de solo lectura (`baco_readonly`).
2. Precarga en memoria los catálogos de categorías y etiquetas. Si la carga falla, sigue sin ellos.
3. Carga los dos modelos ONNX y ejecuta una inferencia de calentamiento en cada uno.
4. Al apagarse, cierra el pool.

La documentación OpenAPI queda en `http://localhost:8080/docs`. Pide usuario y contraseña (`DOCS_USER` / `DOCS_PASSWORD`).

> La primera vez, el arranque tarda más porque descarga los modelos de Hugging Face Hub.

---

## 6. Front

```powershell
cd frontend
python -m http.server 5173
```

Abrir `http://localhost:5173`.

Configuración en `frontend/js/config.js`:

| Clave | Valor actual | Descripción |
| :--- | :--- | :--- |
| `MODO` | `'http'` | `'http'` llama al backend real. `'mock'` simula las respuestas en el navegador (ver nota). |
| `BASE_URL` | `'http://127.0.0.1:8080'` | URL del backend. |
| `API_KEY` | — | Debe coincidir con `API_KEY_SERVIDOR` del `.env`. |
| `MIN_TITULO`, `MAX_TITULO`, `MIN_TEXTO`, `MAX_TEXTO`, `MAX_TEXTO_PERCENTIL_99`, `MIN_TAGS`, `MAX_TAGS` | valores de respaldo | En modo `'http'` se reemplazan al iniciar con la respuesta de `GET /limites`. |

> ⚠️ El modo `'mock'` está desactualizado: le falta el objeto `mock` en `config.js` y usa estados viejos del flujo. Usar `'http'`.

---

## 7. Docker

Con Docker Desktop abierto y el `.env` completo:

```bash
docker compose up --build   # o ./baco.sh desde Git Bash (chequea Docker, el .env y la API key antes)
```

Levanta PostgreSQL con pgvector, carga la base, y expone el front en `http://localhost:5173` y la API en `http://localhost:8080/docs`.

Paso a paso: [docs/GUIA-DOCKER.md](docs/GUIA-DOCKER.md). Variables, front y comandos de `baco.sh`: [docs/CONFIGURACION.md](docs/CONFIGURACION.md).

---

## 8. Actualización periódica desde Discourse

Corre en Windows, con el Programador de Tareas.

### Registrar las tareas

```powershell
powershell -ExecutionPolicy Bypass -File scripts\configurar_scheduler.ps1
```

| Tarea | Cuándo corre | Modo |
| :--- | :--- | :--- |
| `Baco_Discourse_Actualizacion_Diaria` | Lunes a viernes, 10:00 | Incremental |
| `Baco_Discourse_Actualizacion_Semanal` | Sábados, 10:00 | Completo, con purga (`-Completo`) |

Para ver el estado de las tareas: `scripts\configurar_scheduler.ps1 -Consultar`.

> `-Desinstalar` está declarado pero no implementado. Para quitar las tareas, usar `Unregister-ScheduledTask`.

### Ejecución manual

```powershell
scripts\ejecutar_actualizacion.ps1              # incremental
scripts\ejecutar_actualizacion.ps1 -Completo    # completo con purga
scripts\ejecutar_actualizacion.ps1 -Reintento   # no corre si ya hubo un éxito hoy
```

El script ejecuta estos tres pasos en orden y registra todo en `logs\actualizar_articulos.log`:

1. `baco.server.discourse.actualizar_nuevos_articulos`
2. `baco.server.discourse.actualizar_articulos_editados`
3. `baco.server.db.generar_embeddings`

Códigos de salida de los pasos 1 y 2:

- `1`: fallos parciales. Registra una advertencia y sigue.
- `>= 2`: aborta.

Si termina bien, guarda la fecha en `.last_success_diario` o `.last_success_semanal`.

---

## 9. Tests

```powershell
pytest                       # suite completa
pytest -m "not slow"         # sin los tests lentos de paridad ONNX
pytest -m slow               # solo paridad ONNX (descarga PyTorch + ONNX)
pytest -m integration        # solo integración
pytest -m "not integration"  # sin integración
```

Para los tests de base de datos se usa Docker (`testcontainers`, imagen `pgvector/pgvector:pg16`). Si Docker no está disponible, los tests usan un PostgreSQL local con la base `baco_test_db`.

Variables que habilitan tests que, si no, se saltan:

| Variable | Habilita |
| :--- | :--- |
| `BACO_TEST_DATABASE_URL` | Test de `normalizar_texto` contra PostgreSQL (DSN de conexión). |
| `RUN_ONNX_INTEGRATION=1` | Test que carga los modelos ONNX reales. |
| `PAUSA_DOCKER` | Pausa en segundos de los tests de Docker. Default: `45`. |

Los tests de frontend se saltan si `node` no está en el `PATH`.

---

## 10. Endpoints

Contrato completo: [frontend/CONTRATO-API.md](frontend/CONTRATO-API.md). Documentación OpenAPI en `http://localhost:8080/docs` (pide `DOCS_USER` / `DOCS_PASSWORD`).

Todos requieren el header `X-API-Key` (o `Authorization: Bearer`).

| Método | Ruta | Propósito |
| :--- | :--- | :--- |
| `POST` | `/chat` | Procesa un turno del chat en la máquina de estados del orquestador. |
| `GET` | `/chat/borrador` | Devuelve el borrador final. Solo en estado `FINALIZADO`. |
| `POST` | `/chat/aplicar-plantilla` | Skill `plantillas`: reestructura el borrador como `instructivo` o `soluciones`. |
| `POST` | `/chat/auditar-semantica` | Skill `validador`: auditoría semántica y editorial, con `texto_corregido`. |
| `POST` | `/chat/revalidar-post-skill` | Revalida formato, longitud y PII después de aplicar una skill. |
| `GET` | `/chat/contenido-adicional` | Lista los ítems de contenido adicional. |
| `POST` | `/chat/contenido-adicional` | Agrega un ítem. Solo al actualizar o enriquecer un artículo existente. |
| `PUT` / `PATCH` | `/chat/contenido-adicional/{item_id}` | Modifica un ítem. |
| `PUT` | `/chat/contenido-adicional/reordenar` | Reordena los ítems. |
| `DELETE` | `/chat/contenido-adicional/{item_id}` | Elimina un ítem. |
| `GET` | `/limites` | Devuelve los límites vigentes de título, texto y etiquetas. |

---

## 11. Modelos de embeddings

| Uso | Modelo | Dimensión | Archivo ONNX |
| :--- | :--- | :--- | :--- |
| Título | `paraphrase-multilingual-MiniLM-L12-v2` | 384 | `onnx/model_quint8_avx2.onnx` |
| Texto | `intfloat/multilingual-e5-base` | 768 | `onnx/model_qint8_avx512_vnni.onnx` |

- Para el texto, el sistema lo trunca a 1000 caracteres (respetando los límites de palabra) y le antepone `"query: "`.
- `sentence-transformers` descarga los modelos (backend ONNX, `CPUExecutionProvider`) a la caché estándar de Hugging Face. No hay una ruta local propia para los `.onnx`.
- Los nombres y las dimensiones se registran en la tabla `embeddings_meta`. `generar_embeddings` los valida contra esa tabla.
