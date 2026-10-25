import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import List, Optional
from fastmcp import FastMCP

import baco.server.db.config as db_cfg
from baco.server.db.config import get_ro_conn
from baco.server.core.facade import (
    buscar_duplicados as core_buscar_duplicados,
    validar_formato as core_validar_formato,
)
from baco.server.schemas.duplicados import BuscarDuplicadosToolOutput
from baco.server.schemas.validacion import ValidarFormatoToolOutput
from baco.server.services.buscar_duplicados import BuscadorDuplicados

logger = logging.getLogger("baco.mcp_server")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False


@asynccontextmanager
async def mcp_lifespan(server: FastMCP):
    pool_propio = False
    pool = getattr(db_cfg, "db_ro_pool", None)
    if pool is None or getattr(pool, "closed", True):
        pool = db_cfg.crear_ro_pool()
        pool.open(wait=True)
        db_cfg.db_ro_pool = pool
        pool_propio = True
    elif not getattr(pool, "_opened", False):
        try:
            pool.open(wait=True)
            pool_propio = True
        except Exception:
            pass

    try:
        from baco.server.services.embeddings import (
            embedding_texto,
            embedding_titulo,
            get_model_texto,
            get_model_titulo,
        )
        get_model_titulo()
        get_model_texto()
        embedding_titulo("Calentamiento inicial de grafos ONNX para titulo en MCP")
        embedding_texto("Calentamiento inicial de grafos ONNX para texto en MCP")
        yield
    finally:
        if pool_propio and pool is not None:
            try:
                pool.close()
            except Exception:
                pass


mcp = FastMCP(name="baco-mcp", lifespan=mcp_lifespan)


def _resolver_deps():
    conn_fn = get_ro_conn
    buscador_cls = BuscadorDuplicados
    app_mod = sys.modules.get("baco.server.app.mcp_server")
    if app_mod is not None:
        if getattr(app_mod, "get_ro_conn", get_ro_conn) is not get_ro_conn:
            conn_fn = getattr(app_mod, "get_ro_conn")
        if getattr(app_mod, "BuscadorDuplicados", BuscadorDuplicados) is not BuscadorDuplicados:
            buscador_cls = getattr(app_mod, "BuscadorDuplicados")
    return conn_fn, buscador_cls


def _buscar_duplicados_db(
    titulo: Optional[str] = None,
    texto: Optional[str] = None,
    limite: int = 3,
    borrador: Optional[str] = None,
) -> BuscarDuplicadosToolOutput:
    conn_fn, buscador_cls = _resolver_deps()
    return core_buscar_duplicados(
        titulo=titulo,
        texto=texto,
        limite=limite,
        borrador=borrador,
        _get_ro_conn=conn_fn,
        _buscador_cls=buscador_cls,
    )


@mcp.tool(
    name="buscar_duplicados",
    description=(
        "Herramienta de SOLO LECTURA. Busca artículos duplicados o semánticamente similares "
        "en la Base de Conocimiento a partir de un título (15 a 255 caracteres), un texto opcional "
        "(20 a 6687 caracteres) y un límite de resultados (1 a 10, por defecto 3). "
        "Devuelve el nivel de coincidencia ('exacto' con score 1.0, 'similar' o 'ninguno'), "
        "una decisión sugerida ('crear_nuevo' o 'proponer_mejora_existente') y la lista de artículos "
        "similares con id, título, URL y score, sin exponer jamás el cuerpo del artículo."
    ),
)
async def buscar_duplicados(
    titulo: Optional[str] = None,
    texto: Optional[str] = None,
    limite: int = 3,
    borrador: Optional[str] = None,
) -> BuscarDuplicadosToolOutput:
    """Busca artículos similares por título o texto (solo lectura) sin devolver el cuerpo de los artículos."""
    return await asyncio.to_thread(_buscar_duplicados_db, titulo, texto, limite, borrador)


@mcp.tool(
    name="validar_formato",
    description=(
        "Herramienta de SOLO LECTURA en memoria. Audita que el artículo cumpla con las cotas de longitud "
        "(título de 15 a 255 caracteres, texto de 20 a 6687 caracteres), la estructura de la plantilla "
        "obligatoria ('instructivo' o 'soluciones'), la presencia de categoría y al menos 2 etiquetas, "
        "y aplica sanitización determinista de datos sensibles (CUITs reales, emails y URLs internas). "
        "Devuelve el estado ('Listo', 'Listo con ajustes sugeridos' o 'Pendiente'), los hallazgos detallados "
        "y el título y texto sanitizados."
    ),
)
def validar_formato(
    titulo: str,
    texto: str,
    tags: Optional[List[str]] = None,
    categoria_id: Optional[int] = None,
) -> ValidarFormatoToolOutput:
    """Valida deterministamente formato, plantilla, metadatos y privacidad sobre el borrador."""
    return core_validar_formato(
        titulo=titulo,
        texto=texto,
        tags=tags,
        categoria_id=categoria_id,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
