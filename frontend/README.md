# BACO — Panel

Frontend de la consola de carga, integrado con el backend de BACO (`baco/server/`).

Opera contra el backend real (`MODO: 'http'`). El modo simulado (`api-mock.js`, `datos-mock.js`) es un resto del desarrollo previo: no refleja la máquina de estados actual y no debe usarse para probar.

## Cómo correrlo

```bash
# desde la raíz del repo
cd frontend
python -m http.server 5173
```

Y abrir <http://localhost:5173>

> Tiene que ser con servidor, no doble clic: el HTML carga scripts desde `js/`.
> Usar el puerto 5173 o el 3000: son los que el backend admite por CORS por defecto. Otros se habilitan con `CORS_ORIGINS` en el `.env`.

## Cómo conectarlo al backend

En `js/config.js`:

```js
MODO: 'http',
BASE_URL: 'http://localhost:8080',
API_KEY: '...',            // el API_KEY_SERVIDOR del .env
```

## El flujo

El backend conduce. Cada turno devuelve un `estado`, las `opciones` (botones del chat), la `navegacion` (p. ej. *volver*) y los `editables` (campos del panel), y el panel se acomoda: habilita los campos de `editables` y muestra los botones disponibles.

```
ESPERANDO_TITULO → DECISION_TITULO → ESPERANDO_TEXTO → DECISION_TEXTO
       → ESPERANDO_PLANTILLA → REVISION_TIPO → ESPERANDO_METADATOS
       → REVISION_METADATOS → EDICION_FINAL → FINALIZADO / RECHAZADO
```

*Volver* está disponible en `DECISION_TITULO`, `ESPERANDO_TEXTO`, `DECISION_TEXTO`, `ESPERANDO_PLANTILLA` y `ESPERANDO_METADATOS` (en este último, solo si no se aplicó la plantilla). En `REVISION_TIPO`, `REVISION_METADATOS` y `EDICION_FINAL` no hay *volver*: las correcciones se hacen en el lugar. El backend la declara en `navegacion` (no en `opciones`).

| Paso | Qué pide | Mínimo que exige el backend |
|---|---|---|
| 1 | Título | 15 a 255 caracteres |
| 2 | Contenido | 20 a 16791 caracteres (skills disponibles hasta 6687) |
| 3 | Plantilla (`instructivo` o `soluciones`) y etiquetas | 2 a 5 etiquetas |
| 4 | Revisión: aplicar plantilla (`REVISION_TIPO`), auditar (`REVISION_METADATOS`) y edición final | sin hallazgos bloqueantes |
| 5 | Finalizado | — |

El chat acepta texto libre solo para cargar el título (`ESPERANDO_TITULO`) y el contenido (`ESPERANDO_TEXTO`). En los demás pasos solo acepta las opciones que ofrece el turno (botones) y los comandos globales; cualquier otro texto se rechaza.

## Cómo está organizado

```
Panel/
├── index.html
├── styles.css
├── js/
│   ├── config.js        ← LO ÚNICO QUE SE TOCA PARA CONECTAR
│   ├── api.js           fachada: la UI solo usa esto
│   ├── api-mock.js      simulador obsoleto (no usar)
│   ├── api-http.js      llamadas al backend
│   ├── estados.js       estados, campos activos y store
│   ├── datos-mock.js    datos del simulador obsoleto
│   └── app.js           la interfaz
├── CONTRATO-API.md      contrato del back: estados, transiciones y reglas
└── openapi.json         referencia generada de endpoints y esquemas
```

La regla que hace barata la integración: **la UI no conoce `fetch` ni URLs**. Llama `BACO.api.turno(...)` y recibe la forma que define el backend.

## Qué anda

- Flujo completo, con el backend decidiendo cada paso
- Detección de duplicados por título y por contenido, con la opción de enriquecer el artículo existente
- Cabecera que indica si estás creando una entrada nueva o enriqueciendo una existente
- Validación con hallazgos separados en bloqueantes, ajustes y sugerencias
- Sanitizado de datos sensibles (CUITs, correos)
- Skills del agente desde el menú: aplicar plantilla y auditar
- Vista previa de Markdown
- Modal con el borrador finalizado y sanitizado
- Errores con código y explicación de qué hacer

## Para probar

- **Cargar ejemplo** precarga el título o el contenido según el paso en el que estés.
- **Simular fallas** y `mock.LATENCIA_MS` solo afectan al modo simulado, que está obsoleto.

## Diferencias con el contrato que habíamos escrito

El backend quedó bastante distinto de lo que habíamos propuesto originalmente. Hoy `CONTRATO-API.md` documenta ese contrato vigente del back. Lo que cambió respecto de la propuesta original:

| Habíamos propuesto | Lo que hay |
|---|---|
| CRUD de entradas con varios endpoints | Un endpoint principal de orquestación (`POST /chat`) que hace avanzar una máquina de estados, más endpoints REST para skills, bloques, límites y contenido adicional |
| El panel manejaba el estado | El backend manda; el panel refleja |
| Análisis asincrónico con polling | Validación sincrónica en cada turno |
| Endpoint de publicación | No existe todavía: el flujo termina en `FINALIZADO` |
| Catálogos de categorías y etiquetas | Llegan en cada turno: `categorias_disponibles` (id y nombre) y `tags_disponibles` |
