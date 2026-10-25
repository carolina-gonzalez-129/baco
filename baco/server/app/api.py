from typing import List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Cookie, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from baco.server.config_limites import PERMITIR_SUBIDA_RECURSOS, RECURSO_MAX_BYTES
from baco.server.schemas.chat import ChatResponse
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
    ItemContenidoAdicional,
)
from baco.server.schemas.recurso import (
    ConfirmarBloquesRequest,
    ConfirmarBloquesResponse,
    Recurso,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.app.dependencies import get_buscador_duplicados, get_baco_agent
from baco.server.services.agente_service import (
    ejecutar_skill_plantillas,
    ejecutar_skill_validador,
)
from baco.server.services.orquestador import (
    EstadoInvalidoError,
    TTL_SEGUNDOS,
    gestor_sesiones,
    manejar_turno,
    obtener_borrador_sesion_validado,
)
from baco.server.services.orquestador.sesion import SesionChat, multimedia_habilitada
from baco.server.services.orquestador.recursos_service import (
    RecursoDuplicadoError,
    RecursoInvalidoError,
    SubidaRecursosDeshabilitadaError,
    componer_texto_publicable,
    crear_recurso_desde_url,
    derivar_desde_bloques,
    guardar_recurso_temporal_sesion,
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


def resolver_sesion_activa(
    baco_session: Optional[str] = Cookie(default=None),
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-ID"),
) -> Tuple[str, SesionChat]:
    sid = extraer_session_id(baco_session, x_session_id)
    if not sid:
        raise HTTPException(
            status_code=401,
            detail="No se encontró una sesión activa (se requiere cookie 'baco_session' o cabecera 'X-Session-ID').",
        )
    sesion = gestor_sesiones.obtener_sesion(sid)
    if not sesion:
        raise HTTPException(
            status_code=404,
            detail=f"No existe la sesión '{sid}' o la sesión expiró.",
        )
    return sid, sesion


def resolver_sesion_con_borrador(
    baco_session: Optional[str] = Cookie(default=None),
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-ID"),
) -> Tuple[str, BorradorSesion]:
    sid = extraer_session_id(baco_session, x_session_id)
    if not sid:
        raise HTTPException(
            status_code=401,
            detail="No se encontró una sesión activa (se requiere cookie 'baco_session' o cabecera 'X-Session-ID').",
        )
    sesion = gestor_sesiones.obtener_sesion(sid)
    if not sesion:
        raise HTTPException(
            status_code=404,
            detail=f"No existe la sesión '{sid}' o la sesión expiró.",
        )
    if not sesion.borrador:
        raise HTTPException(
            status_code=400,
            detail="No existe un borrador activo en la sesión.",
        )
    if not multimedia_habilitada(sesion):
        raise HTTPException(
            status_code=409,
            detail="La gestión multimedia se habilita una vez superada la búsqueda de duplicados.",
        )
    return sid, sesion.borrador


class ReordenarMultimediaRequest(BaseModel):
    from_index: Optional[int] = Field(default=None, description="Índice origen para mover elemento")
    to_index: Optional[int] = Field(default=None, description="Índice destino para mover elemento")
    orden_ids: Optional[List[str]] = Field(default=None, description="Vector de IDs en el nuevo orden")
    orden_indices: Optional[List[int]] = Field(default=None, description="Vector de índices numéricos en el nuevo orden")


class AgregarRecursoRequest(BaseModel):
    referencia: str = Field(..., min_length=1, max_length=2048, description="URL (http/https) del recurso")
    nombre: Optional[str] = Field(default=None, max_length=200, description="Nombre visible; si falta se deriva de la URL")
    tipo: Optional[Literal["imagen", "video", "audio", "documento"]] = Field(
        default=None,
        description="Opcional. El tipo se detecta de la URL; este valor solo se usa si la detección no es concluyente.",
    )
    posicion: Optional[int] = Field(default=None, description="Posición donde insertar; si falta, va al final")


class AgregarContenidoAdicionalRequest(BaseModel):
    contenido: str = Field(..., min_length=1, description="Contenido a agregar en la sección adicional.")
    tipo: str = Field(default="texto", description="Tipo de contenido (ej. 'texto', 'nota', 'recurso').")


class ReordenarContenidoAdicionalRequest(BaseModel):
    orden_ids: List[str] = Field(..., description="Lista ordenada con los IDs de los ítems de contenido adicional.")


class ModificarContenidoAdicionalRequest(BaseModel):
    contenido: str = Field(..., min_length=1, description="Nuevo contenido del ítem.")
    tipo: Optional[str] = Field(default=None, description="Nuevo tipo opcional.")


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
    summary="Obtiene el borrador de sesión validado y con conformidad registrada de la sesión activa"
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


@router.post(
    "/chat/bloques",
    response_model=ConfirmarBloquesResponse,
    summary="Recibe una lista de bloques y deriva texto_limpio con marcadores [[R1]], [[R2]]... y recursos por separado",
)
def confirmar_bloques(
    body: ConfirmarBloquesRequest,
    baco_session: Optional[str] = Cookie(default=None),
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-ID"),
) -> ConfirmarBloquesResponse:
    # No se loguea el body para preservar datos sensibles
    sid = body.session_id or extraer_session_id(baco_session, x_session_id)
    if not sid:
        raise HTTPException(
            status_code=400,
            detail="Falta identificar la sesión (X-Session-ID, cookie baco_session o session_id en el cuerpo).",
        )

    sesion = gestor_sesiones.obtener_sesion(sid)
    if not sesion:
        raise HTTPException(
            status_code=404,
            detail=f"No existe la sesión '{sid}' o la sesión expiró.",
        )

    recursos_previos = sesion.borrador.recursos if sesion.borrador else sesion.recursos

    try:
        texto_limpio, recursos, aviso = derivar_desde_bloques(
            body.bloques, recursos_previos=recursos_previos
        )
    except RecursoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not sesion.borrador:
        sesion.borrador = BorradorSesion(
            modo="nuevo",
            titulo=sesion.titulo or "Artículo",
            texto_limpio=texto_limpio,
            recursos=recursos,
            categoria_id=sesion.categoria_id,
            tags=list(sesion.tags),
        )
    else:
        sesion.borrador.texto_limpio = texto_limpio
        sesion.borrador.recursos = recursos
        sesion.borrador.orden_multimedia = [r.orden for r in sorted(recursos.values(), key=lambda x: x.orden)]
        sesion.borrador.posiciones = list(sesion.borrador.orden_multimedia)
        if sesion.borrador.conforme:
            sesion.borrador.conforme = False
            sesion.borrador.conforme_en = None
            sesion.borrador.conformidad_invalidada = True

    sesion.texto_limpio = texto_limpio
    sesion.texto = sesion.borrador.texto
    sesion.recursos = recursos
    sesion.orden_multimedia = list(sesion.borrador.orden_multimedia)

    return ConfirmarBloquesResponse(
        session_id=sid,
        texto_limpio=texto_limpio,
        recursos=sorted(recursos.values(), key=lambda r: r.orden),
        aviso=aviso,
        borrador=sesion.borrador,
    )


@router.get(
    "/chat/recursos",
    response_model=List[Recurso],
    summary="Lista los recursos multimedia y documentos asociados al borrador de la sesión activa"
)
def listar_recursos(
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> List[Recurso]:
    sid, borrador = sesion_valida
    return sorted(borrador.recursos.values(), key=lambda r: r.orden)


@router.delete(
    "/chat/recursos/{recurso_id}",
    summary="Elimina un recurso multimedia del borrador y remueve su marcador del texto limpio"
)
def eliminar_recurso(
    recurso_id: str,
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> dict:
    sid, borrador = sesion_valida
    target: Union[str, int] = recurso_id
    if recurso_id.isdigit() and recurso_id not in borrador.recursos:
        target = int(recurso_id)
    eliminado = gestor_sesiones.eliminar_recurso_multimedia(sid, target)
    if not eliminado:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el recurso '{recurso_id}' en el borrador de la sesión.",
        )
    return {"status": "ok", "eliminado": recurso_id}


@router.put(
    "/chat/recursos/reordenar",
    response_model=List[Recurso],
    summary="Reordena los recursos multimedia en el borrador mediante índices o vector explícito"
)
def reordenar_recursos_multimedia(
    body: ReordenarMultimediaRequest,
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> List[Recurso]:
    sid, _ = sesion_valida
    try:
        nuevo_orden = body.orden_indices if body.orden_indices is not None else body.orden_ids
        return gestor_sesiones.reordenar_multimedia(
            session_id=sid,
            from_index=body.from_index,
            to_index=body.to_index,
            nuevo_orden=nuevo_orden,
        )
    except (EstadoInvalidoError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/chat/recursos/agregar",
    response_model=Recurso,
    summary="Agrega o inserta un recurso multimedia en el borrador sin restricción de flujo"
)
def agregar_recurso_multimedia(
    body: AgregarRecursoRequest,
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> Recurso:
    sid, borrador = sesion_valida
    try:
        recurso = crear_recurso_desde_url(
            url=body.referencia,
            recursos_actuales=borrador.recursos,
            nombre=body.nombre,
            tipo_sugerido=body.tipo,
        )
    except RecursoDuplicadoError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RecursoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return gestor_sesiones.agregar_recurso_multimedia(sid, recurso, posicion=body.posicion)


@router.post(
    "/chat/recursos",
    response_model=Recurso,
    summary="Sube un archivo y lo agrega a la lista multimedia del borrador (opcionalmente en una posición)"
)
async def subir_recurso(
    file: UploadFile = File(...),
    posicion: Optional[int] = Form(default=None),
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> Recurso:
    sid, borrador = sesion_valida
    if not PERMITIR_SUBIDA_RECURSOS:
        raise HTTPException(
            status_code=403,
            detail="La subida de recursos nuevos está deshabilitada en esta fase de BACO (modo validador).",
        )
    # Se lee como máximo 1 byte más que el límite: alcanza para rechazar sin cargar archivos enormes en memoria
    contenido = await file.read(RECURSO_MAX_BYTES + 1)
    try:
        recurso = guardar_recurso_temporal_sesion(
            session_id=sid,
            filename=file.filename or "adjunto",
            contenido_bytes=contenido,
            content_type_declarado=file.content_type,
            recursos_actuales=borrador.recursos,
        )
    except (RecursoInvalidoError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SubidaRecursosDeshabilitadaError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return gestor_sesiones.agregar_recurso_subido(sid, recurso, posicion=posicion)


@router.get(
    "/chat/contenido-adicional",
    response_model=List[ItemContenidoAdicional],
    summary="Lista los ítems de contenido adicional del borrador de la sesión activa"
)
def listar_contenido_adicional(
    sesion_activa: Tuple[str, SesionChat] = Depends(resolver_sesion_activa),
) -> List[ItemContenidoAdicional]:
    sid, _ = sesion_activa
    return gestor_sesiones.obtener_contenido_adicional(sid)


@router.post(
    "/chat/contenido-adicional",
    response_model=ItemContenidoAdicional,
    summary="Agrega contenido nuevo a la sección adicional del borrador (flujos de actualizar o enriquecer)"
)
def agregar_contenido_adicional(
    body: AgregarContenidoAdicionalRequest,
    sesion_activa: Tuple[str, SesionChat] = Depends(resolver_sesion_activa),
) -> ItemContenidoAdicional:
    sid, sesion = sesion_activa
    if not sesion.borrador:
        raise HTTPException(
            status_code=400,
            detail="No hay un borrador activo en esta sesión.",
        )
    if (
        sesion.borrador.modo not in ("enriquecimiento", "actualizar")
        and sesion.borrador.articulo_original_id is None
    ):
        raise HTTPException(
            status_code=403,
            detail="El contenido adicional solo está habilitado para flujos de actualizar o enriquecer un artículo existente.",
        )
    try:
        return gestor_sesiones.agregar_contenido_adicional(
            session_id=sid,
            contenido=body.contenido,
            tipo=body.tipo,
        )
    except EstadoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete(
    "/chat/contenido-adicional/{item_id}",
    summary="Elimina un ítem de la sección de contenido adicional del borrador"
)
def eliminar_contenido_adicional(
    item_id: str,
    sesion_activa: Tuple[str, SesionChat] = Depends(resolver_sesion_activa),
) -> dict:
    sid, _ = sesion_activa
    try:
        eliminado = gestor_sesiones.eliminar_item_contenido_adicional(sid, item_id)
    except EstadoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not eliminado:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el ítem '{item_id}' en el contenido adicional.",
        )
    return {"status": "ok", "eliminado": item_id}


@router.put(
    "/chat/contenido-adicional/reordenar",
    response_model=List[ItemContenidoAdicional],
    summary="Reordena los ítems de la sección de contenido adicional del borrador"
)
def reordenar_contenido_adicional(
    body: ReordenarContenidoAdicionalRequest,
    sesion_activa: Tuple[str, SesionChat] = Depends(resolver_sesion_activa),
) -> List[ItemContenidoAdicional]:
    sid, _ = sesion_activa
    try:
        return gestor_sesiones.reordenar_contenido_adicional(sid, body.orden_ids)
    except EstadoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put(
    "/chat/contenido-adicional/{item_id}",
    response_model=ItemContenidoAdicional,
    summary="Modifica el contenido de un ítem de la sección adicional del borrador"
)
@router.patch(
    "/chat/contenido-adicional/{item_id}",
    response_model=ItemContenidoAdicional,
    summary="Modifica el contenido de un ítem de la sección adicional del borrador"
)
def modificar_contenido_adicional(
    item_id: str,
    body: ModificarContenidoAdicionalRequest,
    sesion_activa: Tuple[str, SesionChat] = Depends(resolver_sesion_activa),
) -> ItemContenidoAdicional:
    sid, _ = sesion_activa
    try:
        return gestor_sesiones.modificar_item_contenido_adicional(
            session_id=sid,
            item_id=item_id,
            nuevo_contenido=body.contenido,
            nuevo_tipo=body.tipo,
        )
    except EstadoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
