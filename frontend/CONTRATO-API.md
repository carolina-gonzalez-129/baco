# Contrato de API — BACO

Especificación técnica de la API REST del backend de BACO (`baco/server/app/api.py`). El backend es la **fuente de verdad única**.

- **Host por defecto (desarrollo):** `http://127.0.0.1:8080`
- **Prefijo base:** `/` (las rutas cuelgan directamente de la raíz, sin prefijo `/api/v1`)
- **Formato:** JSON, UTF-8

---

## Autenticación y Sesión

### Autenticación de seguridad
Todos los endpoints (excepto la previsualización de recursos temporales en `/api/recursos-temp/...`) requieren autenticación mediante API Key (`baco/server/app/middleware.py`):

- Cabecera: `X-API-Key: <API_KEY_SERVIDOR>` o `Authorization: Bearer <API_KEY_SERVIDOR>`
- Si la clave falta o no coincide con `API_KEY_SERVIDOR`, el servidor responde `401 Unauthorized`.

### Identificador de sesión FSM
El orquestador de BACO mantiene el estado de la máquina finita (FSM) por sesión:

- El servidor emite y gestiona el ID de sesión mediante:
  1. Cabecera HTTP expuesta: `X-Session-ID`
  2. Cookie HTTP: `baco_session` (`httpOnly`, `path=/`, `max_age=3600`)
- El cliente debe capturar el valor de `X-Session-ID` recibido en la respuesta y reenviarlo en la cabecera `X-Session-ID` en cada solicitud subsecuente.
- El campo `session_id` en el cuerpo de los requests JSON está deprecado; el backend prioriza la cookie o la cabecera `X-Session-ID`.

---

## Formato de Errores

El backend utiliza el formato estándar de FastAPI / Starlette (`baco/server/app/exception_handlers.py`):

```json
{
  "detail": "Mensaje explicativo del error o lista de validaciones"
}
```

- **400 Bad Request:** Datos malformados o inconsistencia en la solicitud.
- **401 Unauthorized:** API key ausente o inválida; o sesión no identificada cuando es requerida.
- **403 Forbidden:** Subida de recursos deshabilitada por configuración (`PERMITIR_SUBIDA_RECURSOS = False`) o acción restringida a ciertos modos.
- **404 Not Found:** Sesión expirada/inexistente o recurso no encontrado.
- **409 Conflict:** Incoherencia de estado en la FSM (ej. intentar listar recursos antes de superar duplicados, o pedir borrador finalizado cuando el estado no es `FINALIZADO`).
- **422 Unprocessable Entity:** Falla de validación de esquema Pydantic (devuelve lista de objetos `{loc, msg, type}`) o precondición de negocio no cumplida (ej. invocar skill con artículo que supera límite de caracteres o faltan categorías/etiquetas).

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
| `RECURSO_MAX_BYTES` | 10 MB (10485760 B) | Tamaño máximo por archivo multimedia subido |
| `MAX_RECURSOS_TOTAL_BYTES` | 50 MB (52428800 B) | Tamaño máximo acumulado de recursos por borrador |
| `MAX_RECURSOS_POR_SESION` | 20 | Cantidad máxima de recursos multimedia por sesión |
| `MAX_BLOQUES_TEXTO` | 21 | Cantidad máxima de bloques de texto por borrador |

---

## Estados del Flujo (`EstadoFlujo`)

La máquina de estados de BACO (`baco/server/schemas/chat_orquestado.py`) define los siguientes estados:

| Estado | Etapa | Descripción |
|---|---|---|
| `ESPERANDO_TITULO` | 1 (Título y duplicados) | Espera el título inicial propuesto por el usuario |
| `DECISION_TITULO` | 1 (Título y duplicados) | Coincidencia de título detectada; espera si enriquece, actualiza o descarta |
| `ESPERANDO_TEXTO` | 2 (Contenido) | Espera la carga o confirmación del cuerpo del artículo |
| `DECISION_TEXTO` | 2 (Contenido) | Coincidencia de contenido detectada; espera si enriquece o continúa |
| `ESPERANDO_PLANTILLA`| 3 (Plantilla y etiquetas) | Espera la selección de formato (`instructivo` o `soluciones`) |
| `ESPERANDO_METADATOS` | 3 (Plantilla y etiquetas) | Espera la asignación de categoría y al menos 2 etiquetas |
| `REVISION_BORRADOR` | 4 (Revisión) | Borrador con validación determinista. Permite revisión intermedia o final, auditar con skills o avanzar |
| `EDICION_FINAL` | 4 (Revisión) | Último paso antes de registrar. Permite editar libremente campos y finalizar |
| `FINALIZADO` | 5 (Conformidad) | Borrador registrado y sanitizado, listo para moderación. Estado terminal |
| `RECHAZADO` | 5 (Conformidad) | Borrador descartado y sesión cerrada. Estado terminal |

---

## Endpoints del Orquestador

### 1. Turno de Conversación: `POST /chat`

Endpoint unificado de avance determinista de la FSM.

#### Request (`ChatOrquestadorRequest`)

```json
{
  "mensaje": "Configurar facturación electrónica en Ventas",
  "accion": null,
  "titulo": null,
  "texto": null,
  "texto_editor": null,
  "categoria_id": 20,
  "tags": ["instructivo", "ventas", "facturacion"],
  "tipo_plantilla": "instructivo"
}
```

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `session_id` | `string \| null` | No | Deprecado. Se extrae de cabecera `X-Session-ID` o cookie `baco_session` |
| `mensaje` | `string \| null` | No | Texto conversacional ingresado por el usuario en el chat |
| `accion` | `string \| null` | No | Acción o identificador del botón presionado (`confirmar_texto`, `enriquecer`, `actualizar`, `descartar`, `continuar`, `continuar_revision`, `instructivo`, `soluciones`, `aplicar_plantilla`, `auditar`, `editar`, `finalizar`, `volver`, `reiniciar`, etc.) |
| `titulo` | `string \| null` | No | Título al crear o editar el borrador (15–255 caracteres) |
| `texto` | `string \| null` | No | Cuerpo del texto (hasta 16777 caracteres) |
| `texto_editor` | `string \| null` | No | Texto escrito exclusivamente en el Editor (independiente de Vista previa) |
| `categoria_id` | `int \| null` | No | ID numérico de la categoría de la tabla `categorias` |
| `tags` | `string[] \| null` | No | Lista de etiquetas temáticas y estructurales |
| `tipo_plantilla` | `string \| null` | No | Formato oficial: `"instructivo"` o `"soluciones"` |

#### Response (`ChatOrquestadorResponse`)

```json
{
  "session_id": "8f03b41d-4eb2-43bb-a1b7-b08709cf931b",
  "estado": "REVISION_BORRADOR",
  "etapa": {
    "actual": 4,
    "total": 5,
    "nombre": "Revisión",
    "etapas": [
      "Título y duplicados",
      "Contenido",
      "Plantilla y etiquetas",
      "Revisión",
      "Conformidad"
    ]
  },
  "mensaje": "¡Listo! Antes de seguir, ¿querés que revise tu artículo según las pautas editoriales?...",
  "opciones": ["auditar", "continuar", "volver"],
  "botones": [
    { "accion": "auditar", "label": "Auditar", "estilo": "btn-dark" },
    { "accion": "continuar", "label": "Continuar", "estilo": "btn-primary" },
    { "accion": "volver", "label": "Volver", "estilo": "btn-ghost" }
  ],
  "tags_acumulados": ["instructivo", "ventas", "facturacion"],
  "categorias_disponibles": [
    { "id": 20, "nombre": "Ventas" },
    { "id": 21, "nombre": "Contabilidad" }
  ],
  "tags_disponibles": ["afip", "facturacion", "instructivo", "soluciones", "ventas"],
  "coincidencias": [],
  "borrador": {
    "modo": "nuevo",
    "articulo_original_id": null,
    "articulo_original_url": null,
    "titulo": "Configurar facturación electrónica en Ventas",
    "bloques_texto": ["Para configurar el punto de venta..."],
    "recursos": {},
    "ultimo_id_recurso": 0,
    "texto_base_limpio": "",
    "texto_en_edicion": "Para configurar el punto de venta...",
    "texto_editor": "Para configurar el punto de venta...",
    "texto_original": null,
    "orden_multimedia": [],
    "posiciones": [],
    "contenido_adicional": [],
    "advertencias_recursos": [],
    "finalizado": false,
    "tipo_plantilla": "instructivo",
    "categoria_id": 20,
    "categoria_nombre": "Ventas",
    "tags": ["instructivo", "ventas", "facturacion"],
    "metadatos_anteriores": null,
    "revision_intermedia": false,
    "texto_base_revision_final": "Para configurar el punto de venta...",
    "metadatos_heredados_revisados": false,
    "resultado_skill_pendiente": false,
    "resultado_skill_desactualizado": false,
    "skill_pendiente": null,
    "skill_aplicada": null,
    "texto_limpio": "Para configurar el punto de venta...",
    "texto_alineado_discourse": "Para configurar el punto de venta...",
    "skills_habilitadas": true,
    "skills_motivo": null,
    "multimedia": []
  },
  "titulo": "Configurar facturación electrónica en Ventas",
  "texto_limpio": "Para configurar el punto de venta...",
  "texto_original": null,
  "texto_editor": "Para configurar el punto de venta...",
  "multimedia_habilitada": true,
  "skills_habilitadas": true,
  "skills_motivo": null,
  "validacion": {
    "valido": true,
    "fase": "fase_2_texto_y_estructura",
    "status": "Listo",
    "titulo_sanitizado": "Configurar facturación electrónica en Ventas",
    "texto_sanitizado": "Para configurar el punto de venta...",
    "aviso_privacidad": null,
    "findings": [],
    "resumen": { "longitud_texto": 35, "tags_count": 3 }
  },
  "aviso_privacidad": null,
  "aviso_metadatos_heredados": null
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `session_id` | `string` | ID de la sesión activa |
| `estado` | `EstadoFlujo` | Estado actual de la FSM |
| `etapa` | `EtapaFlujo` | Número `actual` de `total`, `nombre` y lista `etapas` |
| `mensaje` | `string` | Respuesta conversacional de BACO |
| `opciones` | `string[]` | Acciones o botones habilitados en el estado actual |
| `botones` | `BotonOpcion[]` | Botones con metadatos de estilo `{ accion, label, estilo }` |
| `tags_acumulados` | `string[]` | Etiquetas acumuladas en la sesión |
| `categorias_disponibles` | `CategoriaOpcion[]` | Categorías de la base de datos (`id: int`, `nombre: str`) |
| `tags_disponibles` | `string[]` | Etiquetas registradas para autocompletado |
| `coincidencias` | `CoincidenciaArticulo[]` | Artículos similares detectados en duplicados (`id`, `titulo`, `url`, `score`, `texto_original`, `tipo_coincidencia`) |
| `borrador` | `BorradorSesion \| null` | Estado completo del borrador en memoria |
| `titulo` | `string \| null` | Título limpio y sanitizado actual |
| `texto_limpio` | `string \| null` | Texto limpio sin marcadores ni adjuntos |
| `texto_original` | `string \| null` | Texto original previo a la aplicación de skills |
| `texto_editor` | `string \| null` | Texto destinado al Editor |
| `multimedia_habilitada` | `bool` | `true` una vez superada la búsqueda de duplicados |
| `skills_habilitadas` | `bool` | `true` si el texto no supera `TEXTO_MAX` (6687 chars) |
| `skills_motivo` | `string \| null` | Explicación si las skills están deshabilitadas |
| `validacion` | `ValidarFormatoResponse \| null` | Resultado de la validación estructural y editorial |
| `aviso_privacidad` | `string \| null` | Aviso puntual cuando se anonimizaron datos sensibles (CUIT, correos) en el turno |
| `aviso_metadatos_heredados` | `string \| null` | Notificación sobre metadatos de versiones anteriores |

---

### 2. Borrador Finalizado: `GET /chat/borrador`

Devuelve el `BorradorSesion` completo validado y sanitizado de la sesión activa.
- **Requisito estricto:** La sesión debe encontrarse en estado `FINALIZADO` y con `finalizado = true`. Si se llama en otro estado, responde `409 Conflict`.

---

### 3. Skills del Agente

#### `POST /chat/aplicar-plantilla`
Reestructura el texto del borrador de la sesión activa al formato oficial de la plantilla asignada (`instructivo` o `soluciones`). No requiere body.
- **Response (`ChatResponse`):**
  ```json
  {
    "response": "## Objetivo\n...\n\n## Pasos a seguir\n1. ..."
  }
  ```

#### `POST /chat/auditar-semantica`
Audita coherencia semántica, estilo y privacidad del borrador. No requiere body. Requiere que el borrador tenga categoría y al menos 2 etiquetas.
- **Response (`ChatResponse`):**
  ```json
  {
    "response": "Dictamen de validación semántica...",
    "texto_corregido": "Texto sugerido..."
  }
  ```

#### `POST /chat/revalidar-post-skill`
Ejecuta la validación determinista del borrador en silencio tras aplicar una skill.
- **Response:** `ValidarFormatoResponse`

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
