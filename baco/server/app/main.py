import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from baco.server.db.config import db_pool
from baco.server.services.buscar_duplicados import buscar_generico


@asynccontextmanager
async def lifespan(app: FastAPI):
    # cargo el pool de conexiones
    db_pool.open()
    yield  # aca fast api escucha peticiones
    #cierro el pool
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
        limite: int = 1
):
    # MARCADOR 1: Tiempo antes de ejecutar la consulta
    t_inicio = time.perf_counter()

    # Ejecuta la búsqueda usando la conexión caliente del pool
    coincidencias = await run_in_threadpool(buscar_generico, "titulo", titulo, limite=limite)

    # MARCADOR 2: Tiempo después de obtener los resultados
    t_fin = time.perf_counter()
    latencia_ms = (t_fin - t_inicio) * 1000

    # Imprime en la consola del servidor
    print(f"[FASTAPI /buscar] Título: '{titulo}' | Tiempo total endpoint: {latencia_ms:.2f} ms")

    # Retorna la respuesta con la latencia calculada
    if coincidencias:
        return {
            "encontrado": True,
            "origen": "titulo_exacto",
            "latencia_endpoint_ms": round(latencia_ms, 2),
            "articulos": coincidencias
        }
    return {
        "encontrado": False,
        "origen": None,
        "latencia_endpoint_ms": round(latencia_ms, 2),
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