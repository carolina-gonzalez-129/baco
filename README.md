# BACO — Servidor MCP y Fachada de Base de Conocimiento

BACO expone una fachada de dominio desacoplada (`baco/server/core/`) y un servidor **Model Context Protocol (MCP)** autónomo (`baco/server/mcp_server.py`) que se ejecuta por transporte **`stdio`** sin depender de FastAPI.

Incluye un entorno de demostración reproducible con **PostgreSQL 16 + `pgvector`**, esquema completo (`baco/server/db/schema_completo.sql`) y un dataset de **35 artículos 100 % sintéticos** (`baco/server/db/seed.sql`) con vectores de embeddings ONNX INT8 precalculados (`paraphrase-multilingual-MiniLM-L12-v2` de 384 dimensiones para títulos e `intfloat/multilingual-e5-base` de 768 dimensiones para textos).

---

## 1. Requisitos Previos

- **Docker** y **Docker Compose** (para levantar PostgreSQL con `pgvector` y/o ejecutar el contenedor MCP).
- **Python 3.12+** (si se ejecuta el servidor MCP directamente en el host).
- **Node.js 18+** (opcional, para probar interactivamente con `@modelcontextprotocol/inspector`).

---

## 2. Levantar el Entorno con Docker Compose

### Paso 1: Configurar el archivo `.env`

Copie el archivo de ejemplo `.env.example` a `.env` y defina las contraseñas locales:

```bash
cp .env.example .env
```

Variables requeridas en `.env`:

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=baco_db

# Usuario administrador (usado en la inicialización del contenedor)
DB_USER=postgres
DB_PASSWORD=changeme_admin_local

# Usuario de solo lectura (usado por el servidor MCP en tiempo de ejecución)
DB_RO_USER=baco_readonly
DB_RO_PASSWORD=changeme_readonly_local

ONNX_INTRA_OP_THREADS=2
```

### Paso 2: Iniciar PostgreSQL (`pgvector`) con esquema y seed sintético

```bash
docker compose up -d postgres
```

Al iniciar por primera vez, el contenedor ejecuta automáticamente [`docker/init-db.sh`](docker/init-db.sh), el cual:
1. Configura la contraseña del rol de solo lectura `baco_readonly` a partir de `DB_RO_PASSWORD` (`default_transaction_read_only = on`).
2. Aplica [`baco/server/db/schema_completo.sql`](baco/server/db/schema_completo.sql) (extensiones `unaccent`, `pg_trgm`, `vector`, tablas, índices HNSW y funciones del esquema `duplicados`).
3. Carga [`baco/server/db/seed.sql`](baco/server/db/seed.sql) con 35 artículos sintéticos y sus embeddings precalculados.

Para verificar que la base de datos está saludable:

```bash
docker compose ps
```

---

## 3. Ejecutar el Servidor MCP (`stdio`)

El servidor MCP (`baco/server/mcp_server.py`) tiene su propio ciclo de vida (`lifespan`): abre el pool de conexiones de solo lectura (`db_ro_pool`), precarga y calienta los modelos ONNX INT8 al iniciar, e inyecta la conexión en la fachada `baco.server.core`. Todos los logs se emiten por `stderr` para mantener `stdout` reservado exclusivamente al protocolo JSON-RPC.

### Opción A: Ejecución local con Python

```bash
python -m venv .venv
# En Linux/macOS:
source .venv/bin/activate
# En Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python -m baco.server.mcp_server
```

### Opción B: Ejecución en contenedor Docker (`docker run -i`)

El `Dockerfile` incluye los modelos ONNX INT8 precargados dentro de la imagen para un arranque inmediato en modo offline:

```bash
# Construir la imagen con los modelos ONNX incluidos
docker compose --profile mcp build mcp
# O directamente con docker build:
docker build -t baco-mcp:latest .

# Ejecutar por stdio conectándose al contenedor de PostgreSQL
docker run -i --rm \
  --network geminiagente_default \
  -e DB_HOST=baco-postgres \
  -e DB_PORT=5432 \
  -e DB_NAME=baco_db \
  -e DB_RO_USER=baco_readonly \
  -e DB_RO_PASSWORD=changeme_readonly_local \
  baco-mcp:latest
```

---

## 4. Ejemplo de Configuración para un Cliente MCP (JSON)

Puede conectar cualquier cliente compatible con MCP (Claude Desktop, Cursor, VS Code, etc.) agregando la siguiente configuración en su archivo `mcpServers`:

### Usando Python local

```json
{
  "mcpServers": {
    "baco": {
      "command": "python",
      "args": ["-m", "baco.server.mcp_server"],
      "env": {
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "baco_db",
        "DB_RO_USER": "baco_readonly",
        "DB_RO_PASSWORD": "changeme_readonly_local",
        "ONNX_INTRA_OP_THREADS": "2"
      }
    }
  }
}
```

### Usando Docker (`docker run -i`)

```json
{
  "mcpServers": {
    "baco-docker": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "--add-host=host.docker.internal:host-gateway",
        "-e", "DB_HOST=host.docker.internal",
        "-e", "DB_PORT=5432",
        "-e", "DB_NAME=baco_db",
        "-e", "DB_RO_USER=baco_readonly",
        "-e", "DB_RO_PASSWORD=changeme_readonly_local",
        "baco-mcp:latest"
      ]
    }
  }
}
```

---

## 5. Probar con MCP Inspector

Puede inspeccionar los schemas de entrada/salida y ejecutar llamadas de prueba desde el navegador utilizando el inspector oficial de MCP:

### Contra el entorno Python local

```bash
npx @modelcontextprotocol/inspector python -m baco.server.mcp_server
```

### Contra la imagen Docker

```bash
npx @modelcontextprotocol/inspector docker run -i --rm \
  --add-host=host.docker.internal:host-gateway \
  -e DB_HOST=host.docker.internal \
  -e DB_PORT=5432 \
  -e DB_NAME=baco_db \
  -e DB_RO_USER=baco_readonly \
  -e DB_RO_PASSWORD=changeme_readonly_local \
  baco-mcp:latest
```

Ejemplos de prueba sugeridos en el Inspector:

1. **`buscar_duplicados`**:
   - **Coincidencia exacta (`nivel: "exacto"`, `score: 1.0`)**:
     ```json
     {
       "titulo": "Cómo configurar un punto de venta electrónico en el módulo de facturación",
       "limite": 3
     }
     ```
   - **Coincidencia semántica (`nivel: "similar"`)**:
     ```json
     {
       "titulo": "Dar de alta nuevo punto de venta para factura electrónica",
       "texto": "# Consulta\nNecesito habilitar un punto de venta electrónico para emitir facturas por webservice.\n\n# Pasos a seguir\n1. Entrar a configuración de puntos de venta.\n2. Crear el código y asociar comprobantes.",
       "limite": 3
     }
     ```

2. **`validar_formato`**:
   ```json
   {
     "titulo": "Cómo configurar un punto de venta electrónico",
     "texto": "# Consulta\nCómo habilitar un punto de venta fiscal.\n\n# Pasos a seguir\n1. Ingresar a Configuración > Puntos de Venta.\n2. Asignar el número y guardar."
   }
   ```

---

## 6. Especificación de Tools Expuestas

| Tool | Modo | Parámetros | Cotas de Entrada | Salida (`Pydantic`) |
| :--- | :--- | :--- | :--- | :--- |
| `buscar_duplicados` | Solo lectura (`baco_readonly`) | `titulo: str`, `texto: str \| None = None`, `limite: int = 3` | `titulo`: 15–255 chars<br>`texto`: 20–6687 chars (si se envía)<br>`limite`: 1–10 | `BuscarDuplicadosToolOutput`: `encontrado` (`bool`), `nivel` (`"exacto"` \| `"similar"` \| `"ninguno"`), `mensaje` (`str`), `articulos` (`list[{id, titulo, url, metodo, score}]` — **nunca incluye texto del cuerpo**). |
| `validar_formato` | Puro / Sin efecto lateral | `titulo: str`, `texto: str` | `titulo`: 15–255 chars<br>`texto`: 20–6687 chars | `ValidarFormatoToolOutput`: `status` (`"Listo"` \| `"Listo con ajustes sugeridos"` \| `"Pendiente"`), `tipo_detectado`, `secciones_presentes`, `secciones_faltantes`, `alertas` (incluye sanitización de PII como CUITs y correos reales). |
