# Contrato de API — BACO

Borrador escrito desde las necesidades del panel. **Pensado para que Caro lo revise y ajuste** según lo que sea viable del backend.

Mientras no exista el backend, el panel corre contra una implementación simulada que respeta exactamente estas firmas. Cambiar de mock a real es cambiar una variable en `js/config.js`.

- **Base:** `/api/v1`
- **Formato:** JSON, UTF-8
- **El panel nunca habla con Discourse directamente.** Todo pasa por BACO, como definió Emiliano en la reunión del 28/09.

---

## Convenciones

**Error**, misma forma en todos los endpoints:

```json
{ "error": { "codigo": "ENTRADA_NO_ENCONTRADA", "mensaje": "...", "detalle": {} } }
```

Códigos que el panel ya contempla: `NO_AUTORIZADO`, `ENTRADA_NO_ENCONTRADA`, `VALIDACION`, `FUENTE_NO_DISPONIBLE` (Discourse caído o fuera del horario 8–20), `LIMITE_EXCEDIDO`, `ERROR_INTERNO`.

**Entrada** — el objeto central:

```json
{
  "id": "ent_8f2a",
  "estado": "borrador",
  "origen": "ui",
  "titulo": "Configurar el monitoreo hídrico - Protocolo bajo sequía",
  "categoria_id": "cat_agro_actividades",
  "etiquetas": ["instructivo", "agro", "riego"],
  "cuerpo": "…markdown…",
  "decision_duplicado": null,
  "entrada_destino": null,
  "autor": "dkleiman",
  "creada": "2026-10-09T14:03:11Z",
  "actualizada": "2026-10-09T14:21:40Z"
}
```

`origen` distingue `"ui"` (una persona cargando) de `"api"` (un agente externo). Es el campo que permite que el mismo flujo sirva para los dos casos de entrada que planteó Emiliano.

Los estados posibles están en [MAQUINA-ESTADOS.md](MAQUINA-ESTADOS.md).

---

## Catálogos

### `GET /categorias`

```json
[{ "id": "cat_agro_actividades", "nombre": "Gestión de actividades agrícolas", "grupo": "Agro" }]
```

### `GET /etiquetas?q=rie`

```json
[{ "tag": "riego", "usos": 18, "es_tipo_documentacion": false, "tiene_plantilla": false }]
```

Las etiquetas de tipo de documentación son las 11 que pasó Ayelen; solo 4 tienen plantilla.

### `GET /plantillas/{tipo}`

```json
{ "tipo": "instructivo", "cuerpo_markdown": "…" }
```

`404` si el tipo no tiene plantilla definida.

---

## Ciclo de vida de la entrada

### `POST /entradas`

Crea un borrador. Todos los campos son opcionales: el panel crea la entrada apenas el usuario empieza a escribir.

```json
{ "origen": "ui", "titulo": "", "categoria_id": null, "etiquetas": [], "cuerpo": "" }
```

→ `201` con la entrada.

**Este es también el endpoint que consumen los agentes externos**, mandando la entrada completa con `origen: "api"`.

### `GET /entradas/{id}` · `PATCH /entradas/{id}`

`PATCH` acepta campos parciales. El panel lo llama con debounce mientras se escribe.

---

## Detección de duplicados

Son **dos endpoints distintos a propósito**: tienen latencia y costo muy distintos.

### `GET /duplicados?titulo=…&categoria_id=…`

El chequeo rápido y determinista. Sin LLM, sin tokens. El panel lo dispara apenas hay título y categoría, con debounce.

```json
{
  "consulta": "monitoreo hídrico soja sequía",
  "metodo": "deterministico",
  "ms": 8,
  "total_revisados": 4500,
  "descartados": 4498,
  "candidatos": [
    {
      "id_externo": 3829,
      "titulo": "Monitoreo de riego y sensores de humedad",
      "url": "https://bc-dev.finneg.com/t/…/3829",
      "categoria": "Gestión de actividades agrícolas",
      "etiquetas": ["agro", "riego", "instructivo"],
      "autor": "mlopez",
      "actualizado": "2024-03-12",
      "fragmentos": 6,
      "score": 0.66,
      "veredicto": "parcial — cubre la configuración pero no el protocolo bajo sequía"
    }
  ]
}
```

Nota sobre `score`: en el ejemplo real que mandó Finnegans los artículos relevantes puntuaban entre **0.58 y 0.66**, así que el umbral no puede ser 0.85. El panel muestra el score sin interpretarlo — **el umbral lo define el backend** y conviene que venga en la respuesta cuando esté decidido.

### `POST /entradas/{id}/decision`

```json
{ "decision": "actualizar", "entrada_destino": 3829 }
```

`decision` ∈ `actualizar` · `fragmento` · `nueva`. Sin decisión tomada, el panel no deja publicar.

---

## Análisis agéntico

Asincrónico, como pidió Emiliano: *"hago toda la entrada, enviar, y que asincrónicamente se analice"*.

### `POST /entradas/{id}/analisis` → `202`

```json
{ "job_id": "job_c41e", "estado": "en_cola" }
```

### `GET /entradas/{id}/analisis/{job_id}`

```json
{
  "job_id": "job_c41e",
  "estado": "listo",
  "resultado": {
    "calidad": { "score": 0.78, "resumen": "Cumple el formato; faltan capturas." },
    "hallazgos": [
      { "id": "appbuilder", "nivel": "bloqueante", "campo": "cuerpo",
        "regla": "Quitar la línea de AppBuilder si no aplica",
        "ayuda": "La plantilla indica borrarla cuando no corresponde." }
    ],
    "gaps": ["Los valores de 12 mm salen del PDF de apoyo: validar contra pantalla."],
    "sugerencias": { "etiquetas": ["humedad-de-suelo"], "titulo": null }
  }
}
```

`estado` ∈ `en_cola` · `procesando` · `listo` · `error`. El panel hace polling cada 1,5 s. Si más adelante hay websocket o webhook, se reemplaza el polling sin tocar la UI.

`nivel` ∈ `bloqueante` · `aviso`. **Qué regla es bloqueante y cuál aviso lo decide el backend**, no el panel.

---

## Publicación

### `POST /entradas/{id}/publicar`

```json
{
  "entrada": { "id": "ent_8f2a", "estado": "pendiente_moderacion" },
  "moderacion": { "requerida": true, "motivo": "primeras tres publicaciones del autor" }
}
```

Si el backend resuelve que no requiere moderación, devuelve `estado: "publicada"` y `url_publica`.

---

## Archivos de apoyo

### `POST /archivos`

`multipart/form-data` con `archivo`. Un archivo por vez (lo pidió Ayelen: *"uno solo"*).

```json
{
  "nombre": "manual_riego_2026.pdf",
  "tipo": "application/pdf",
  "markdown": "## Protocolo de riego\n\n…",
  "advertencias": ["Se detectaron 3 tablas y se convirtieron a Markdown."]
}
```

El archivo **no se adjunta a la entrada**: se extrae el contenido y se vuelca en el editor, porque Fini solo lee lo que está embebido en el cuerpo.

---

## Chat del companion (Orquestador FSM)

### `POST /chat`

Endpoint unificado del orquestador determinista en servidor (`baco/server/services/orquestador/`). La sesión viaja por cookie `baco_session` (httpOnly) o cabecera `X-Session-ID`.

**Request (`ChatOrquestadorRequest`):**

```json
{
  "mensaje": "Configurar facturación electrónica en Ventas",
  "accion": null,
  "titulo": null,
  "texto": null,
  "categoria_id": 5,
  "tags": ["instructivo", "ventas"]
}
```

- Tope máximo de `texto` / `mensaje`: **16777 caracteres** de admisión (`TEXTO_MAX_PERCENTIL_99`), con un límite de **6687 caracteres** (`TEXTO_MAX`) para uso de skills / agente.
- Tope máximo de `titulo`: **255 caracteres** (`TITULO_MAX`).

**Response (`ChatOrquestadorResponse`):**

```json
{
  "session_id": "abc123...",
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
  "mensaje": "Metadatos registrados. El borrador fue validado (Listo).\n\nRevisá el borrador. Si estás conforme con el contenido, tocá Estoy conforme. Esto registra tu conformidad; no lo publica.",
  "opciones": ["conforme", "editar", "sanitizar", "rechazar", "volver", "reiniciar"],
  "tags_acumulados": ["instructivo", "ventas", "facturacion"],
  "categorias_disponibles": [
    { "id": 21, "nombre": "Contabilidad" },
    { "id": 20, "nombre": "Ventas" },
    { "id": 37, "nombre": "Agro" }
  ],
  "tags_disponibles": ["afip", "facturacion", "instructivo", "soluciones", "ventas"],
  "coincidencias": [],
  "borrador": {
    "modo": "nuevo",
    "articulo_original_id": null,
    "articulo_original_url": null,
    "titulo": "Configurar facturación electrónica en Ventas",
    "texto": "Para configurar el punto de venta...",
    "texto_original_conforme": null,
    "conforme": false,
    "conforme_en": null,
    "tipo_plantilla": "instructivo",
    "categoria_id": 5,
    "tags": ["instructivo", "ventas", "facturacion"]
  },
  "validacion": {
    "valido": true,
    "status": "Listo",
    "titulo_sanitizado": "Configurar facturación electrónica en Ventas",
    "texto_sanitizado": "Para configurar el punto de venta...",
    "findings": [],
    "resumen": { "longitud_texto": 180, "tags_count": 3 }
  },
  "aviso_privacidad": null
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `session_id` | `string` | Identificador de sesión activa |
| `estado` | `EstadoFlujo` | Estado actual de la FSM (`ESPERANDO_TITULO`, `DECISION_TITULO`, `ESPERANDO_TEXTO`, `DECISION_TEXTO`, `ESPERANDO_PLANTILLA`, `ESPERANDO_METADATOS`, `REVISION_BORRADOR`, `SUBSANANDO_BORRADOR`, `CONFORMIDAD_USUARIO`, `RECHAZADO`) |
| `etapa` | `EtapaFlujo` | Progreso `actual` de `total` (1 a 5), `nombre` de la etapa actual y lista ordenada `etapas` |
| `mensaje` | `string` | Respuesta conversacional de Baco para el turno actual |
| `opciones` | `string[]` | Acciones o botones elegibles habilitados por el servidor en este estado |
| `tags_acumulados` | `string[]` | Etiquetas acumuladas en la sesión/borrador hasta el turno actual |
| `categorias_disponibles` | `{id, nombre}[]` | Categorías leídas de la tabla `categorias` para mostrar como chips/selector |
| `tags_disponibles` | `string[]` | Etiquetas leídas de la tabla `tags` para sugerencias |
| `borrador` | `BorradorSesion \| null` | Borrador de sesión en memoria (si ya fue instanciado) |
| `coincidencias` | `CoincidenciaArticulo[]` | Candidatos detectados en los estados de decisión de duplicados |
| `validacion` | `ValidarFormatoResponse \| null` | Resultado de validación determinista post-duplicados |
| `aviso_privacidad` | `string \| null` | Aviso puntual cuando se anonimizan datos sensibles en el turno |

---

## Pendiente de definir con el backend

1. **Autenticación del panel contra BACO.** Hoy el mock no autentica. Falta saber si va header `Authorization`, cookie de sesión o SSO.
2. **Umbral de duplicado.** Debería venir del backend, no estar hardcodeado en el panel.
3. **Notificación cuando termina el análisis.** Hoy el panel hace polling. Emiliano mencionó mail, Slack o WhatsApp — si eso existe, el polling puede ser solo el fallback.
4. **Paginación de catálogos.** Son 120+ categorías y miles de etiquetas; si crecen, hace falta paginar o buscar del lado del servidor.
5. **Quién resuelve la decisión de "actualizar".** Editar una entrada ajena requiere nivel *líder* en Discourse, así que puede que la aplique el moderador y no BACO.
