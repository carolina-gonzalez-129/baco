# Contrato API del orquestador — BACO (back)

**Branch:** `corrigiendo-estados` · **Fuente de verdad:** `baco/server/services/orquestador/contrato.py`
**Destinatario:** front (`cliente.js`). El front no replica reglas de estado: muestra lo que declara cada respuesta.

---

## 1. Principios

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

## 2. `POST /chat`

### 2.1. Request (`ChatOrquestadorRequest`)

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

### 2.2. Response (`ChatOrquestadorResponse`)

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

## 3. Matriz por estado

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

## 4. Acciones de panel (no vienen en `opciones`)

| Acción | Estado | Condición |
| :--- | :--- | :--- |
| `confirmar_texto` | `ESPERANDO_TEXTO` | — |
| `enviar_datos` | `ESPERANDO_METADATOS` | — |
| `reaplicar` | `REVISION_TIPO`, `REVISION_METADATOS`, `EDICION_FINAL` | El handler exige `borrador.resultado_skill_pendiente == true`; si no, responde sin ejecutar la skill. |

---

## 5. Endpoints REST de skills y borrador

| Endpoint | Estados permitidos | Requisitos / errores |
| :--- | :--- | :--- |
| `POST /chat/aplicar-plantilla` | `REVISION_TIPO`, `EDICION_FINAL` | Fuera de estado → rechazo. `FINALIZADO` → 409. |
| `POST /chat/auditar-semantica` | `REVISION_METADATOS`, `EDICION_FINAL` | Además: `categoria_id` cargada y ≥ 2 tags. `FINALIZADO` → 409. |
| `POST /chat/revalidar-post-skill` | `REVISION_TIPO`, `REVISION_METADATOS`, `EDICION_FINAL`, `FINALIZADO` | Solo revalida, no muta contenido. |
| `POST /chat/bloques` | no terminales | `FINALIZADO` → 409. |
| `GET /chat/borrador` | `FINALIZADO` | Exige `borrador.finalizado == true`. |

`RECHAZADO` no necesita 409 propio: la sesión deja de existir (cookie destruida).

---

## 6. Fuera del contrato

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
