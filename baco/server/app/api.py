from fastapi import APIRouter, Depends
from baco.server.schemas.chat import ChatResponse
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.app.dependencies import get_buscador_duplicados, get_baco_agent
from baco.server.services.agente_service import (
    ejecutar_skill_plantillas,
    ejecutar_skill_validador,
)
from baco.server.services.orquestador import (
    manejar_turno,
    obtener_borrador_sesion_validado,
)

router = APIRouter(tags=["API REST"])


@router.post(
    "/chat",
    response_model=ChatOrquestadorResponse,
    summary="Endpoint unificado de chat conversacional con el orquestador"
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
def obtener_borrador_de_sesion(
    borrador: BorradorSesion = Depends(obtener_borrador_sesion_validado),
) -> BorradorSesion:
    return borrador


@router.post(
    "/chat/{session_id}/aplicar-plantilla",
    response_model=ChatResponse,
    summary="Aplica la skill 'plantillas' para estructurar el borrador en su formato oficial"
)
def aplicar_plantilla(
    session_id: str,
    borrador: BorradorSesion = Depends(obtener_borrador_sesion_validado),
    baco=Depends(get_baco_agent),
) -> ChatResponse:
    resultado = ejecutar_skill_plantillas(session_id, borrador, baco)
    return ChatResponse(response=resultado)


@router.post(
    "/chat/{session_id}/auditar-semantica",
    response_model=ChatResponse,
    summary="Aplica la skill 'validador' para auditar la coherencia semántica y estilo del artículo"
)
def auditar_semantica(
    borrador: BorradorSesion = Depends(obtener_borrador_sesion_validado),
    baco=Depends(get_baco_agent),
) -> ChatResponse:
    dictamen = ejecutar_skill_validador(borrador, baco)
    return ChatResponse(response=dictamen)
