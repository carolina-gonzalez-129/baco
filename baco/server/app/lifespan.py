import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI

def _get_db_pool():
    main_mod = sys.modules.get("baco.server.app.main")
    if main_mod and hasattr(main_mod, "db_pool"):
        return main_mod.db_pool
    from baco.server.db.config import db_pool
    return db_pool


def _get_mcp_http_app():
    main_mod = sys.modules.get("baco.server.app.main")
    if main_mod and hasattr(main_mod, "mcp_http_app"):
        return main_mod.mcp_http_app
    from baco.server.app.mcp_server import mcp_http_app
    return mcp_http_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool = _get_db_pool()
    db_pool.open(wait=True)
    app.state.db_pool = db_pool

    from baco.server.services.embeddings import get_model_titulo, get_model_texto
    get_model_titulo()
    get_model_texto()

    mcp_app = _get_mcp_http_app()
    try:
        async with mcp_app.lifespan(app):
            yield
    finally:
        db_pool.close()
