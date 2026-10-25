# BACO — Panel

Frontend de la consola de carga, **adaptado al backend real de Caro** (`carolina-gonzalez-129/baco`).

Funciona de punta a punta sin backend, contra un simulador que reproduce su máquina de estados. Cuando hay backend disponible, se cambian tres líneas y pasa a hablar con él.

## Cómo correrlo

```bash
cd "Proyecto BACO/Panel"
python -m http.server 5173
```

Y abrir <http://localhost:5173>

> Tiene que ser con servidor, no doble clic: el HTML carga scripts desde `js/`.
> **Y tiene que ser el puerto 5173**: es el único que acepta el CORS del backend.

## Cómo conectarlo al backend

Ver **[CONECTAR-BACKEND.md](CONECTAR-BACKEND.md)**. En resumen, en `js/config.js`:

```js
MODO: 'http',
BASE_URL: 'https://...',   // túnel de Caro, o http://localhost:8080
API_KEY: '...',            // el API_KEY_SERVIDOR de su .env
```

## El flujo

El backend conduce. Cada turno devuelve un `estado` y una lista de `opciones`, y el panel se acomoda: habilita los campos que corresponden y muestra los botones disponibles.

```
ESPERANDO_TITULO → DECISION_TITULO → ESPERANDO_TEXTO → DECISION_TEXTO
       → ESPERANDO_PLANTILLA → ESPERANDO_METADATOS → REVISION_BORRADOR
       → CONFORMIDAD_USUARIO / RECHAZADO
```

Desde la versión del 22/10 **se puede volver atrás en cada paso**: el backend ofrece la opción *volver* y el panel la muestra como botón. Ya no es un camino de una sola dirección.

| Paso | Qué pide | Mínimo que exige el backend |
|---|---|---|
| 1 | Título | 15 a 255 caracteres |
| 2 | Contenido | 20 a 6687 caracteres |
| 3 | Plantilla (`instructivo` o `soluciones`) y etiquetas | 2 a 5 etiquetas |
| 4 | Revisión: editar, sanitizar, confirmar conformidad o rechazar | sin hallazgos bloqueantes |
| 5 | Conformidad | — |

En los pasos que esperan un dato, **el chat también sirve para contestar**: lo que escribas ahí alimenta el flujo. En los demás, es una consulta libre al agente.

## Cómo está organizado

```
Panel/
├── index.html
├── styles.css
├── js/
│   ├── config.js        ← LO ÚNICO QUE SE TOCA PARA CONECTAR
│   ├── api.js           fachada: la UI solo usa esto
│   ├── api-mock.js      emula el orquestador de Caro
│   ├── api-http.js      llamadas reales a su backend
│   ├── estados.js       estados, campos activos y store
│   ├── datos-mock.js    catálogos y artículos simulados
│   └── app.js           la interfaz
├── CONECTAR-BACKEND.md  ← empezar por acá para integrar
└── MAQUINA-ESTADOS.md
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
- Modal con el borrador en conformidad y sanitizado
- Errores con código y explicación de qué hacer

## Para probar

- **Cargar ejemplo** precarga el título o el contenido según el paso en el que estés.
- **Simular fallas** hace que ~1 de cada 3 llamadas falle, para ver los estados de error. Solo afecta al modo simulado.
- En `js/config.js`, `mock.LATENCIA_MS` cambia cuánto tarda cada respuesta.

## Diferencias con el contrato que habíamos escrito

El backend quedó bastante distinto de lo que habíamos propuesto en `CONTRATO-API.md`. **Ganó el de Caro**, que es el que existe. Lo que cambió:

| Habíamos propuesto | Lo que hay |
|---|---|
| CRUD de entradas con varios endpoints | Un solo `POST /chat` que hace avanzar una máquina de estados |
| El panel manejaba el estado | El backend manda; el panel refleja |
| Análisis asincrónico con polling | Validación sincrónica en cada turno |
| Endpoint de publicación | No existe todavía: el flujo termina en `CONFORMIDAD_USUARIO` |
| Catálogos de categorías y etiquetas | No hay; la categoría es un ID numérico |
