from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    import baco.server.db.config as cfg
    pool = cfg.crear_ro_pool()
    pool.open(wait=True)
    cfg.db_ro_pool = pool
    app.state.db_ro_pool = pool
    try:
        try:
            with pool.connection() as conn, conn.cursor() as cur:
                from baco.server.services.orquestador.validaciones import (
                    precargar_catalogos_cache_sync,
                )
                precargar_catalogos_cache_sync(cur)
        except Exception:
            pass

        from baco.server.services.embeddings import (
            embedding_texto,
            embedding_titulo,
            get_model_texto,
            get_model_titulo,
        )
        get_model_titulo()
        get_model_texto()
        embedding_titulo("Calentamiento inicial de grafos y kernels ONNX para titulo")
        embedding_texto("Instructivo de calentamiento de grafos ONNX para texto y calculo de embeddings")

        yield
    finally:
        pool.close()
