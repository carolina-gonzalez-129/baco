from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastmcp import FastMCP
from baco.server.db.config import db_pool, get_conn
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.agent import create_agent
from baco.server.schemas.articulo import ArticuloSchema
from baco.server.services.validar_articulo import (
    validar_titulo_pre_duplicados,
    validar_texto_y_estructura_post_duplicados,
)

def get_db_cursor():
    with get_conn() as conn:
        with conn.cursor() as cur:
            yield cur


def get_buscador_duplicados():
    with get_conn() as conn:
        with conn.cursor() as cur:
            yield BuscadorDuplicados(cur)



#HAY Q IMPLEMENTAR UN STATE MANAGER PARA Q 1) VERIFICAR SEA PRMERO 2) DEDUPLICAR 3) PERMITIR OBTENERU NA INSTANCIA DEL AGENTE!
@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool.open()
    from baco.server.services.embeddings import get_model_titulo, get_model_texto
    get_model_titulo()
    get_model_texto()
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
#ES LA PRIMERA ETAPA, SE DEBE SUPERPONER CON LA OTRA Y ES BLOQUEANTE
#1- ES PRE LO DE DUPLICADOS.
#En teoria se supone que esto sea validar primero y deduplicar dsps, asegurarlo dsps de algun modo
@app.get("/validar_titulo_inicial")
async def validar_titulo_inicial(
        titulo: str = Query(..., description="Titulo del artículo")
):
    articulo = ArticuloSchema(id=0, titulo=titulo)
    resultado = validar_titulo_pre_duplicados(articulo)
    if not resultado["apto_para_deduplicacion"]:
        return {
            "valido": False,
            "fase": "fase_1_titulo",
            "bloqueante": True,
            "findings": resultado["findings"]
        }

    return {
        "valido": True,
        "fase": "fase_1_titulo",
        "titulo_sanitizado": resultado["titulo_sanitizado"],
        "findings": resultado["findings"]
    }
#  DSPS DE LO DE DUPLICADOS-!
@app.post("/validar_post_duplicados")
async def validar_post_duplicados(articulo: ArticuloSchema):
    resultado = validar_texto_y_estructura_post_duplicados(articulo)
    es_valido = resultado["status"] != "Pendiente"
    return {
        "valido": es_valido,
        "fase": "fase_2_texto_y_estructura",
        "status": resultado["status"],
        "findings": resultado["findings"],
        "resumen": {
            "longitud_texto": resultado["longitud_texto"],
            "tags_count": resultado["tags_count"]
        }
    }
#IMPORTANTE : Solo deberia poder usarse si se paso lo anterior, si no no!
# SI DSPS NOS DICEN Q USEMOS LA API ESTO PASA A ASYNC! y hay q usar await y ir moldeandolo
@app.get("/buscar_duplicados")
def buscar_duplicados(
    titulo: str = Query(..., description="titulo"),
    texto: str = Query(None, description="texto"),
    limite: int = 5,
    buscador: BuscadorDuplicados = Depends(get_buscador_duplicados)
):
    coincidencias_titulo = buscador.evaluar_titulo(titulo, limite=limite)
    if coincidencias_titulo:
        return {
            "encontrado": True,
            "resultado": coincidencias_titulo,
            "mensaje": "se encontro el titulo"
        }
    if not texto or not texto.strip():
        return {
            "encontrado": False,
            "requiere_texto": True,
            "mensaje": "Indicar texto"
        }
    coincidencias_texto = buscador.evaluar_texto(texto, True, titulo, limite=limite)
    if coincidencias_texto:
        return {
            "encontrado": True,
            "resultado": coincidencias_texto
        }

    return {
        "encontrado": False,
        "requiere_texto": False,
        "mensaje": "No se encontraron duplicados, ofrecer publicar!"
    }

class ChatRequest(BaseModel):
    prompt: str
# creo a baco (CONFIGURAR DSPS A OLLAMA PORQ SEGURO SI NO ME DA 503)
#solo deberia poder crear al agente si las validaciones dieron bien, y no es duplicado
@app.post("/chat_bac")
def chat(request: ChatRequest) -> dict[str, str]:
    baco_agent = create_agent()
    response = baco_agent(request.prompt)
    return {"response": str(response)}
#Falta que exponga todas sus skills, aunque no se va a poder usarlas T_T

# PARA Q ELLOS DSPS PUEDAN USARLO MEDIANTE AGENTES
mcp = FastMCP.from_fastapi(app=app, name="Baco MCP")
mcp_app = mcp.http_app(path="/mcp")


@asynccontextmanager
async def combined_lifespan(app_inst: FastAPI):
    async with lifespan(app):
        async with mcp_app.lifespan(app_inst):
            yield


combined_app = FastAPI(
    title="API y MCP Server",
    routes=[
        *mcp_app.routes,
        *app.routes,
    ],
    lifespan=combined_lifespan,
)
combined_app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# levantar server : uvicorn baco.server.app.main:combined_app --reload --port 8080
# http://localhost:8080/docs

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("baco.server.app.main:combined_app", host="localhost", port=8080, reload=True)