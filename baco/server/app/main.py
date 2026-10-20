from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from baco.server.db.config import db_pool
from baco.server.app.api import router as api_router
from baco.server.app.mcp_server import mcp_http_app
from baco.server.app.middleware import SecurityMiddleware
from baco.server.services.orquestador import EstadoInvalidoError, SesionNoEncontradaError


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool.open(wait=True)
    app.state.db_pool = db_pool
    from baco.server.services.embeddings import get_model_titulo, get_model_texto
    get_model_titulo()
    get_model_texto()
    try:
        async with mcp_http_app.lifespan(app):
            yield
    finally:
        db_pool.close()


app = FastAPI(
    title="BACO (api rest y mcp server)",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|.*\.trycloudflare\.com)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-ID"],
)

app.add_middleware(SecurityMiddleware)


@app.exception_handler(SesionNoEncontradaError)
async def sesion_no_encontrada_handler(request, exc: SesionNoEncontradaError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(EstadoInvalidoError)
async def estado_invalido_handler(request, exc: EstadoInvalidoError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})

# uvicorn baco.server.app.main:app --host 0.0.0.0 --port 8080
##cloudflared tunnel --url http://127.0.0.1:8080 --http-host-header="localhost:8080"
##ej podria ser url_tunel/chat
##o los endpoints de api.py

app.include_router(api_router)
app.mount("/", mcp_http_app)
