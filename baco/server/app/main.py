from fastapi import FastAPI
from baco.server.db.config import db_pool
from baco.server.app.api import router as api_router
from baco.server.app.mcp_server import mcp_http_app
from baco.server.app.lifespan import lifespan
from baco.server.app.middleware import setup_middlewares
from baco.server.app.exception_handlers import register_exception_handlers

app = FastAPI(
    title="BACO (api rest y mcp server)",
    lifespan=lifespan,
)

setup_middlewares(app)
register_exception_handlers(app)

#   uvicorn baco.server.app.main:app --host 0.0.0.0 --port 8080
##  cloudflared tunnel --url http://127.0.0.1:8080"
##ej podria ser url_tunel/chat
##o los endpoints de api.py

app.include_router(api_router)
app.mount("/", mcp_http_app)
