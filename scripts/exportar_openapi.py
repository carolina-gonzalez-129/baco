"""Exporta el esquema OpenAPI de la API HTTP de BACO a frontend/openapi.json.

Uso (desde la raíz del repo):
    python scripts/exportar_openapi.py

No levanta el servidor ni se conecta a la base: solo importa la app de FastAPI.
Volver a correrlo cada vez que cambien endpoints o esquemas (baco/server/schemas, app/api.py).
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from baco.server.app.main import app  # noqa: E402

DESTINO = RAIZ / "frontend" / "openapi.json"

if __name__ == "__main__":
    DESTINO.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI exportado a {DESTINO}")
