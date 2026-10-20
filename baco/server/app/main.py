from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from baco.server.db.config import db_pool
from baco.server.app.api import router as api_router
from baco.server.app.mcp_server import mcp_http_app
from baco.server.app.middleware import SecurityMiddleware


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
)

app.add_middleware(SecurityMiddleware)

app.include_router(api_router)
app.mount("/", mcp_http_app)

# NO USAR SIEMPRE ESTE COMANDO XQ SE RECARGA POR LO DEL RELOAD, LAP UTA QE LO PARIO
# uvicorn baco.server.app.main:app --reload --host 0.0.0.0 --port 8080
# http://localhost:8080/docs
# Endpoint MCP: http://localhost:8080/mcp
## PARA DIEGO
##PASARLE LA URL Q ME GENERE CLOUDFLARED !!! CON /docs al final  (DSPS DE .COM
# !!!!!!!!!
##CAMBIAR LO DEL RELOAD DE UVICORN DESPUES DE HACER TODAS LAS PRUEBAS XQ NO QUIERO Q SE CORTE MOSTRANDO NADA
#X SI JUSTO NO SE CAMBIO ALOG EN EL MOMENTO O TOCO ALGO
##!!!!
##osea # uvicorn baco.server.app.main:app --host 0.0.0.0 --port 8080
#Quizas dsps convieene hashear la pwd tmb
##cloudflared tunnel --url http://127.0.0.1:8080 --http-host-header="localhost:8080"