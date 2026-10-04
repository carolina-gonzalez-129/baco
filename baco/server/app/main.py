from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from baco.server.services.buscar_duplicados import buscar_generico


@asynccontextmanager
async def lifespan(app: FastAPI):
    "Falta configurar un pool de conexiones psycopg para no abrir una conexion nueva en cada busqueda (ya que tarda entre 50 y 150 milisegundos)"
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("baco.server.app.main:app", host="localhost", port=8080, reload=True)

##IMPORTANTE : Como el servidor va a ser usado por agentes quizas estaria bueno configurar q
#sea un mcp server si eso compatibiliza con q pueda usarse tmb por usuairos (tiene sentido si vemos lo q nos pasaron ellos
#osea solo difiere en como se autentica pero

#Levantar servidor : uvicorn baco.server.app.main:app --reload --port 8080
#http://localhost:8080/docs
#no desde la web con nros q mandan xq se ve fea 
@app.get("/")
async def first_example():
    return {"message": "Es reactiva? Si xd"}

@app.get("/buscar")
async def buscar_por_titulo(
        titulo: str = Query(..., description="Título a buscar"),
        limite: int = 1
        #DSPS SI NO PONER MAS o dejarle al usuario elegir
):
    coincidencias = await run_in_threadpool(buscar_generico, "titulo", titulo, limite=limite)

    if coincidencias:
        return {
            "encontrado": True,
            "origen": "titulo_exacto",
            "articulos": coincidencias
        }
    return {
        "encontrado": False,
        "origen": None,
        "articulos": []
    }

