from fastapi import FastAPI
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

app.include_router(api_router)
app.mount("/", mcp_http_app)


#  uvicorn baco.server.app.main:app --host 0.0.0.0 --port 8080
#para probarlo con el front
# cd C:\Users\ahreq\IdeaProjects\GeminiAgente\frontend
# python -m http.server 5173
#



