from fastapi import APIRouter, Depends
from baco.server.schemas.chat import ChatRequest, ChatResponse
from baco.server.schemas.chat_orquestado import ChatOrquestadorRequest, ChatOrquestadorResponse
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.app.dependencies import get_buscador_duplicados, get_baco_agent
from baco.server.app.orquestador import manejar_turno

router = APIRouter(tags=["API REST"])

@router.post(
    "/chat",
    response_model=ChatOrquestadorResponse,
    summary="Endpoint unificado de chat simulando al agente baco"
)
async def chat_orquestado(
        request: ChatOrquestadorRequest,
        buscador: BuscadorDuplicados = Depends(get_buscador_duplicados)
) -> ChatOrquestadorResponse:
    return await manejar_turno(request, buscador)

##FALTA HACER Q SE INYECTE EL CONTEXTO SANITIZADO!
@router.post(
    "/chat_baco",
    response_model=ChatResponse,
    summary="Consulta al agente de conocimiento BACO"
)
def chat(
        request: ChatRequest,
        baco=Depends(get_baco_agent)
) -> ChatResponse:
    mensaje = request.construir_prompt_sanitizado()
    response = baco(mensaje)
    return {"response": str(response)}
