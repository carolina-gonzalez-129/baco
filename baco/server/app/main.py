from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from baco.server.app.api import router as api_router
from baco.server.app.exception_handlers import register_exception_handlers
from baco.server.app.lifespan import lifespan
from baco.server.app.middleware import setup_middlewares

app = FastAPI(
    title="BACO",
    version="1.0.0",
    lifespan=lifespan,
)

setup_middlewares(app)
register_exception_handlers(app)

app.include_router(api_router)


def _openapi_con_seguridad() -> dict:
    """Declara en el OpenAPI la API key que exige el middleware (X-API-Key o Bearer)."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema.setdefault("components", {})["securitySchemes"] = {
        "ApiKeyHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
        "BearerAuth": {"type": "http", "scheme": "bearer"},
    }
    schema["security"] = [{"ApiKeyHeader": []}, {"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_con_seguridad



#  uvicorn baco.server.app.main:app --host 0.0.0.0 --port 8080
#para probarlo con el front
# cd frontend
# python -m http.server 5173
#
#


