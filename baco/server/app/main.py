import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Depends  # <-- 1. Agregamos Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from baco.server.db.config import db_pool, get_conn  # <-- 2. Importamos get_conn
from baco.server.services.buscar_duplicados import buscar_generico
def get_db_cursor():
    with get_conn() as conn:
        with conn.cursor() as cur:
            yield cur

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool.open()
    yield
    db_pool.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def first_example():
    return {"message": "Es reactiva? Si xd"}


@app.get("/buscar")
async def buscar_por_titulo(
        titulo: str = Query(..., description="Título a buscar"),
        limite: int = 1,
        cur = Depends(get_db_cursor)
):
    t_inicio = time.perf_counter()
    coincidencias = await run_in_threadpool(buscar_generico, "titulo", titulo, cur, limite=limite)
    t_fin = time.perf_counter()
    duracion_ms = (t_fin - t_inicio) * 1000
#DSPS ELIMINAR QIERO USAR ESTO SOLO PARA MEDIR LA LATENCIA DE CADA COSA!
    print("\n" + "=" * 60)
    print(f"--- TIEMPO INICIAL : 0.00 ms ---")
    print(f"--- TIEMPO FINAL   : {duracion_ms:.2f} ms ---")
    print(f"=== TIEMPO TOTAL   : {duracion_ms:.2f} ms ===")
    print("=" * 60 + "\n")

    if coincidencias:
        return {
            "encontrado": True,
            "origen": "titulo_exacto",
            "tiempo_ms": round(duracion_ms, 2),
            "articulos": coincidencias
        }
    return {
        "encontrado": False,
        "origen": None,
        "tiempo_ms": round(duracion_ms, 2),
        "articulos": []
    }

##IMPORTANTE : Como el servidor va a ser usado por agentes quizas estaria bueno configurar q
#sea un mcp server si eso compatibiliza con q pueda usarse tmb por usuairos (tiene sentido si vemos lo q nos pasaron ellos
#osea solo difiere en como se autentica pero

#levantar server : uvicorn baco.server.app.main:app --reload --port 8080
#http://localhost:8080/docs
#no desde la web con nros q mandan xq se ve fea

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("baco.server.app.main:app", host="localhost", port=8080, reload=True)