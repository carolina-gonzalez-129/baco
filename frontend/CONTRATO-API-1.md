# Contrato de API — BACO

Especificación técnica de la API REST del backend de BACO (`baco/server/app/api.py`). El backend es la **fuente de verdad única**.

- **Host por defecto (desarrollo):** `http://127.0.0.1:8080`
- **Prefijo base:** `/` (las rutas cuelgan directamente de la raíz, sin prefijo `/api/v1`)
- **Formato:** JSON, UTF-8

---

## Autenticación y Sesión

### Autenticación de seguridad
Todos los endpoints requieren autenticación mediante API Key (`baco/server/app/middleware.py`), salvo las excepciones listadas abajo:

- Cabecera: `X-API-Key: <API_KEY_SERVIDOR>` o `Authorization: Bearer <API_KEY_SERVIDOR>`
- Si la clave falta o no coincide con `API_KEY_SERVIDOR`, el servidor responde `401 Unauthorized` con `{"detail": "Unauthorized"}`.

**Excepciones:**

| Ruta / método | Autenticación |
|---|---|
| `GET /api/recursos-temp/...` | Ninguna (previsualización de recursos temporales) |
| Cualquier ruta con método `OPTIONS` | Ninguna (preflight CORS) |
| `/docs`, `/openapi.json`, `/redoc` | HTTP Basic Auth con `DOCS_USER` / `DOCS_PASSWORD` (no API Key) |

### Identificador de sesión FSM
El orquestador de BACO mantiene el estado de la máquina finita (FSM) por sesión.

**Emisión (solo en `POST /chat`):**

1. Cabecera HTTP `X-Session-ID` (expuesta vía CORS). El resto de los endpoints **no** la devuelve.
2. Cookie HTTP `baco_session`:
   - `httpOnly`, `path=/`
   - `max_age=TTL_SEGUNDOS` = **20400 s** (340 min; `baco/server/services/orquestador/sesion.py`)
   - Bajo HTTPS: `SameSite=None`, `Secure=true`. En HTTP local: `SameSite=Lax`, `Secure=false`.
   - Si el turno termina en estado `RECHAZADO`, la cookie se elimina (`delete_cookie`).

**Envío por el cliente:** capturar `X-Session-ID` de la respuesta de `POST /chat` y reenviarlo en la cabecera `X-Session-ID` en cada solicitud subsecuente (o confiar en la cookie).

**Campo `session_id` en el body (deprecado):**

| Endpoint | Comportamiento real |
|---|---|
| `POST /chat` | Se ignora: siempre se sobrescribe con el valor de cookie/cabecera. |
| `POST /chat/bloques` | **Tiene prioridad** sobre cookie/cabecera (`body.session_id or cookie/cabecera`). Enviarlo en `null` para que se use la cookie/cabecera. |
| Resto de endpoints | No se acepta en el body. |

---

## Formato de Errores

El backend utiliza el formato estándar de FastAPI / Starlette (`baco/server/app/exception_handlers.py`):

```json
{
  "detail": "Mensaje explicativo del error o lista de validaciones"
}
```

- **400 Bad Request:** Datos malformados o inconsistencia en la solicitud. Incluye archivos que superan `RECURSO_MAX_BYTES` o recursos que exceden `MAX_RECURSOS_TOTAL_BYTES` al subir.
- **401 Unauthorized:** API key ausente o inválida; o sesión no identificada cuando es requerida.
- **403 Forbidden:** Subida de recursos deshabilitada por configuración (`PERMITIR_SUBIDA_RECURSOS = False`) o acción restringida a ciertos modos (ver Contenido Adicional).
- **404 Not Found:** Sesión expirada/inexistente o recurso no encontrado.
- **409 Conflict:** Incoherencia de estado en la FSM (ej. intentar listar recursos antes de superar duplicados, o pedir borrador finalizado cuando el estado no es `FINALIZADO`).
- **422 Unprocessable Entity:** Falla de validación de esquema Pydantic (devuelve lista de objetos `{loc, msg, type}`, sin el campo `input`) o precondición de negocio no cumplida (ej. invocar skill con artículo que supera límite de caracteres o faltan categorías/etiquetas). Excesos de tamaño/cantidad detectados por el esquema de `POST /chat/bloques` también responden 422.

> El backend **no** usa `413 Payload Too Large`: los excesos de tamaño responden `400` o `422` según dónde se detecten.

---

## Límites del Sistema (`baco/server/config_limites.py`)

| Parámetro | Valor | Descripción |
|---|---|---|
| `TITULO_MIN` | 15 caracteres | Longitud mínima del título |
| `TITULO_MAX` | 255 caracteres | Longitud máxima del título |
| `TEXTO_MIN` | 20 caracteres | Longitud mínima del texto efectivo |
| `TEXTO_MAX` | 6687 caracteres | Límite máximo de caracteres de texto para invocar skills del agente |
| `TEXTO_MAX_PERCENTIL_99` | 16777 caracteres | Límite máximo de admisión de texto para el orquestador |
| `TAGS_MIN` | 2 | Mínimo de etiquetas para clasificar un artículo |
| `TAGS_MAX` | 5 | Máximo de etiquetas permitido |
| `TAGS_PLANTILLAS_PERMITIDAS` | `["instructivo", "soluciones"]` | Plantillas oficiales soportadas |
| `CATEGORIA_ID_DEFAULT` | 1 | Categoría asignada por defecto |
| `PERMITIR_SUBIDA_RECURSOS` | `true` | Si es `false`, `POST /chat/recursos` responde `403` |
| `RECURSO_MAX_BYTES` | 10 MB (10485760 B) | Tamaño máximo por archivo multimedia subido |
| `MAX_RECURSOS_TOTAL_BYTES` | 50 MB (52428800 B) | Tamaño máximo acumulado de recursos por borrador |
| `MAX_RECURSOS_POR_SESION` | 20 | Cantidad máxima de recursos multimedia por sesión |
| `MAX_BLOQUES_TEXTO` | 21 | Cantidad máxima de bloques de texto por borrador (`MAX_RECURSOS_POR_SESION + 1`) |
| `BUFFER_CARACTERES_PROMPT_XML` | 500 | Margen de caracteres reservado para el envoltorio XML del prompt (uso interno del back) |

---

<!-- ===================================================================== -->
<!-- PEGAR ACÁ el contenido de contrato_api.md (reemplaza L68–268 del viejo: -->
<!-- Estados del Flujo + Endpoints del Orquestador 1–3)                      -->
<!-- ===================================================================== -->

---

### 4. Gestión de Bloques y Recursos Multimedia

#### `POST /chat/bloques`
Recibe una secuencia de bloques ordenados de texto y recursos, deriva el texto limpio y asocia las posiciones de los recursos.

- **Request (`ConfirmarBloquesRequest`):**
  ```json
  {
    "session_id": null,
    "bloques": [
      { "tipo": "texto", "contenido": "Paso 1: Abrir la configuración" },
      { "tipo": "recurso", "recurso": { "id": "rec_1" } },
      { "tipo": "texto", "contenido": "Paso 2: Guardar los cambios" }
    ]
  }
  ```
  > `session_id` en el body tiene prioridad sobre cookie/cabecera en este endpoint (ver *Identificador de sesión FSM*). Enviarlo en `null`.
- **Response (`ConfirmarBloquesResponse`):**
  ```json
  {
    "session_id": "...",
    "bloques_texto": ["Paso 1: Abrir la configuración", "Paso 2: Guardar los cambios"],
    "texto_limpio": "Paso 1: Abrir la configuración\n\nPaso 2: Guardar los cambios",
    "recursos": [
      {
        "id": "rec_1",
        "tipo": "imagen",
        "nombre": "captura.png",
        "origen": "subido",
        "referencia": "/api/recursos-temp/.../captura.png",
        "posicion": 0,
        "orden": 0
      }
    ],
    "aviso": null,
    "borrador": { ... }
  }
  ```

#### `GET /chat/recursos`
Devuelve el estado consolidado de `bloques_texto` y `recursos` multimedia (`EstadoRecursosResponse`). Requiere haber superado la etapa de duplicados.

#### `POST /chat/recursos` (Subida de archivo)
Carga un archivo temporal en la sesión (`multipart/form-data`).
- **Form Data:**
  - `file`: Archivo binario (máx. 10 MB, no SVG).
  - `posicion` (opcional): Índice del bloque de texto tras el cual se inserta (-1 para el inicio).
  - `bloques_texto` (opcional): Lista JSON de cadenas con la partición actualizada de bloques de texto.
- **Response:** `EstadoRecursosResponse`

#### `POST /chat/recursos/agregar`
Inserta un recurso por URL externa (`http://` o `https://`).
- **Request (`AgregarRecursoRequest`):**
  ```json
  {
    "referencia": "https://servidor.com/imagen.png",
    "nombre": "Diagrama de flujo",
    "tipo": "imagen",
    "posicion": 1
  }
  ```
- **Response:** `EstadoRecursosResponse`

#### `DELETE /chat/recursos/{recurso_id}`
Elimina un recurso multimedia del borrador. Si dos bloques de texto quedan contiguos sin ningún otro recurso intermedio, aplica **fusión condicional** de bloques.
- **Response:** `EstadoRecursosResponse`

#### `PUT /chat/recursos/reordenar`
Reordena los recursos multimedia en el borrador mediante `from_index`/`to_index`, lista de `orden_ids` o lista de `orden_indices`.
- **Response:** `EstadoRecursosResponse`

#### `GET /api/recursos-temp/{session_id}/{archivo}`
Sirve la previsualización del archivo temporal para el navegador (no requiere cabecera de autenticación).

---

### 5. Contenido Adicional (Flujos Actualizar / Enriquecer)

Endpoints para gestionar ítems de contenido adicional independientes del cuerpo principal:

- `GET /chat/contenido-adicional` → `ItemContenidoAdicional[]`
- `POST /chat/contenido-adicional` → Body: `{ "contenido": "...", "tipo": "texto" }`
- `DELETE /chat/contenido-adicional/{item_id}` → `{ "status": "ok", "eliminado": "..." }`
- `PUT /chat/contenido-adicional/reordenar` → Body: `{ "orden_ids": ["item_2", "item_1"] }`
- `PUT /chat/contenido-adicional/{item_id}` o `PATCH` → Body: `{ "contenido": "...", "tipo": "texto" }`

**Restricciones de `POST /chat/contenido-adicional`:**
- `409 Conflict` si la sesión está en `FINALIZADO`.
- `400 Bad Request` si no hay borrador.
- `403 Forbidden` si el borrador no está en modo `enriquecimiento` o `actualizar` y no tiene artículo base (`articulo_original_id` es `null`), es decir, en modo `nuevo`.

