# Panel BACO — Nota de integración

Hola Caro. Este es el frontend del panel, ya adaptado a tu backend al commit **237dcfb**. Acá va todo lo que necesitás para probarlo y para saber qué espera de tu lado.

---

## Probarlo en 30 segundos

```bash
cd Panel
python -m http.server 5173
```

Y abrir <http://localhost:5173>

Arranca en **modo simulado**: hay un mock que reproduce tu orquestador (estados, opciones, validaciones, avisos de privacidad), así que se puede recorrer el flujo completo sin levantar nada. Arriba a la derecha dice contra qué está corriendo: 🟡 simulado · 🟢 backend.

---

## Conectarlo a tu backend

En `js/config.js`, tres líneas:

```js
MODO: 'http',
BASE_URL: 'http://127.0.0.1:8080',   // o la URL del túnel
API_KEY: 'el-API_KEY_SERVIDOR',
```

**El panel tiene que correr en el 5173** porque es uno de los orígenes que aceptás por CORS. Si preferís otro puerto, se agrega en tu `CORS_ORIGINS`.

---

## Qué consume, exactamente

| Endpoint | Cuándo |
|---|---|
| `POST /chat` | En cada paso del flujo |
| `GET /chat/borrador` | Al llegar a `APROBADO`, para mostrar el resumen final |
| `POST /chat/aplicar-plantilla` | Botón "Aplicar plantilla" del menú lateral |
| `POST /chat/auditar-semantica` | Botón "Auditar con validador" |

**Autenticación:** header `X-API-Key` en todas.

**Sesión:** el panel lee `X-Session-ID` de la respuesta y lo reenvía como header en el pedido siguiente. No manda `session_id` en el cuerpo. Elegimos el header en vez de la cookie porque `baco_session` es httpOnly y cross-origin, y los navegadores la bloquean cada vez más — con el header funciona siempre. Gracias por dejarlo en `expose_headers`, sin eso no se podía leer.

**Cuerpo de `/chat`:** solo manda lo que corresponde al paso — `titulo`, `texto`, `tags`, `categoria_id`, `accion` o `mensaje`.

---

## Cómo usa tu respuesta

Todo lo que devolvés se refleja en la pantalla:

| Campo | Qué hace el panel |
|---|---|
| `estado` | Decide qué campos se habilitan y qué paso se marca en el rail |
| `opciones` | Se renderizan como botones, abajo y en el chat |
| `mensaje` | Va al hilo del chat |
| `coincidencias` | Lista con el score y el tipo traducido a lenguaje común |
| `borrador` | Llena el formulario; es la fuente de verdad |
| `validacion.findings` | Tarjeta con bloqueantes, ajustes y sugerencias. **Cada hallazgo es clickeable y lleva al campo que señala** (`field`) |
| `aviso_privacidad` | Franja azul propia, separada de la de errores |

**El panel no calcula estados.** Solo refleja lo que mandás. Si agregás un estado o una opción nueva, avisame y la mapeo; mientras tanto la muestra con su nombre crudo en vez de romperse.

---

## Cosas que te pueden servir saber

**Los hallazgos llevan al campo.** Probando el flujo nos quedamos trabados con el marcador `[Indicar...]`: el mensaje sugiere *"editá el borrador o sanitizalo"*, pero sanitizar no resuelve ese caso porque solo limpia CUITs y correos. Del lado del panel lo compensamos haciendo que el hallazgo te lleve al campo, pero quizás convenga que el mensaje distinga entre lo que sanitizar arregla y lo que hay que editar a mano.

**Hay un botón de Reintentar** en cada error, que repite el pedido sin perder el paso. Pensado para cuando el túnel se corta o la instancia dev se apaga a las 20.

**Los límites están tomados de `config_limites.py`** (15/255, 20/6687, 2/5) y el panel los valida antes de mandar, así te ahorra viajes.

---

## Lo que el panel necesita y todavía no existe

Ninguna de estas rompe nada: están resueltas con un plan B, pero quedarían mejor con backend.

1. **Publicación.** El flujo termina en `APROBADO`. El panel muestra el resumen del borrador, pero no hay a dónde publicarlo.
2. **Catálogo de categorías.** Hoy la categoría es un campo numérico. Vi tu comentario en `config_limites.py` sobre el desplegable: si exponés un endpoint con id y nombre, lo convierto en selector.
3. **Catálogo de etiquetas.** Las sugerencias del panel salen de una lista local armada del export que nos pasó Ayelen. Con un endpoint, serían las reales.
4. **Subida de archivos.** El botón lee `.txt` y `.md` en el navegador y los vuelca en el editor. PDF y Word necesitan extracción del lado del servidor.

---

## Los archivos

```
Panel/
├── index.html
├── styles.css
├── js/
│   ├── config.js        lo único que se toca para conectar
│   ├── api.js           fachada: la UI solo usa esto
│   ├── api-mock.js      el simulador de tu orquestador
│   ├── api-http.js      las llamadas reales a tu backend
│   ├── estados.js       estados, campos activos por estado, store
│   ├── datos-mock.js    catálogos y artículos simulados
│   └── app.js           la interfaz
├── INTEGRACION.md       esto
├── CONECTAR-BACKEND.md  el paso a paso de la conexión
├── MAQUINA-ESTADOS.md   los estados y sus transiciones
└── CONTRATO-API.md      histórico: el contrato que habíamos propuesto
                         antes de ver tu backend. Ya no aplica
```

Si algo del contrato cambia, el único archivo a tocar es **`js/api-http.js`**. La interfaz no conoce `fetch` ni URLs: llama `BACO.api.turno(...)` y listo.

Cualquier cosa me escribís.

— Diego
