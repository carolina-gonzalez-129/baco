# Cómo conectar el panel al backend de Caro

Actualizado al commit **237dcfb** del repo de Caro (22/10/2026).

---

## ⚠ Lo primero: el puerto

El backend solo acepta estos orígenes por CORS:

```
localhost:3000 · localhost:5173 · 127.0.0.1:3000 · 127.0.0.1:5173
```

**Por eso el panel ahora corre en el 5173**, no en el 5501:

```bash
cd "Proyecto BACO/Panel"
python -m http.server 5173
```

Y se abre en <http://localhost:5173>

Si por algún motivo necesitás otro puerto, Caro puede agregarlo en la variable `CORS_ORIGINS` de su `.env`. Pero es más fácil usar el 5173.

---

## Camino A — Caro levanta el backend y te pasa un túnel (recomendado)

En su `main.py` dejó anotado el comando: `cloudflared tunnel --url http://127.0.0.1:8080`.

**Lo que le pedís:**

1. Que levante el backend y el túnel
2. **La URL del túnel** (`https://xxxx.trycloudflare.com`)
3. **El valor de `API_KEY_SERVIDOR`** de su `.env`

**Lo que hacés vos** — en `js/config.js`:

```js
MODO: 'http',
BASE_URL: 'https://lo-que-te-pase.trycloudflare.com',
API_KEY: 'la-key-que-te-pase',
```

> La URL del túnel **cambia cada vez** que ella lo reinicia.

---

## Camino B — Levantarlo en tu máquina

Mucho más trabajo. Necesitás PostgreSQL con **pgvector**, ~2 GB de dependencias de Python, los modelos de embeddings, el `.env` (que no está en el repo) y el `data/articulos.json` (que tampoco).

Además ahora la base necesita **un usuario de solo lectura**: Caro agregó `baco_readonly` para que las consultas del chat nunca puedan modificar nada. Si lo levantás local, pedile también el script de creación de ese rol.

```powershell
cd "...\Proyecto BACO\backend-caro"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# crear el .env con los valores que te pase Caro
psql -U postgres -c "CREATE DATABASE baco_db;"
psql -U postgres -d baco_db -f baco\server\db\schema_completo.sql
python baco\server\db\reconstruir_db.py
uvicorn baco.server.app.main:app --host 0.0.0.0 --port 8080
```

> Caro dejó anotado que **no uses `--reload`** mientras estén mostrando algo: recarga al menor cambio y corta la demo.

---

## El contrato, en resumen

| Endpoint | Qué hace |
|---|---|
| `POST /chat` | Un turno del orquestador |
| `GET /chat/borrador` | Borrador en conformidad y sanitizado de la sesión activa |
| `POST /chat/aplicar-plantilla` | Skill *plantillas* sobre el borrador de la sesión |
| `POST /chat/auditar-semantica` | Skill *validador* sobre el borrador de la sesión |

**Autenticación:** header `X-API-Key: <API_KEY_SERVIDOR>` en todas.

**Sesión:** la maneja el backend. La devuelve en la cookie `baco_session` (httpOnly) y en el header `X-Session-ID`. El panel usa **el header**, porque la cookie es cross-origin y los navegadores la bloquean cada vez más. El campo `session_id` del cuerpo está deprecado y el backend lo ignora.

**Límites** (de `baco/server/config_limites.py`):

| | Mínimo | Máximo |
|---|---|---|
| Título | 15 | 255 |
| Texto | 20 | 16777 (admisión) / 6687 (skills) |
| Etiquetas | 2 | 5 |

---

## Cómo saber si funcionó

Arriba a la derecha el panel dice el modo: 🟡 **simulado** · 🟢 **backend**.

Si algo falla, aparece una franja roja con el código:

| Código | Qué pasó |
|---|---|
| `SIN_API_KEY` | Falta completar `API_KEY` en `js/config.js` |
| `NO_AUTORIZADO` | La key no coincide con la del `.env` |
| `SIN_SESION` | La sesión expiró. Tocá *Empezar de nuevo* |
| `SIN_CONEXION` | El backend no está levantado, la URL está mal, **o el panel no está en el 5173** |
| `VALIDACION` | El backend rechazó los datos (ej. título de menos de 15 caracteres) |

Cada error trae un botón **Reintentar** que repite el pedido sin hacerte rehacer el paso. Es lo que más va a servir: la instancia de desarrollo se apaga a las 20 y el túnel cambia de URL al reiniciarse.

---

## Lo que todavía no existe del lado del backend

- **No hay endpoint de publicación.** El flujo termina en `CONFORMIDAD_USUARIO`.
- **No hay catálogo** de categorías ni etiquetas; la categoría es un ID numérico. Caro dejó anotado en su código que habría que agregar un desplegable con los nombres.
- **Solo dos plantillas**: `instructivo` y `soluciones`.
- **No procesa PDF ni Word.** El botón de subir lee `.txt` y `.md` en el navegador.
