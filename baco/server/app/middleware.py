import os
import base64
import secrets
from pathlib import Path
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse, Response

for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
    if (p / ".env").exists():
        load_dotenv(p / ".env")
        break
else:
    load_dotenv()
##PASARSELAS A LOS CHICOS
API_KEY = os.getenv("API_KEY_SERVIDOR")
DOCS_USER = os.getenv("DOCS_USER")
DOCS_PASSWORD = os.getenv("DOCS_PASSWORD")

if not API_KEY or not DOCS_USER or not DOCS_PASSWORD:
    raise RuntimeError("Faltan variables de autenticacion en .env")

DOCS_PATHS = {"/docs", "/openapi.json", "/redoc"}

class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        api_key = request.headers.get("X-API-Key")

        if request.url.path in DOCS_PATHS:
            if auth.startswith("Basic "):
                try:
                    user, pwd = base64.b64decode(auth[6:]).decode().split(":", 1)
                    if secrets.compare_digest(user, DOCS_USER) and secrets.compare_digest(pwd, DOCS_PASSWORD):
                        return await call_next(request)
                except Exception:
                    pass
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Docs"'})
        token = api_key or (auth[7:] if auth.startswith("Bearer ") else None)
        if not token or not secrets.compare_digest(token, API_KEY):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)