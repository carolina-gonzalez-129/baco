# Guía para levantar Baco con Docker

Necesitás Docker Desktop abierto y PowerShell con git (chequealo con `git --version`).

## 1) Clonar el repo

```powershell
mkdir C:\temp -Force
cd C:\temp
git clone https://github.com/carolina-gonzalez-129/baco baco
cd baco
```

## 2) Configurar el .env

Dos opciones:

- **Usar el .env ya configurado:** descargalo de la carpeta de Drive del mail y copialo a la carpeta `baco` con este nombre exacto (aunque el navegador lo haya renombrado al bajarlo):

  ```powershell
  copy "$HOME\Downloads\<nombre con que se descargó>" .env
  ```

- **Definir tus propios valores:** `copy .env.example .env` y completalo. Si cambiás `API_KEY_SERVIDOR`, poné el mismo valor en `API_KEY` de `frontend\js\config.js`.

Detalle de cada variable: [CONFIGURACION.md](CONFIGURACION.md).

## 3) Levantar todo

```powershell
docker compose up --build
```

Alternativa desde Git Bash: `./baco.sh` (hace lo mismo y antes chequea Docker, el .env y la API key). Otros comandos en [CONFIGURACION.md](CONFIGURACION.md#4-bacosh-y-la-base).

La primera vez puede tardar por los embeddings (en mi máquina tardó porque tiene poca CPU). Está listo cuando aparece:

```
app-1 | Uvicorn running on http://0.0.0.0:8080
```

Para apagarlo: `Ctrl+C`, o `docker compose down` (la base se conserva).

## 4) Uso

- **Front + back:** http://localhost:5173
- **API:** http://localhost:8080/docs. Entrás con `DOCS_USER` y `DOCS_PASSWORD` del .env; para probar los endpoints, cargá `API_KEY_SERVIDOR` en el botón **Authorize**.

Para probar con ejemplos: https://docs.google.com/document/d/1jh--HRvqy2F42yNAD06QOOgy-cQ6Tt2U4da7l1wgFeM/edit?tab=t.0

Muchas gracias ദ്ദി(˵ •̀ ᴗ - ˵ ) ✧
