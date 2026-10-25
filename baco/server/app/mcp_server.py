"""
Módulo adaptador para montaje HTTP de MCP en FastAPI.
La definición autónoma de las tools y el servidor MCP reside en `baco.server.mcp_server`.
"""
from baco.server.db.config import get_ro_conn
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.mcp_server import (
    _buscar_duplicados_db,
    buscar_duplicados,
    mcp,
    validar_formato,
)

mcp_http_app = mcp.http_app(path="/mcp", stateless_http=True)

__all__ = [
    "mcp",
    "mcp_http_app",
    "buscar_duplicados",
    "validar_formato",
    "_buscar_duplicados_db",
    "get_ro_conn",
    "BuscadorDuplicados",
]
