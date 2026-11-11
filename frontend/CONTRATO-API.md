# Contrato de API — BACO

Especificación técnica de la API REST del backend de BACO (`baco/server/app/api.py`). El backend es la **fuente de verdad única**.

- **Host por defecto (desarrollo):** `http://127.0.0.1:8080`
- **Prefijo base:** `/` (las rutas cuelgan directamente de la raíz, sin prefijo `/api/v1`)
- **Formato:** JSON, UTF-8

## Cómo leer esta documentación

La API se documenta en dos partes complementarias:

1. **Referencia de endpoints y esquemas (generada desde el código):** rutas, métodos, parámetros, cuerpos de request/response y la descripción de cada campo.
   - En vivo: `/docs` (Swagger UI) o `/redoc` del servidor (piden HTTP Basic con `DOCS_USER` / `DOCS_PASSWORD`).
   - Sin levantar el servidor: [`openapi.json`](openapi.json), en esta misma carpeta. Se regenera con `python scripts/exportar_openapi.py` (desde la raíz del repo) cada vez que cambian endpoints o esquemas.
2. **Este documento:** lo que el esquema no expresa: autenticación, sesión, errores, límites, reglas de negocio y el comportamiento del orquestador por estado (qué botones, campos editables y transiciones hay en cada paso).

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
- **422 Unprocessable Entity:** Falla de validación de esquema Pydantic (devuelve lista de objetos `{loc, msg, type}`, sin el campo `input`) o precondición de negocio no cumplida (ej. invocar skill con artículo que supera límite de caracteres o faltan categorías/etiquetas). Excesos de cantidad de bloques/recursos o de bytes detectados por el esquema de `POST /chat/bloques` también responden 422. El texto que supera `TEXTO_MAX_PERCENTIL_99` responde **400** en `POST /chat/bloques` y **422** en `POST /chat` (validación del esquema). Superar `TEXTO_MAX` no genera error: solo deshabilita las skills.

> El backend **no** usa `413 Payload Too Large`: los excesos de tamaño responden `400` o `422` según dónde se detecten.

---

## Límites del Sistema (`baco/server/config_limites.py`)

| Parámetro | Valor                           | Descripción                                                                             |
|---|---------------------------------|-----------------------------------------------------------------------------------------|
| `TITULO_MIN` | 15 caracteres                   | Longitud mínima del título                                                              |
| `TITULO_MAX` | 255 caracteres                  | Longitud máxima del título                                                              |
| `TEXTO_MIN` | 20 caracteres                   | Longitud mínima del texto efectivo                                                      |
| `TEXTO_MAX` | 6687 caracteres                 | Límite máximo de caracteres de texto para invocar skills del agente                     |
| `TEXTO_MAX_PERCENTIL_99` | 16791 caracteres                | Límite máximo de admisión de texto para el orquestador P99                              |
| `TAGS_MIN` | 2                               | Mínimo de etiquetas para clasificar un artículo                                         |
| `TAGS_MAX` | 5                               | Máximo de etiquetas permitido                                                           |
| `TAGS_PLANTILLAS_PERMITIDAS` | `["instructivo", "soluciones"]` | Plantillas oficiales soportadas                                                         |
| `CATEGORIA_ID_DEFAULT` | 1                               | Categoría asignada por defecto                                                          |
| `PERMITIR_SUBIDA_RECURSOS` | `true`                          | Si es `false`, `POST /chat/recursos` responde `403`                                     |
| `RECURSO_MAX_BYTES` | 10 MB (10485760 B)              | Tamaño máximo por archivo multimedia subido                                             |
| `MAX_RECURSOS_TOTAL_BYTES` | 50 MB (52428800 B)              | Tamaño máximo acumulado de recursos por borrador                                        |
| `MAX_RECURSOS_POR_SESION` | 20                              | Cantidad máxima de recursos multimedia por sesión                                       |
| `MAX_BLOQUES_TEXTO` | 21                              | Cantidad máxima de bloques de texto por borrador (`MAX_RECURSOS_POR_SESION + 1`)        |
| `BUFFER_CARACTERES_PROMPT_XML` | 500                             | Margen de caracteres reservado para el envoltorio XML del prompt (uso interno del back) |

---

## Orquestador: estados y `POST /chat`

**Fuente de verdad:** `baco/server/services/orquestador/contrato.py` (estados, acciones de panel, acciones que guardan, skills); `opciones` y transiciones las resuelven `handlers.py`, `continuar.py` y `retroceso.py`.
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
4. **Sin volver en `REVISION_TIPO` ni `REVISION_METADATOS`.** El tipo y la categoría/etiquetas se editan en el lugar antes de la skill; aplicada la plantilla o el auditor dejan de ser editables y se corrigen en `EDICION_FINAL`.
5. **Terminales.** `FINALIZADO` y `RECHAZADO` no admiten mutaciones.

---

### 2. `POST /chat`

#### 2.1. Request y response

Los campos de `ChatOrquestadorRequest` y `ChatOrquestadorResponse` están descritos en la referencia generada (`openapi.json` o `/docs`). Reglas que el esquema no expresa:

- **Request.** `accion` es el id de una opción o navegación del turno anterior, una global o una de panel (§1.2). `titulo`, `texto`, `texto_editor`, `categoria_id`, `tags` y `tipo_plantilla` solo se tienen en cuenta si figuran en `editables`. `session_id` se ignora: la sesión la gestiona el servidor (cookie `baco_session` o header `X-Session-ID`).
- **Response.** El front renderiza a partir de `opciones`/`botones`, `navegacion`/`navegacion_etiquetas`, `editables`, `guardan_campos` (§2.4), `accion_panel` y `skills` (§2.3); `estado` es informativo y no se usa para deducir botones. `coincidencias` solo viene con datos en `DECISION_TITULO`/`DECISION_TEXTO`. `skills_habilitadas`/`skills_motivo` reflejan solo el límite de largo (`TEXTO_MAX`): para habilitar cada skill usar `skills`.

#### 2.3. `accion_panel` y `skills`

**`accion_panel`** (`contrato.accion_panel`): el front pinta el botón principal desde acá, no desde `estado`. Esa acción nunca se repite en `opciones` (no hay botón equivalente en el chat).

| Estado | `accion` | `label` | Qué envía el front |
| :--- | :--- | :--- | :--- |
| `ESPERANDO_TEXTO` | `confirmar_texto` | Confirmar texto | `accion: "confirmar_texto"` + `texto` |
| `ESPERANDO_METADATOS` | `enviar_datos` | Enviar datos | `accion: "enviar_datos"` + los `campos` (categoría, etiquetas y contenido) |
| `REVISION_TIPO`, `REVISION_METADATOS`, `EDICION_FINAL` | `guardar` | Guardar cambios | solo los `campos`; `guardar` **no** viaja como `accion`. Sin `accion`, el back guarda sin avanzar y descarta los campos no editables. Si `tags` no es editable, el tipo viaja en `tipo_plantilla` |
| resto | `null` | — | — (en `ESPERANDO_TITULO` Enter en el título envía `{titulo}`) |

`campos` = `editables` del estado.

**`skills`** (`contrato.estado_skills`, a partir de `ESTADOS_SKILL`): por cada skill, `habilitada` y `motivo` (`null` si está habilitada). Orden de evaluación del motivo:

1. Sin borrador → "Todavía no hay un borrador armado."
2. Estado fuera de `ESTADOS_SKILL` (plantilla: `REVISION_TIPO`, `EDICION_FINAL`; auditor: `REVISION_METADATOS`, `EDICION_FINAL`).
3. Bloqueantes de la validación en `REVISION_TIPO`/`REVISION_METADATOS`.
4. Límite de largo (`skills_motivo`).
5. Plantilla sin `tipo_plantilla`; auditor sin categoría o con menos de 2 etiquetas.

El largo del borrador puede cambiar entre turnos por los endpoints de recursos: si `borrador.skills_habilitadas` pasa a `false`, el front lo prioriza sobre `skills`.

#### 2.4. `guardan_campos`: qué acciones guardan lo editado

Fuente única: `contrato.ACCIONES_QUE_GUARDAN`. La respuesta trae la intersección con lo disponible en el turno. Regla para el front:

- Acción en `guardan_campos` → viaja como `accion` + los campos de `editables` (solo si hay cambios sin guardar). Desde el chat, con cambios, el front pide confirmar ([Guardar y continuar] [Cancelar]).
- Cualquier otra acción → viaja sola; con cambios sin guardar, el front avisa que se descartan ([Descartar y seguir] [Cancelar]).

| Estado | Acciones que guardan |
| :--- | :--- |
| `DECISION_TITULO` | `enriquecer`, `actualizar`, `descartar` (`texto`) |
| `DECISION_TEXTO` | `enriquecer`, `continuar` (`texto`; sin nueva búsqueda de duplicados) |
| `ESPERANDO_TEXTO` | `confirmar_texto`, `descartar` (enriquecimiento: `texto` = Editor, el texto propio) |
| `ESPERANDO_METADATOS` | `enviar_datos` |
| `REVISION_TIPO` | `continuar`, `aplicar_plantilla`, `editar`, `cancelar_rechazo`, `reaplicar` |
| `REVISION_METADATOS` | `continuar`, `auditar`, `editar`, `cancelar_rechazo`, `reaplicar` |
| `EDICION_FINAL` | `finalizar`, `aplicar_plantilla`, `auditar`, `reaplicar` |

`volver` no guarda en ningún estado (aviso de descarte). `reaplicar` figura solo con un resultado de skill pendiente; el front la muestra en el panel. `editar` ("Seguir editando") con cambios los guarda y revalida; sin cambios, pide editar.

**Texto del Editor y de la Vista previa:** sin skill aplicada hay un solo texto (el back iguala `texto_editor` a `texto`). Se separan solo con un resultado de skill pendiente (Editor = entrada para `reaplicar`; avanza la Vista previa) y en `ESPERANDO_TEXTO` de enriquecimiento (Editor = texto propio; Vista previa = artículo base). Al avanzar, el Editor se reemplaza por la Vista previa.

---

### 3. Matriz por estado

`C` = `["titulo", "texto", "texto_editor"]` (contenido).

| Estado | `opciones` | `navegacion` | `editables` | Skills |
| :--- | :--- | :--- | :--- | :--- |
| `ESPERANDO_TITULO` | `[]` | `[]` | `titulo` | — |
| `DECISION_TITULO` | serie: `actualizar, descartar` · estándar: `enriquecer, descartar` | `volver` | `texto` | — |
| `ESPERANDO_TEXTO` | nuevo: `[]` · enriquecimiento: `descartar` (`confirmar_texto` solo desde el panel) | `volver` | `texto` | — |
| `DECISION_TEXTO` | `enriquecer, continuar` | `volver` | `texto` | — |
| `ESPERANDO_PLANTILLA` | `instructivo, soluciones` | `volver` | `[]` (el tipo se elige solo por chat) | — |
| `ESPERANDO_METADATOS` | `[]` (se confirma con `enviar_datos`, solo desde el panel) · categoría ambigua: nombres de categorías candidatas (dinámicos) | `volver` (con la plantilla ya aplicada: `[]`) | `C`, `categoria_id`, `tags` | — |
| `REVISION_TIPO` | válido sin skill: `aplicar_plantilla, continuar` · plantilla aplicada: `continuar` · con bloqueantes: `editar, rechazar` · confirmando rechazo: `confirmar_rechazo, cancelar_rechazo` | `[]` | sin skill: `C`, `tipo_plantilla` · con skill: `C` | `plantilla` (no con bloqueantes) |
| `REVISION_METADATOS` | válido sin skill: `auditar, continuar` · auditado: `continuar` · con bloqueantes: `editar, rechazar` · confirmando rechazo: `confirmar_rechazo, cancelar_rechazo` | `[]` | sin skill: `C`, `categoria_id`, `tags` · con skill: `C` | `auditor` (no con bloqueantes) |
| `EDICION_FINAL` | `finalizar` · cambio de plantilla pedido: `confirmar_plantilla, cancelar_plantilla` | `[]` | `C`, `tipo_plantilla`, `categoria_id`, `tags` | `plantilla`, `auditor` |
| `FINALIZADO` | `[]` · ayuda o sesión expirada: `reiniciar` | `ver_articulo_final` | `[]` | — |
| `RECHAZADO` | `reiniciar` | `[]` | `[]` | — |

**Notas**
- Los enriquecidos pasan por `ESPERANDO_PLANTILLA` y `REVISION_TIPO` como cualquier borrador. Al salir de `REVISION_TIPO` con `continuar` se entra siempre a `ESPERANDO_METADATOS`, aunque los metadatos estén completos o sean heredados (estos llegan precargados en el borrador); la persona los confirma con `enviar_datos` desde el panel.
- En `ESPERANDO_METADATOS` las opciones de categoría no son ids fijos: el front envía el nombre tal cual lo recibió.
- `ver_articulo_final` reemite el mensaje de artículo finalizado; no muta nada.
- Al pasar a `RECHAZADO` el servidor destruye la cookie de sesión.

#### 3.1. Transiciones

Estado siguiente según la acción. Las acciones que no figuran (p. ej. `aplicar_plantilla`, `auditar`, `editar`, `reaplicar`, `rechazar`, `cancelar_rechazo`, `confirmar_plantilla`, guardar) dejan el flujo en el mismo estado. `reiniciar` (global) descarta la sesión y empieza otra en `ESPERANDO_TITULO`.

| Estado | Acción | Siguiente estado |
| :--- | :--- | :--- |
| `ESPERANDO_TITULO` | título (`mensaje` o `titulo`) | `DECISION_TITULO` si hay coincidencias por título; si no, `ESPERANDO_TEXTO` |
| `DECISION_TITULO` | `enriquecer` / `actualizar` | `ESPERANDO_TEXTO` (modo enriquecimiento) |
| | `descartar` | con texto de al menos `TEXTO_MIN`: búsqueda por texto → `DECISION_TEXTO` si hay coincidencias, si no `ESPERANDO_PLANTILLA`; sin texto: `ESPERANDO_TEXTO` |
| | `volver` | `ESPERANDO_TITULO` |
| `ESPERANDO_TEXTO` | `confirmar_texto` | nuevo: `DECISION_TEXTO` si hay coincidencias por texto, si no `ESPERANDO_PLANTILLA` · enriquecimiento: `ESPERANDO_PLANTILLA` |
| | `descartar` (enriquecimiento) | con texto propio: `ESPERANDO_PLANTILLA`; sin texto: sigue en `ESPERANDO_TEXTO` en modo nuevo |
| | `volver` | nuevo: `ESPERANDO_TITULO` · enriquecimiento: `DECISION_TEXTO` si la coincidencia vino por texto, si no `DECISION_TITULO` |
| `DECISION_TEXTO` | `enriquecer` | `ESPERANDO_TEXTO` (modo enriquecimiento) |
| | `continuar` | `ESPERANDO_PLANTILLA` |
| | `volver` | `ESPERANDO_TEXTO` |
| `ESPERANDO_PLANTILLA` | `instructivo` / `soluciones` | `REVISION_TIPO` |
| | `volver` | `ESPERANDO_TEXTO` |
| `REVISION_TIPO` | `continuar` | `ESPERANDO_METADATOS` |
| | `confirmar_rechazo` | `RECHAZADO` |
| `ESPERANDO_METADATOS` | `enviar_datos` | `REVISION_METADATOS` si quedan categoría y al menos 2 etiquetas; si no, sigue en `ESPERANDO_METADATOS` |
| | `volver` (no disponible si ya se aplicó la plantilla) | `REVISION_TIPO` si hay tipo de plantilla; si no, `ESPERANDO_PLANTILLA` |
| `REVISION_METADATOS` | `continuar` | `EDICION_FINAL` |
| | `confirmar_rechazo` | `RECHAZADO` |
| `EDICION_FINAL` | `finalizar` | `FINALIZADO` si se cumplen los obligatorios; si no, sigue en `EDICION_FINAL` con aviso |
| `FINALIZADO`, `RECHAZADO` | — | Terminales |

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
| `POST /chat/aplicar-plantilla` | `REVISION_TIPO`, `EDICION_FINAL` | Fuera de esos estados (incluidos `FINALIZADO` y `RECHAZADO`) → 409. |
| `POST /chat/auditar-semantica` | `REVISION_METADATOS`, `EDICION_FINAL` | Además: `categoria_id` cargada y ≥ 2 tags. Fuera de esos estados (incluidos `FINALIZADO` y `RECHAZADO`) → 409. |
| `POST /chat/revalidar-post-skill` | `REVISION_TIPO`, `REVISION_METADATOS`, `EDICION_FINAL`, `FINALIZADO` | Solo revalida, no muta contenido. |
| `POST /chat/bloques` | no terminales | `FINALIZADO` o `RECHAZADO` → 409. |
| `GET /chat/borrador` | `FINALIZADO` | Exige `borrador.finalizado == true`. |
| `GET /limites` | cualquiera | Devuelve los límites de `config_limites.py` (título, texto, `MAX_TEXTO_PERCENTIL_99`, tags); el front los toma de acá. |

`RECHAZADO` destruye la cookie, pero la sesión sigue en memoria hasta el TTL: un cliente que reenvíe el `session_id` recibe 409 en `POST /chat/bloques`, recursos y contenido adicional. El cliente web descarta el `session_id` al recibir `RECHAZADO`, así que ahí recibe 400 (falta identificar la sesión).

---

Si llega como `accion` un id que no está en el contrato (no vino en el turno anterior, no es global ni de panel), se rechaza con `MSG_OPCION_NO_DISPONIBLE`.

---

## Gestión de Bloques y Recursos Multimedia

Rutas, parámetros y esquemas en la referencia generada (`openapi.json` o `/docs`). Reglas de negocio:

- **`POST /chat/bloques`:** recibe la secuencia ordenada de bloques de texto y recursos, deriva el texto limpio y asigna las posiciones de los recursos. El `session_id` del body **tiene prioridad** sobre cookie/cabecera (ver *Identificador de sesión FSM*): enviarlo en `null`.
- **`GET /chat/recursos` y demás endpoints de recursos:** requieren haber superado la etapa de duplicados (si no, `409`).
- **`POST /chat/recursos`** (`multipart/form-data`): archivo de hasta `RECURSO_MAX_BYTES`, sin SVG. `posicion` es el índice del bloque de texto tras el cual se inserta (`-1` para el inicio); `bloques_texto`, si viene, reemplaza la partición de bloques (p. ej. al partir un bloque para insertar el recurso).
- **`POST /chat/recursos/agregar`:** solo URLs `http://` o `https://`.
- **`DELETE /chat/recursos/{recurso_id}`:** si dos bloques de texto quedan contiguos sin recurso intermedio, se fusionan (**fusión condicional**).
- **`PUT /chat/recursos/reordenar`:** acepta `from_index`/`to_index`, `orden_ids` u `orden_indices`.
- **`GET /api/recursos-temp/{session_id}/{archivo}`:** sirve la previsualización del archivo temporal al navegador. No requiere autenticación y **no figura en la referencia generada** (está excluido del esquema OpenAPI).

---

## Contenido Adicional (Flujos Actualizar / Enriquecer)

Ítems de contenido adicional, independientes del cuerpo principal del borrador. Endpoints (`GET`, `POST`, `DELETE`, `PUT .../reordenar`, `PUT`/`PATCH .../{item_id}`) y esquemas en la referencia generada.

**Restricciones de `POST /chat/contenido-adicional`:**
- `409 Conflict` si la sesión está en `FINALIZADO` o `RECHAZADO`.
- `400 Bad Request` si no hay borrador.
- `403 Forbidden` si el borrador no está en modo `enriquecimiento` o `actualizar` y no tiene artículo base (`articulo_original_id` es `null`), es decir, en modo `nuevo`.

