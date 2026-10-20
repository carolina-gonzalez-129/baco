from fastapi import APIRouter, Depends, HTTPException
from baco.server.schemas.chat import ChatRequest, ChatResponse
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.app.dependencies import get_buscador_duplicados, get_baco_agent
from baco.server.app.orquestador import (
    actualizar_borrador_texto,
    manejar_turno,
    obtener_borrador_aprobado,
    obtener_borrador_sesion_validado,
)

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
def obtener_borrador_de_sesion(
    borrador: BorradorSesion = Depends(obtener_borrador_sesion_validado),
) -> BorradorSesion:
    return borrador

##AGREGO ESTO PORQ SE SUPONE Q UNO PUEDE USAR A BACO SI Y SOLO SI PASAMOS LO ANTERIOR!
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
    prompt_sanitizado = (
        f"Skill solicitada: plantillas\n"
        f"Plantilla a aplicar: {borrador.tipo_plantilla}\n"
        f"Título del borrador: {borrador.titulo}\n"
        f"Borrador actual del artículo:\n\"\"\"\n{borrador.texto}\n\"\"\"\n\n"
        f"Instrucción: Estructurar este borrador aprobado en el formato oficial correspondiente."
    )
    resultado = str(baco(prompt_sanitizado))
    actualizar_borrador_texto(session_id, resultado)
    return {"response": resultado}


@router.post(
    "/chat/{session_id}/auditar-semantica",
    response_model=ChatResponse,
    summary="Aplica la skill 'validador' para auditar la coherencia semántica y estilo del artículo"
)
def auditar_semantica(
    borrador: BorradorSesion = Depends(obtener_borrador_sesion_validado),
    baco=Depends(get_baco_agent),
) -> ChatResponse:
    tags_str = ", ".join(borrador.tags) if borrador.tags else "Ninguno"
    prompt_sanitizado = (
        f"Skill solicitada: validador\n"
        f"Categoría / Módulo ERP: {borrador.categoria_id}\n"
        f"Tags: {tags_str}\n"
        f"Título del borrador: {borrador.titulo}\n"
        f"Borrador actual del artículo:\n\"\"\"\n{borrador.texto}\n\"\"\"\n\n"
        f"Instrucción: Auditar la calidad semántica, coherencia causa-efecto y estilo editorial del artículo antes de su publicación definitiva."
    )
    dictamen = str(baco(prompt_sanitizado))
    return {"response": dictamen}


 ##VER Q ONDA PORQ NO ESTA BUENO MANDAR DIRECTO LA SESSION_ID T_T