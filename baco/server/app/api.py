from fastapi import APIRouter, Depends, HTTPException
from baco.server.schemas.chat import ChatRequest, ChatResponse
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.app.dependencies import get_buscador_duplicados, get_baco_agent
from baco.server.app.orquestador import manejar_turno, obtener_borrador_aprobado

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


@router.get(
    "/chat/{session_id}/borrador",
    response_model=BorradorSesion,
    summary="Obtiene el borrador de sesión aprobado y sanitizado"
)
def obtener_borrador_de_sesion(session_id: str) -> BorradorSesion:
    borrador = obtener_borrador_aprobado(session_id)
    if borrador is None:
        raise HTTPException(
            status_code=404,
            detail="No existe un borrador en estado APROBADO para la sesión indicada o la sesión expiró."
        )
    return borrador


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
