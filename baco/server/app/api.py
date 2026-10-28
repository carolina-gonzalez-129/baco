import json
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Cookie, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from baco.server.config_limites import (
    PERMITIR_SUBIDA_RECURSOS,
    RECURSO_MAX_BYTES,
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
)
from baco.server.schemas.chat import ChatResponse
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
    ItemContenidoAdicional,
    _sanitizar_y_validar_bloques,
)
from baco.server.schemas.recurso import (
    ConfirmarBloquesRequest,
    ConfirmarBloquesResponse,
    EstadoRecursosResponse,
    Recurso,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.app.dependencies import get_buscador_duplicados, get_baco_agent
from baco.server.services.validar_articulo import sanitizar_borrador
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
    DIR_TEMP_SESIONES,
    RecursoDuplicadoError,
    RecursoInvalidoError,
    RecursoNoEncontradoEnSesionError,
    SubidaRecursosDeshabilitadaError,
    _max_num_recurso,
    componer_texto_publicable,
    crear_recurso_desde_url,
    derivar_bloques_y_recursos,
    derivar_desde_bloques,
    extraer_recursos_y_texto_limpio,
    guardar_recurso_temporal_sesion,
    obtener_ruta_fisica_recurso,
    texto_efectivo_sin_marcadores,
)
from baco.server.services.orquestador.validaciones import consolidar_texto_enriquecimiento

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
    id: Optional[str] = Field(default=None, description="ID del recurso a mover a un nuevo (posicion, orden)")
    recurso_id: Optional[str] = Field(default=None, description="Alias de id del recurso a mover a un nuevo (posicion, orden)")
    posicion: Optional[int] = Field(default=None, description="Nuevo índice del bloque de texto tras el cual va (-1 para el inicio)")
    orden: Optional[int] = Field(default=None, description="Nuevo orden del recurso")
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
    if not borrador.skills_habilitadas:
        raise HTTPException(
            status_code=422,
            detail=borrador.skills_motivo or "Las skills están deshabilitadas para este borrador.",
        )
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
    if not borrador.skills_habilitadas:
        raise HTTPException(
            status_code=422,
            detail=borrador.skills_motivo or "Las skills están deshabilitadas para este borrador.",
        )
    dictamen = ejecutar_skill_validador(borrador, baco)
    return ChatResponse(response=dictamen)


@router.post(
    "/chat/bloques",
    response_model=ConfirmarBloquesResponse,
    summary="Recibe una lista de bloques y deriva texto_limpio con marcadores [[recurso:rec_N]] y recursos por separado",
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
    ultimo_id_prev = max(
        sesion.ultimo_id_recurso,
        sesion.borrador.ultimo_id_recurso if sesion.borrador else 0,
        _max_num_recurso(recursos_previos),
    )

    try:
        bloques_derivados, recursos, aviso = derivar_bloques_y_recursos(
            body.bloques,
            recursos_previos=recursos_previos,
            ultimo_id=ultimo_id_prev,
            session_id=sid,
        )
    except RecursoNoEncontradoEnSesionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RecursoInvalidoError as exc:
        msg_exc = str(exc)
        if any(k in msg_exc.lower() for k in ("ruta", "session_id", "recurso temporal", "http", "no existe en la sesión")):
            raise HTTPException(status_code=422, detail=msg_exc)
        raise HTTPException(status_code=400, detail=msg_exc)

    texto_limpio = "\n\n".join(bloques_derivados).strip()
    titulo_ctx = (sesion.borrador.titulo if sesion.borrador else sesion.titulo) or "Artículo"
    sanit = sanitizar_borrador(texto=texto_limpio, titulo=titulo_ctx)
    texto_sanitizado = sanit.get("texto_sanitizado", texto_limpio)
    aviso_priv = sanit.get("aviso_privacidad")
    bloques_sanitizados = [
        sanitizar_borrador(texto=b)["texto_sanitizado"].strip()
        for b in bloques_derivados
        if b.strip()
    ]
    bloques_sanitizados = [b for b in bloques_sanitizados if b]
    if sesion.borrador and sesion.borrador.modo == "enriquecimiento":
        sesion.borrador.texto_base_limpio = texto_sanitizado

    largo_efectivo = len(texto_efectivo_sin_marcadores(texto_sanitizado))
    if largo_efectivo < TEXTO_MIN:
        raise HTTPException(
            status_code=400,
            detail=f"El texto efectivo sin marcadores es muy breve ({largo_efectivo} < {TEXTO_MIN}).",
        )
    if largo_efectivo > TEXTO_MAX_PERCENTIL_99:
        raise HTTPException(
            status_code=400,
            detail=f"El texto efectivo sin marcadores excede el máximo permitido ({largo_efectivo} > {TEXTO_MAX_PERCENTIL_99}).",
        )

    aviso_final = f"{aviso_priv}\n\n{aviso}" if (aviso_priv and aviso) else (aviso_priv or aviso)
    max_id_nuevo = max(ultimo_id_prev, _max_num_recurso(recursos))

    if not sesion.borrador:
        sesion.borrador = BorradorSesion(
            modo="nuevo",
            titulo=titulo_ctx,
            bloques_texto=bloques_sanitizados,
            recursos=recursos,
            ultimo_id_recurso=max_id_nuevo,
            categoria_id=sesion.categoria_id,
            tags=list(sesion.tags),
        )
    else:
        sesion.borrador.bloques_texto = bloques_sanitizados
        sesion.borrador.texto_en_edicion = sesion.borrador.texto_limpio
        sesion.borrador.recursos = recursos
        sesion.borrador.ultimo_id_recurso = max_id_nuevo
        sesion.borrador._sincronizar_orden_recursos(list(recursos.values()), invalidar_conformidad=True)

    sesion.bloques_texto = list(sesion.borrador.bloques_texto)
    sesion.texto_limpio = sesion.borrador.texto_limpio
    sesion.texto_en_edicion = sesion.borrador.texto_limpio
    sesion.texto = sesion.borrador.texto_alineado_discourse
    sesion.recursos = dict(sesion.borrador.recursos)
    sesion.ultimo_id_recurso = max_id_nuevo
    sesion.orden_multimedia = list(sesion.borrador.orden_multimedia)
    sesion.posiciones = list(sesion.borrador.posiciones)

    return ConfirmarBloquesResponse(
        session_id=sid,
        bloques_texto=list(sesion.borrador.bloques_texto),
        texto_limpio=sesion.borrador.texto_limpio,
        recursos=sesion.borrador.multimedia,
        aviso=aviso_final,
        borrador=sesion.borrador,
    )


def construir_estado_recursos(sid: str) -> EstadoRecursosResponse:
    """Helper único para devolver el estado sincronizado de bloques_texto y recursos."""
    sesion = gestor_sesiones.obtener_sesion(sid)
    if not sesion or not sesion.borrador:
        return EstadoRecursosResponse(
            bloques_texto=list(sesion.bloques_texto) if sesion else [],
            recursos=[],
            texto_limpio=sesion.texto_limpio if sesion else "",
            multimedia_habilitada=multimedia_habilitada(sesion) if sesion else False,
            skills_habilitadas=True,
            skills_motivo=None,
        )
    b = sesion.borrador
    recursos_ord = sorted(b.recursos.values(), key=lambda r: (r.posicion, r.orden))
    return EstadoRecursosResponse(
        bloques_texto=list(b.bloques_texto),
        recursos=recursos_ord,
        texto_limpio=b.texto_limpio,
        multimedia_habilitada=multimedia_habilitada(sesion),
        skills_habilitadas=b.skills_habilitadas,
        skills_motivo=b.skills_motivo,
        estado=sesion.estado.value if sesion.estado else None,
        borrador=b,
    )


def _parsear_bloques_texto_form(bloques_raw: Optional[List[str]]) -> Optional[List[str]]:
    if bloques_raw is None:
        return None
    if len(bloques_raw) == 1 and isinstance(bloques_raw[0], str):
        s = bloques_raw[0].strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except Exception as exc:
                raise ValueError(f"Formato JSON inválido en bloques_texto: {exc}")
            if not isinstance(parsed, list):
                raise ValueError("bloques_texto debe ser una lista de cadenas.")
            return [str(x) for x in parsed]
    return [str(x) for x in bloques_raw]


@router.get(
    "/chat/recursos",
    response_model=EstadoRecursosResponse,
    summary="Devuelve el estado unificado de bloques_texto y recursos del borrador de la sesión activa"
)
def listar_recursos(
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> EstadoRecursosResponse:
    sid, _ = sesion_valida
    return construir_estado_recursos(sid)


@router.delete(
    "/chat/recursos/{recurso_id}",
    response_model=EstadoRecursosResponse,
    summary="Elimina un recurso multimedia del borrador, aplica fusión condicional y devuelve el estado unificado"
)
def eliminar_recurso(
    recurso_id: str,
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> EstadoRecursosResponse:
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
    return construir_estado_recursos(sid)


@router.put(
    "/chat/recursos/reordenar",
    response_model=EstadoRecursosResponse,
    summary="Reordena los recursos multimedia en el borrador mediante índices o vector explícito"
)
def reordenar_recursos_multimedia(
    body: ReordenarMultimediaRequest,
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> EstadoRecursosResponse:
    sid, _ = sesion_valida
    try:
        nuevo_orden = body.orden_indices if body.orden_indices is not None else body.orden_ids
        gestor_sesiones.reordenar_multimedia(
            session_id=sid,
            from_index=body.from_index,
            to_index=body.to_index,
            nuevo_orden=nuevo_orden,
            recurso_id=body.recurso_id or body.id,
            posicion=body.posicion,
            orden=body.orden,
        )
        return construir_estado_recursos(sid)
    except (EstadoInvalidoError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/chat/recursos/agregar",
    response_model=EstadoRecursosResponse,
    summary="Agrega o inserta un recurso multimedia en el borrador sin restricción de flujo"
)
def agregar_recurso_multimedia(
    body: AgregarRecursoRequest,
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> EstadoRecursosResponse:
    sid, borrador = sesion_valida
    try:
        recurso = crear_recurso_desde_url(
            url=body.referencia,
            recursos_actuales=borrador.recursos,
            nombre=body.nombre,
            tipo_sugerido=body.tipo,
            ultimo_id=borrador.ultimo_id_recurso,
        )
    except RecursoDuplicadoError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RecursoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    gestor_sesiones.agregar_recurso_multimedia(sid, recurso, posicion=body.posicion)
    return construir_estado_recursos(sid)


@router.post(
    "/chat/recursos",
    response_model=EstadoRecursosResponse,
    summary="Sube un archivo y lo agrega a la lista multimedia del borrador (opcionalmente partiendo bloques en una posición)"
)
async def subir_recurso(
    file: UploadFile = File(...),
    posicion: Optional[int] = Form(default=None),
    bloques_texto: Optional[List[str]] = Form(default=None),
    sesion_valida: Tuple[str, BorradorSesion] = Depends(resolver_sesion_con_borrador),
) -> EstadoRecursosResponse:
    sid, borrador = sesion_valida
    if not PERMITIR_SUBIDA_RECURSOS:
        raise HTTPException(
            status_code=403,
            detail="La subida de recursos nuevos está deshabilitada en esta fase de BACO (modo validador).",
        )

    sesion = gestor_sesiones.obtener_sesion(sid)
    borrador_backup = borrador.model_copy(deep=True)
    archivo_creado: Optional[Path] = None

    try:
        bloques_nuevos_sanitizados: Optional[List[str]] = None
        if bloques_texto is not None:
            bloques_parsed = _parsear_bloques_texto_form(bloques_texto)
            base_api = borrador.texto_base_limpio if borrador.modo == "enriquecimiento" else None
            bloques_nuevos_sanitizados = _sanitizar_y_validar_bloques(
                bloques_parsed or [],
                borrador.recursos,
                texto_base_limpio=base_api,
            )
            if not bloques_nuevos_sanitizados:
                raise ValueError("bloques_texto debe contener al menos un bloque de texto no vacío.")
            texto_unido = "\n\n".join(bloques_nuevos_sanitizados).strip()
            largo_efectivo = len(texto_efectivo_sin_marcadores(texto_unido))
            if largo_efectivo < TEXTO_MIN:
                raise ValueError(
                    f"El texto efectivo sin marcadores es muy breve ({largo_efectivo} < {TEXTO_MIN})."
                )
            if largo_efectivo > TEXTO_MAX_PERCENTIL_99:
                raise ValueError(
                    f"El texto efectivo sin marcadores excede el máximo permitido ({largo_efectivo} > {TEXTO_MAX_PERCENTIL_99})."
                )

        bloques_objetivo = (
            bloques_nuevos_sanitizados
            if bloques_nuevos_sanitizados is not None
            else borrador.bloques_texto
        )
        if posicion is not None:
            max_pos = len(bloques_objetivo) - 1
            if not (-1 <= posicion <= max_pos):
                raise ValueError(
                    f"La posición {posicion} está fuera del rango válido [-1, {max_pos}]."
                )

        # Se lee como máximo 1 byte más que el límite: alcanza para rechazar sin cargar archivos enormes en memoria
        contenido = await file.read(RECURSO_MAX_BYTES + 1)
        recurso = guardar_recurso_temporal_sesion(
            session_id=sid,
            filename=file.filename or "adjunto",
            contenido_bytes=contenido,
            content_type_declarado=file.content_type,
            recursos_actuales=borrador.recursos,
            ultimo_id=borrador.ultimo_id_recurso,
        )
        p_temp = obtener_ruta_fisica_recurso(recurso, session_id=sid)
        if p_temp and p_temp.exists():
            archivo_creado = p_temp

        if bloques_nuevos_sanitizados is not None:
            delta_bloques = len(bloques_nuevos_sanitizados) - len(borrador.bloques_texto)
            if delta_bloques > 0 and posicion is not None and borrador.recursos:
                for r_exist in borrador.recursos.values():
                    if r_exist.posicion >= posicion:
                        r_exist.posicion += delta_bloques
            borrador.bloques_texto = bloques_nuevos_sanitizados
            borrador.texto_en_edicion = borrador.texto_limpio

        gestor_sesiones.agregar_recurso_subido(sid, recurso, posicion=posicion)
        return construir_estado_recursos(sid)
    except SubidaRecursosDeshabilitadaError as exc:
        if archivo_creado and archivo_creado.exists():
            archivo_creado.unlink(missing_ok=True)
        if sesion:
            sesion.borrador = borrador_backup
            gestor_sesiones._sincronizar_sesion_desde_borrador(sesion)
        raise HTTPException(status_code=403, detail=str(exc))
    except (RecursoInvalidoError, ValueError, EstadoInvalidoError) as exc:
        if archivo_creado and archivo_creado.exists():
            archivo_creado.unlink(missing_ok=True)
        if sesion:
            sesion.borrador = borrador_backup
            gestor_sesiones._sincronizar_sesion_desde_borrador(sesion)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        if archivo_creado and archivo_creado.exists():
            archivo_creado.unlink(missing_ok=True)
        if sesion:
            sesion.borrador = borrador_backup
            gestor_sesiones._sincronizar_sesion_desde_borrador(sesion)
        raise


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


@router.get(
    "/api/recursos-temp/{session_id}/{archivo}",
    summary="Previsualiza un recurso temporal de la sesión para el navegador",
    include_in_schema=False,
)
def previsualizar_recurso_temporal(session_id: str, archivo: str):
    if any(c in session_id for c in ("/", "\\", "..")) or any(c in archivo for c in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="Identificador o nombre de archivo inválido.")
    dir_sesion = DIR_TEMP_SESIONES / session_id
    ruta_archivo = dir_sesion / archivo
    if not ruta_archivo.exists() or not ruta_archivo.is_file():
        raise HTTPException(status_code=404, detail="Recurso temporal no encontrado.")
    from fastapi.responses import FileResponse
    return FileResponse(str(ruta_archivo))

