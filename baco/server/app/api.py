from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from baco.server.db.config import get_conn
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.schemas.articulo import ArticuloSchema
from baco.server.services.validar_articulo import validar_texto_y_estructura_post_duplicados
from baco.agent import create_agent

router = APIRouter(tags=["API REST"])

def get_buscador_duplicados():
    with get_conn() as conn:
        with conn.cursor() as cur:
            yield BuscadorDuplicados(cur)

@router.get("/titulo_exacto")
async def titulo_exacto(
        titulo: str = Query(..., description="titulo"),
        buscador: BuscadorDuplicados = Depends(get_buscador_duplicados)
):
    hay_titulo_exacto = buscador.buscar_por_titulo(titulo)
    if hay_titulo_exacto:
        url = hay_titulo_exacto[0][2]
        return {
            "url": url,
            "mensaje": f"Ya hay un titulo exactamente igual ({url}), te gustaria consultarlo?"
        }
    return {
        "url": None
    }


@router.get("/buscar_duplicados")
async def buscar_duplicados(
        titulo: str = Query(..., description="titulo"),
        texto: str = Query(None, description="texto"),
        limite: int = 3,
        buscador: BuscadorDuplicados = Depends(get_buscador_duplicados)
):
    return await run_in_threadpool(
        buscador.evaluar_coincidencias,
        titulo,
        True,
        texto,
        limite
    )


@router.post("/validar_post_duplicados")
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


class ChatRequest(BaseModel):
    prompt: str


@router.post("/chat_baco")
def chat(
        request: ChatRequest,
        baco = Depends(create_agent)
) -> dict[str, str]:
    response = baco(request.prompt)
    return {"response": str(response)}