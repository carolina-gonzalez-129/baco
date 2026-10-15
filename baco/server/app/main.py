from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from baco.server.db.config import db_pool
from baco.server.app.api import router as api_router
from baco.server.app.mcp_server import mcp_http_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool.open(wait=True)
    from baco.server.services.embeddings import get_model_titulo, get_model_texto
    get_model_titulo()
    get_model_texto()
    yield
    db_pool.close()

app = FastAPI(
    title="BACO Platform (API REST & MCP Server)",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


app.mount("/mcp", mcp_http_app)


#
# uvicorn baco.server.app.main:app --reload --port 8080
# http://localhost:8080/docs
# Endpoint MCP: http://localhost:8080/mcp