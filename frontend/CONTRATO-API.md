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

## Orquestador: estados y `POST /chat`

**Branch:** `corrigiendo-estados` · **Fuente de verdad:** `baco/server/services/orquestador/contrato.py`
**Destinatario:** front (`cliente.js`). El front no replica reglas de estado: muestra lo que declara cada respuesta.

---

### 1. Principios

1. **El back declara, el front renderiza.** En cada respuesta vienen `opciones` (botones del chat), `navegacion` (p. ej. `volver`) y `editables` (campos del panel). El front no deduce nada de `estado`.
2. **Regla única de aceptación.** Una `accion` se acepta solo si:
   - es global (`reiniciar`, `ayuda`), o
   - vino en `opciones` o `navegacion` del turno anterior, o
   - es una acción de panel del estado (ver §4).

   Cualquier otra acción se responde con `MSG_OPCION_NO_DISPONIBLE` sin cambiar de estado.
3. **Editables.** El back acepta solo los campos de `editables`; el resto se descarta con aviso.
4. **Sin volver después de una skill.** Aplicada la plantilla (`REVISION_TIPO`) o el auditor (`REVISION_METADATOS`), desaparece `volver` y lo clasificatorio deja de ser editable; se corrige en `EDICION_FINAL`.
5. **Terminales.** `FINALIZADO` y `RECHAZADO` no admiten mutaciones.

---

### 2. `POST /chat`

#### 2.1. Request (`ChatOrquestadorRequest`)

| Campo | Tipo | Uso |
| :--- | :--- | :--- |
| `mensaje` | `str?` | Texto libre del usuario (título, texto o respuesta). |
| `accion` | `str?` | Id de una opción/navegación recibida en el turno anterior, global o de panel (§1.2). |
| `titulo` | `str?` | Si `titulo` ∈ `editables`. |
| `texto` | `str?` | Si `texto` ∈ `editables`. |
| `texto_editor` | `str?` | Texto escrito por la persona en el Editor. Si ∈ `editables`. |
| `categoria_id` | `int?` | Si ∈ `editables`. |
| `tags` | `list[str]?` | Si ∈ `editables`. |
| `tipo_plantilla` | `"instructivo" \| "soluciones"?` | Si ∈ `editables`. |
| `session_id` | — | **Ignorado.** La sesión la gestiona el servidor (cookie `baco_session` o header `X-Session-ID`). |

#### 2.2. Response (`ChatOrquestadorResponse`)

**Control de flujo** (lo que el front usa para renderizar):

| Campo | Tipo | Significado |
| :--- | :--- | :--- |
| `estado` | `EstadoFlujo` | Informativo; el front no deriva botones de acá. |
| `etapa` | `EtapaFlujo` | Paso n de 5 y etapas para el stepper. |
| `mensaje` | `str` | Mensaje del asistente. |
| `opciones` | `list[str]` | Botones del chat válidos ahora. Nunca incluye navegación. |
| `botones` | `list[BotonOpcion]` | Las mismas `opciones` con etiqueta para mostrar. |
| `navegacion` | `list[str]` | `volver` o `ver_articulo_final`; el front decide cómo mostrarlas (no necesariamente como botón del chat). |
| `editables` | `list[str]` | Campos del panel que el back acepta ahora. |
| `frenar_finalizar` | `bool` | El guardado previo a Finalizar dejó un aviso: no encadenar `finalizar`. |
| `multimedia_habilitada` | `bool` | Mini panel multimedia operativo (superado `buscar_duplicados`). |
| `skills_habilitadas` / `skills_motivo` | `bool` / `str?` | Si las skills están disponibles y por qué no. |
| `plantilla_pendiente` | `str?` | En `EDICION_FINAL`: tipo pedido que espera `confirmar_plantilla`/`cancelar_plantilla`. |

**Datos del borrador:** `borrador`, `titulo`, `texto_limpio`, `texto_original` (Editor, previo a skill), `texto_editor`, `tags_acumulados`, `categorias_disponibles`, `tags_disponibles`, `coincidencias` (solo `DECISION_TITULO`/`DECISION_TEXTO`), `validacion`.

**Avisos puntuales:** `aviso_privacidad` (flash del turno), `aviso_metadatos_heredados`.

---

### 3. Matriz por estado

`C` = `["titulo", "texto", "texto_editor"]` (contenido).

| Estado | `opciones` | `navegacion` | `editables` | Skills |
| :--- | :--- | :--- | :--- | :--- |
| `ESPERANDO_TITULO` | `[]` | `[]` | `titulo` | — |
| `DECISION_TITULO` | serie: `actualizar, descartar` · estándar: `enriquecer, descartar` | `volver` | `texto` | — |
| `ESPERANDO_TEXTO` | nuevo: `confirmar_texto` · enriquecimiento: `confirmar_texto, descartar` · error de longitud/marcadores: `[]` | `volver` | `texto` | — |
| `DECISION_TEXTO` | `enriquecer, continuar` | `volver` | `texto` | — |
| `ESPERANDO_PLANTILLA` | `instructivo, soluciones` | `volver` | `tipo_plantilla` | — |
| `ESPERANDO_METADATOS` | carga por panel: `[]` · confirmar lo cargado por chat: `enviar_datos` · categoría ambigua: nombres de categorías candidatas (dinámicos) | `volver` | `C`, `categoria_id`, `tags` | — |
| `REVISION_TIPO` | válido sin skill: `aplicar_plantilla, continuar` · plantilla aplicada: `continuar` · con bloqueantes: `editar, rechazar` · confirmando rechazo: `confirmar_rechazo, cancelar_rechazo` | sin skill: `volver` · con skill o confirmando rechazo: `[]` | sin skill: `C`, `tipo_plantilla` · con skill: `C` | `plantilla` (no con bloqueantes) |
| `REVISION_METADATOS` | válido sin skill: `auditar, continuar` · auditado: `continuar` · con bloqueantes: `editar, rechazar` · confirmando rechazo: `confirmar_rechazo, cancelar_rechazo` | sin skill: `volver` · con skill o confirmando rechazo: `[]` | sin skill: `C`, `categoria_id`, `tags` · con skill: `C` | `auditor` (no con bloqueantes) |
| `EDICION_FINAL` | `finalizar` · cambio de plantilla pedido: `confirmar_plantilla, cancelar_plantilla` | `[]` | `C`, `tipo_plantilla`, `categoria_id`, `tags` | `plantilla`, `auditor` |
| `FINALIZADO` | `[]` · ayuda o sesión expirada: `reiniciar` | `ver_articulo_final` | `[]` | — |
| `RECHAZADO` | `reiniciar` | `[]` | `[]` | — |

**Notas**
- Los enriquecidos saltean a `REVISION_METADATOS` (decisión vigente).
- En `ESPERANDO_METADATOS` las opciones de categoría no son ids fijos: el front envía el nombre tal cual lo recibió.
- `ver_articulo_final` reemite el mensaje de artículo finalizado; no muta nada.
- Al pasar a `RECHAZADO` el servidor destruye la cookie de sesión.

---

### 4. Acciones de panel (no vienen en `opciones`)

| Acción | Estado | Condición |
| :--- | :--- | :--- |
| `confirmar_texto` | `ESPERANDO_TEXTO` | — |
| `enviar_datos` | `ESPERANDO_METADATOS` | — |
| `reaplicar` | `REVISION_TIPO`, `REVISION_METADATOS`, `EDICION_FINAL` | El handler exige `borrador.resultado_skill_pendiente == true`; si no, responde sin ejecutar la skill. |

---

### 5. Endpoints REST de skills y borrador

| Endpoint | Estados permitidos | Requisitos / errores |
| :--- | :--- | :--- |
| `POST /chat/aplicar-plantilla` | `REVISION_TIPO`, `EDICION_FINAL` | Fuera de estado → rechazo. `FINALIZADO` → 409. |
| `POST /chat/auditar-semantica` | `REVISION_METADATOS`, `EDICION_FINAL` | Además: `categoria_id` cargada y ≥ 2 tags. `FINALIZADO` → 409. |
| `POST /chat/revalidar-post-skill` | `REVISION_TIPO`, `REVISION_METADATOS`, `EDICION_FINAL`, `FINALIZADO` | Solo revalida, no muta contenido. |
| `POST /chat/bloques` | no terminales | `FINALIZADO` → 409. |
| `GET /chat/borrador` | `FINALIZADO` | Exige `borrador.finalizado == true`. |

`RECHAZADO` no necesita 409 propio: la sesión deja de existir (cookie destruida).

---

### 6. Fuera del contrato

Estos ids **no son parte del contrato**; si llegan como `accion`, se rechazan con `MSG_OPCION_NO_DISPONIBLE`. El front no debe enviarlos.

| Id | Situación en el back |
| :--- | :--- |
| `sanitizar` | Rama en `handlers.py` inalcanzable. |
| `copiar_borrador` | Sin implementación. |
| `aceptar`, `aceptar_metadatos`, `rechazar_metadatos` | Reemplazados por la asignación directa + `enviar_datos`. |
| `descartar` en `DECISION_TEXTO` | Rama inalcanzable (se ofrece `continuar`). |
| `continuar` en `ESPERANDO_TEXTO` | Rama inalcanzable (se ofrece `confirmar_texto`/`descartar`). |
| `volver` en `EDICION_FINAL` o tras una skill | Excluido por diseño. |
| `SUBSANANDO_BORRADOR`, `REVISION_BORRADOR`, `CONFORMIDAD_USUARIO`, `APROBADO` | Estados eliminados. |

---

## Gestión de Bloques y Recursos Multimedia

### `POST /chat/bloques`
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

### `GET /chat/recursos`
Devuelve el estado consolidado de `bloques_texto` y `recursos` multimedia (`EstadoRecursosResponse`). Requiere haber superado la etapa de duplicados.

### `POST /chat/recursos` (Subida de archivo)
Carga un archivo temporal en la sesión (`multipart/form-data`).
- **Form Data:**
  - `file`: Archivo binario (máx. 10 MB, no SVG).
  - `posicion` (opcional): Índice del bloque de texto tras el cual se inserta (-1 para el inicio).
  - `bloques_texto` (opcional): Lista JSON de cadenas con la partición actualizada de bloques de texto.
- **Response:** `EstadoRecursosResponse`

### `POST /chat/recursos/agregar`
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

### `DELETE /chat/recursos/{recurso_id}`
Elimina un recurso multimedia del borrador. Si dos bloques de texto quedan contiguos sin ningún otro recurso intermedio, aplica **fusión condicional** de bloques.
- **Response:** `EstadoRecursosResponse`

### `PUT /chat/recursos/reordenar`
Reordena los recursos multimedia en el borrador mediante `from_index`/`to_index`, lista de `orden_ids` o lista de `orden_indices`.
- **Response:** `EstadoRecursosResponse`

### `GET /api/recursos-temp/{session_id}/{archivo}`
Sirve la previsualización del archivo temporal para el navegador (no requiere cabecera de autenticación).

---

## Contenido Adicional (Flujos Actualizar / Enriquecer)

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

---

## Otras rutas de la aplicación

- **Servidor MCP:** la app FastAPI monta un servidor MCP HTTP en `/mcp` (`baco/server/app/main.py`, `baco/server/app/mcp_server.py`, `stateless_http=True`). No forma parte de la API REST que consume el front.
