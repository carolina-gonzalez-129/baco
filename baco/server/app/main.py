from contextlib import asynccontextmanager
from strands import tool
from fastapi import FastAPI, Query, Depends, Request
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
    validar_estilo_editorial,
)
from starlette.concurrency import run_in_threadpool

def get_db_cursor():
    with get_conn() as conn:
        with conn.cursor() as cur:
            yield cur


def get_buscador_duplicados():
    with get_conn() as conn:
        with conn.cursor() as cur:
            yield BuscadorDuplicados(cur)

"""
FALTA
1) IMPLEMENTAR UN MANEJADOR DE ESTADOS PARA Q POR EJ BUSCAR_DUPLICADOS SE PUEDA USAR SI Y SOLO SI SE PASO VALIDACION 1,
    TIENE Q CUBRIR TODO PORQ USAR SKILLS ES CARO ASIQ DEBE PERMITIR SOLO SI LO ANTERIOR FUE SATISFECHO
2) DEFINIR SI DESDE ACA TENGO Q DECLARAR A LAS SKILLS COMO TOOLS PARA Q LAS CONSUMAN OTROS AGENTES CON MCP.TOOL
Y COMO SERVIDOR NORMAL CON 

"""

#HAY Q IMPLEMENTAR UN STATE MANAGER PARA Q 1) VERIFICAR SEA PRMERO 2) DEDUPLICAR 3) PERMITIR OBTENERU NA INSTANCIA DEL AGENTE!
#ALGO MINIMO DE PERSISTENCIA PARA Q NO SE PIERDA EL HILO
#FALTA AGREGAR ALGO PARA Q SE CIERREN SI O SI LAS CONEXIONES A LA DB DESDE BUSCAR_DUPLICADOS CUANDO TERMINA!
#CREO UNA INSTANCIA DE BACO AL INICIAR EL SERVIDOR
@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool.open()
    from baco.server.services.embeddings import get_model_titulo, get_model_texto
    get_model_titulo()
    get_model_texto()
    app.state.baco_agent = create_agent()
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
## ESTO  QUIZAS PARA Q LE PEGUE A LA PARTE Q DICE ESCRIBE UN TITULO O PEGA UN ENLACE AQUI, NO VALIDA NADA
@app.get("/titulo_exacto")
async def titulo_exacto(
    titulo: str = Query(..., description="titulo"),
    buscador : BuscadorDuplicados = Depends(get_buscador_duplicados)
):
    hay_titulo_exacto = buscador.buscar_por_titulo(titulo)
    if hay_titulo_exacto:
        url = hay_titulo_exacto[0][2]
    return {
        "url": url,
        "mensaje": f"Ya hay un título exactamente igual ({url}), te gustaria consultarlo?"
    }

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


#IMPORTANTE : Solo deberia poder usarse si se paso lo anterior, si no no! O definir con ellos!

@app.get("/buscar_duplicados")
async def buscar_duplicados(
    titulo: str = Query(..., description="titulo"),
    texto: str = Query(None, description="texto"),
    limite: int = 3,
    buscador: BuscadorDuplicados = Depends(get_buscador_duplicados)
):
    coincidencias_titulo = await run_in_threadpool(
        buscador.evaluar_titulo,
        titulo,
        limite=limite
    )

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
    coincidencias_texto = await run_in_threadpool(
        buscador.evaluar_texto,
        texto,
        True,
        titulo,
        limite=limite
    )
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
#ME DA UNA INSTANCIA DE BACO, PERO SIN LOS MODULOS DEL SERVIDOR! QUIZAS DEBERIA EN CHAT AHI INCORPORAR TODO
def get_baco_agent(request: Request):
    return request.app.state.baco_agent

# FASE 3: validacion de estilo, deberia ser bloqueante quizas para publicar pero es dsps de haber recibido todo
@app.get("/validar_estilo")
async def validar_estilo(articulo: ArticuloSchema):
    resultado = validar_estilo_editorial(articulo)
    return resultado

#AGREGO LO DE LAS SKILLS PARA HACERLAS ACCESIBLES
#IMPORTANTE : LA PLANTILLA QUIZAS HAY Q AGREGAR LO DE Q SEA 1 MAS OSEA LO DE VIDEO
##FALRTA LA SKILL DE DUPLICADOS PERO QUIZAS SE PUIEDE ELIMINAR!
##ACA USAR LO DEL SCHEMA CON EL SLUG
#SE USA RECIEN DSPS DE HABER PASADO T ODO LO DE BUSCAR_DUPLICADOS SI O SI
#SI TENGO Q AGREGAR EL COMO SE HACE TMB IRIA UN CAMBIO ACA!
@app.post("/aplicar_plantilla")
async def aplicar_plantilla(articulo:ArticuloSchema,
    baco = Depends(get_baco_agent)
    ):
    slugs = {
        (t.slug or t.name).lower().strip()
        for t in (articulo.tags or [])
    }
    tipo = "soluciones" if ("soluciones" in slugs or "solucion" in slugs) else "instructivo"
    prompt = (
        f"Activa la skill 'plantillas' (formato '{tipo}') "
        f"para estructurar y normalizar el siguiente borrador.\n"
        f"Título: {articulo.titulo}\n"
        f"Texto:\n{articulo.texto}"
    )
    respuesta = baco(prompt)
    return {"texto_con_plantilla": str(respuesta)}

##LA SKILL DE VALIDATOR
##QUIZAS DSPS DE ESTO RESETEO DE MEMORIA DSPS DE ENVIARLO A OTRO LUGAR DONDE PUEDAN SER
##AUDITADOS POR UN MODERADOR!
#VER Q QUIZAS FALTAN MAS CAMPOS, RECHEQUEAR DSPS
@app.post("/auditar_calidad")
async def auditar_calidad(articulo: ArticuloSchema,
                          baco = Depends(get_baco_agent)
    ):
    prompt = (
    f"Activa la skill 'validator') "
    f"para estructurar y normalizar el siguiente borrador.\n"
    f"Título: {articulo.titulo}\n"
    f"Texto:\n{articulo.texto}"
)

class ChatRequest(BaseModel):
    prompt: str
    ##ACA VER DE INTEGRARLE LAS COSAS DEL SERVIDOR Y ALGO PARA Q DSPS LAS SKILLS USEN ESO!
#VER SI QUIEREN Q SEAN ASYNC O SI NO CAMBIAR A DEF NORMAL
#AGREGAR COMO TOOLS T ODO LO DEMAS Y CONSULTR CON EMILIANO, menos las skills
##DEBERIA REGISTRAR TODAS Si ellos lo quieren asi y la explicacion si o si como en validar_articulo preduplicados
@app.post("/chat_baco")
def chat(
        request: ChatRequest,
        baco = Depends(get_baco_agent)
) -> dict[str, str]:

    @tool
    async def validar_articulo_pre_duplicados(titulo:str):
        """Valida si el titulo inicial del artículo cumple las reglas pre-duplicados."""
        return await validar_titulo_inicial(titulo=titulo)
    baco.tool_registry.registry[validar_articulo_pre_duplicados.tool_name] = validar_articulo_pre_duplicados
    response = baco(request.prompt)
    return {"response": str(response)}


# PARA Q ELLOS DSPS PUEDAN USARLO MEDIANTE AGENTES
mcp = FastMCP.from_fastapi(app=app, name="Baco MCP")
mcp_app = mcp.http_app(path="/mcp")
#POR DEFECTO CON FastMCP.from_fastapi(app=app) todos los endpoints estan disponibles
#ver si no si quieren q sea solo baco de modificarlo para q sea solo baco como modulo que abarque t odo

@asynccontextmanager
async def combined_lifespan(app_inst: FastAPI):
    async with lifespan(app_inst):
        async with mcp_app.lifespan(app_inst):
            yield


#VER Q CREO Q DE ACA SE PUEDE CONFIGURAR LO DE Q SOLO ESTEN ACCESIBLES CIERTOS ENDPOINTS Y NO TODOS!

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



