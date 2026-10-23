import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI


def _get_mcp_http_app():
    main_mod = sys.modules.get("baco.server.app.main")
    if main_mod and hasattr(main_mod, "mcp_http_app"):
        return main_mod.mcp_http_app
    from baco.server.app.mcp_server import mcp_http_app
    return mcp_http_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    import baco.server.db.config as cfg
    pool = cfg.crear_ro_pool()
    pool.open(wait=True)
    cfg.db_ro_pool = pool
    app.state.db_ro_pool = pool
    try:
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    from baco.server.services.orquestador.validaciones import precargar_catalogos_cache_sync
                    precargar_catalogos_cache_sync(cur)
        except Exception:
            pass

        from baco.server.services.embeddings import get_model_titulo, get_model_texto, embedding_titulo, embedding_texto
        get_model_titulo()
        get_model_texto()
        embedding_titulo("Calentamiento inicial de grafos y kernels ONNX para titulo")
        embedding_texto("Instructivo de calentamiento de grafos ONNX para texto y calculo de embeddings")
        async with _get_mcp_http_app().lifespan(app):
            yield
    finally:
        pool.close()
