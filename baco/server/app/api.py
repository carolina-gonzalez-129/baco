from typing import Optional, Tuple
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response

from baco.server.schemas.chat import ChatResponse
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.app.dependencies import get_buscador_duplicados, get_baco_agent
from baco.server.services.agente_service import (
    ejecutar_skill_plantillas,
    ejecutar_skill_validador,
)
from baco.server.services.orquestador import (
    TTL_SEGUNDOS,
    manejar_turno,
    obtener_borrador_sesion_validado,
)

router = APIRouter(tags=["API REST"])


def extraer_session_id(
    baco_session: Optional[str] = Cookie(default=None),
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-ID"),
) -> Optional[str]:
    return baco_session or x_session_id


def resolver_sesion_y_borrador(
    baco_session: Optional[str] = Cookie(default=None),
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-ID"),
) -> Tuple[str, BorradorSesion]:
    sid = extraer_session_id(baco_session, x_session_id)
    if not sid:
        raise HTTPException(
            status_code=401,
            detail="No se encontró una sesión activa (se requiere cookie 'baco_session' o cabecera 'X-Session-ID').",
        )
    borrador = obtener_borrador_sesion_validado(sid)
    return sid, borrador


@router.post(
    "/chat",
    response_model=ChatOrquestadorResponse,
    summary="Endpoint unificado de chat conversacional con el orquestador"
)
async def chat_orquestado(
    http_request: Request,
    request: ChatOrquestadorRequest,
    response: Response,
    baco_session: Optional[str] = Cookie(default=None),
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-ID"),
    buscador: BuscadorDuplicados = Depends(get_buscador_duplicados)
) -> ChatOrquestadorResponse:
    request.session_id = extraer_session_id(baco_session, x_session_id)

    resultado = await manejar_turno(request, buscador)

    if resultado.estado == EstadoFlujo.RECHAZADO:
        response.delete_cookie(key="baco_session", path="/")
    else:
        is_https = (
            http_request.url.scheme == "https"
            or http_request.headers.get("x-forwarded-proto") == "https"
        )
        response.set_cookie(
            key="baco_session",
            value=resultado.session_id,
            httponly=True,
            samesite="none" if is_https else "lax",
            secure=is_https,
            path="/",
            max_age=TTL_SEGUNDOS,
        )
    response.headers["X-Session-ID"] = resultado.session_id
    return resultado


@router.get(
    "/chat/borrador",
    response_model=BorradorSesion,
    summary="Obtiene el borrador de sesión aprobado y sanitizado de la sesión activa"
)
def obtener_borrador_de_sesion(
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_y_borrador),
) -> BorradorSesion:
    _, borrador = sesion_valida
    return borrador


@router.post(
    "/chat/aplicar-plantilla",
    response_model=ChatResponse,
    summary="Aplica la skill 'plantillas' para estructurar el borrador en su formato oficial"
)
def aplicar_plantilla(
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_y_borrador),
    baco=Depends(get_baco_agent),
) -> ChatResponse:
    sid, borrador = sesion_valida
    resultado = ejecutar_skill_plantillas(sid, borrador, baco)
    return ChatResponse(response=resultado)


@router.post(
    "/chat/auditar-semantica",
    response_model=ChatResponse,
    summary="Aplica la skill 'validador' para auditar la coherencia semántica y estilo del artículo"
)
def auditar_semantica(
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_y_borrador),
    baco=Depends(get_baco_agent),
) -> ChatResponse:
    _, borrador = sesion_valida
    dictamen = ejecutar_skill_validador(borrador, baco)
    return ChatResponse(response=dictamen)
