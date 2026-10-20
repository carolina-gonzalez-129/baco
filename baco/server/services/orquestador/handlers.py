from typing import Callable, Coroutine, Dict
from starlette.concurrency import run_in_threadpool

from baco.server.config_limites import (
    TEXTO_MAX,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.validar_articulo import sanitizar_borrador
from baco.server.services.orquestador.mensajes import (
    MSG_DESCARTAR_COINCIDENCIA_TITULO,
    MSG_ELEGIR_ENRIQUECER_O_CONTINUAR,
    MSG_ELEGIR_ENRIQUECER_O_DESCARTAR,
    MSG_ELEGIR_PLANTILLA,
    MSG_PEDIR_EDICION,
    MSG_RECHAZADO,
    MSG_SIN_COINCIDENCIAS_TITULO,
    MSG_TEXTO_VACIO,
    OPCIONES_ENRIQUECER_CONTINUAR,
    OPCIONES_ENRIQUECER_DESCARTAR,
    OPCIONES_PLANTILLAS,
    OPCIONES_REINICIAR,
    OPCIONES_REVISION_BLOQUEANTE,
    OPCIONES_REVISION_VALIDO,
    PREFIJO_BORRADOR_ACTUALIZADO,
    PREFIJO_CONTINUAR_PROPIO,
    PREFIJO_DATOS_SANITIZADOS,
    PREFIJO_ERROR_APROBACION,
    PREFIJO_METADATOS_REGISTRADOS,
    PREFIJO_SIN_DUPLICADOS,
    msg_articulo_aprobado,
    msg_articulo_muy_largo,
    msg_coincidencia,
    msg_enriquecer_cargado,
    msg_pedir_tag_adicional,
    prefijo_borrador_creado,
    prefijo_borrador_enriquecido,
)
from baco.server.services.orquestador.sesion import SesionChat
from baco.server.services.orquestador.validaciones import (
    actualizar_metadatos_sesion,
    avanzar_a_metadatos_o_revision,
    cargar_datos_articulo,
    combinar_tags,
    construir_respuesta,
    extraer_tipo_plantilla,
    normalizar_coincidencias,
    parsear_metadatos_mensaje,
    validar_borrador,
    validar_longitud,
    validar_longitud_maxima,
)


async def handle_esperando_titulo(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    titulo = (req.titulo or req.mensaje or "").strip()
    err = validar_longitud(titulo, TITULO_MIN, TITULO_MAX, "título")
    if err:
        return construir_respuesta(sesion, err, [])

    sesion.titulo = titulo
    actualizar_metadatos_sesion(sesion, req)

    res_tit = await run_in_threadpool(buscador.evaluar_titulo, titulo, 1)
    if res_tit and res_tit.get("coincidencias"):
        sesion.coincidencias = normalizar_coincidencias(
            res_tit["coincidencias"], mensaje=res_tit.get("mensaje", "")
        )
        sesion.estado = EstadoFlujo.DECISION_TITULO
        primero = sesion.coincidencias[0]
        return construir_respuesta(
            sesion,
            msg_coincidencia(res_tit["mensaje"], primero.titulo, primero.url),
            OPCIONES_ENRIQUECER_DESCARTAR,
        )

    sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
    return construir_respuesta(sesion, MSG_SIN_COINCIDENCIAS_TITULO, [])


async def handle_decision_titulo(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    if opcion == "enriquecer":
        elegido = sesion.coincidencias[0]
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        if validar_longitud_maxima(texto_base, TEXTO_MAX, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_enviado = (req.texto or "").strip()
        sanit_env = sanitizar_borrador(texto=texto_enviado)
        texto_enviado_limpio = sanit_env["texto_sanitizado"]
        aviso_priv = sanit_env.get("aviso_privacidad")

        if texto_enviado_limpio and texto_base and texto_base not in texto_enviado_limpio:
            texto_consolidado = f"{texto_base}\n\n{texto_enviado_limpio}"
        else:
            texto_consolidado = texto_enviado_limpio or texto_base

        sesion.borrador = BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=elegido.id,
            articulo_original_url=elegido.url,
            titulo=elegido.titulo,
            texto=texto_consolidado,
            tipo_plantilla=extraer_tipo_plantilla(tags_ini),
            categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
            tags=tags_ini,
        )
        sesion.texto = sesion.borrador.texto

        if not texto_enviado:
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            return construir_respuesta(
                sesion,
                msg_enriquecer_cargado(elegido.id, elegido.titulo),
                ["descartar", "reiniciar"],
            )

        err = validar_longitud(texto_consolidado, TEXTO_MIN, TEXTO_MAX, "texto")
        if err:
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            return construir_respuesta(sesion, err, [])

        return avanzar_a_metadatos_o_revision(
            sesion, prefijo_borrador_creado(elegido.id), aviso_privacidad=aviso_priv
        )

    if opcion in ("descartar", "continuar"):
        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(sesion, MSG_DESCARTAR_COINCIDENCIA_TITULO, [])

    return construir_respuesta(sesion, MSG_ELEGIR_ENRIQUECER_O_DESCARTAR, OPCIONES_ENRIQUECER_DESCARTAR)


async def handle_esperando_texto(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    texto_raw = (req.texto or req.mensaje or "").strip()
    if not texto_raw:
        return construir_respuesta(sesion, MSG_TEXTO_VACIO, [])

    actualizar_metadatos_sesion(sesion, req)

    if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
        texto_base = ""
        if sesion.coincidencias and sesion.coincidencias[0].texto_original:
            texto_base = sesion.coincidencias[0].texto_original.strip()
        elif sesion.borrador.texto:
            texto_base = sesion.borrador.texto.strip()

        sanit_ap = sanitizar_borrador(texto=texto_raw)
        texto_aporte = sanit_ap["texto_sanitizado"]
        aviso_priv = sanit_ap.get("aviso_privacidad")

        if texto_aporte and texto_base and texto_base not in texto_aporte:
            texto_consolidado = f"{texto_base}\n\n{texto_aporte}"
        else:
            texto_consolidado = texto_aporte or texto_base

        err = validar_longitud(texto_consolidado, TEXTO_MIN, TEXTO_MAX, "texto")
        if err:
            return construir_respuesta(sesion, err, [])

        sesion.borrador.texto = texto_consolidado
        sesion.texto = texto_consolidado
        if req.categoria_id is not None:
            sesion.borrador.categoria_id = req.categoria_id
        if req.tags is not None:
            sesion.borrador.tags = req.tags
        return avanzar_a_metadatos_o_revision(
            sesion, prefijo_borrador_creado(sesion.borrador.articulo_original_id), aviso_privacidad=aviso_priv
        )

    err = validar_longitud(texto_raw, TEXTO_MIN, TEXTO_MAX, "texto")
    if err:
        return construir_respuesta(sesion, err, [])

    sesion.texto = texto_raw

    sanit_txt = sanitizar_borrador(texto=texto_raw)
    texto_busqueda = sanit_txt["texto_sanitizado"]
    aviso_privacidad = sanit_txt.get("aviso_privacidad")

    res_txt = await run_in_threadpool(buscador.evaluar_texto, texto_busqueda, True, sesion.titulo, 1)
    if res_txt and res_txt.get("coincidencias"):
        sesion.coincidencias = normalizar_coincidencias(
            res_txt["coincidencias"], mensaje=res_txt.get("mensaje", "")
        )
        sesion.estado = EstadoFlujo.DECISION_TEXTO
        primero = sesion.coincidencias[0]
        return construir_respuesta(
            sesion,
            msg_coincidencia(res_txt["mensaje"], primero.titulo, primero.url),
            OPCIONES_ENRIQUECER_CONTINUAR,
            aviso_privacidad=aviso_privacidad,
        )

    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=sesion.titulo,
        texto=sesion.texto,
        tipo_plantilla=extraer_tipo_plantilla(sesion.tags),
        categoria_id=sesion.categoria_id,
        tags=list(sesion.tags),
    )
    return avanzar_a_metadatos_o_revision(
        sesion, PREFIJO_SIN_DUPLICADOS, aviso_privacidad=aviso_privacidad
    )


async def handle_decision_texto(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    actualizar_metadatos_sesion(sesion, req)

    if opcion == "enriquecer":
        elegido = sesion.coincidencias[0]
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        if validar_longitud_maxima(texto_base, TEXTO_MAX, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_aporte = (req.texto or sesion.texto or "").strip()
        sanit_ap = sanitizar_borrador(texto=texto_aporte)
        texto_aporte_limpio = sanit_ap["texto_sanitizado"]
        aviso_priv = sanit_ap.get("aviso_privacidad")

        if texto_aporte_limpio and texto_base and texto_base not in texto_aporte_limpio:
            texto_enriquecido = f"{texto_base}\n\n{texto_aporte_limpio}"
        else:
            texto_enriquecido = texto_aporte_limpio or texto_base

        if validar_longitud_maxima(texto_enriquecido, TEXTO_MAX, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX), ["descartar", "reiniciar"])

        sesion.borrador = BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=elegido.id,
            articulo_original_url=elegido.url,
            titulo=elegido.titulo,
            texto=texto_enriquecido,
            tipo_plantilla=extraer_tipo_plantilla(tags_ini),
            categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
            tags=tags_ini,
        )
        return avanzar_a_metadatos_o_revision(
            sesion, prefijo_borrador_enriquecido(elegido.id), aviso_privacidad=aviso_priv
        )

    if opcion in ("continuar", "descartar"):
        sesion.borrador = BorradorSesion(
            modo="nuevo",
            titulo=sesion.titulo,
            texto=sesion.texto,
            tipo_plantilla=extraer_tipo_plantilla(sesion.tags),
            categoria_id=sesion.categoria_id,
            tags=list(sesion.tags),
        )
        return avanzar_a_metadatos_o_revision(sesion, PREFIJO_CONTINUAR_PROPIO)

    return construir_respuesta(sesion, MSG_ELEGIR_ENRIQUECER_O_CONTINUAR, OPCIONES_ENRIQUECER_CONTINUAR)


async def handle_esperando_plantilla(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if req.categoria_id is not None:
        b.categoria_id = req.categoria_id

    opcion_plantilla = opcion or req.texto or req.mensaje or ""
    plantilla = extraer_tipo_plantilla(req.tags or [], opcion_plantilla)
    if not plantilla:
        return construir_respuesta(sesion, MSG_ELEGIR_PLANTILLA, OPCIONES_PLANTILLAS)

    b.tipo_plantilla = plantilla
    b.tags = combinar_tags(plantilla, b.tags, req.tags or [])
    if b.categoria_id is None:
        b.categoria_id = sesion.categoria_id or 1
    return avanzar_a_metadatos_o_revision(sesion)


async def handle_esperando_metadatos(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if req.categoria_id is not None:
        b.categoria_id = req.categoria_id

    texto_fuente = req.mensaje or req.texto or req.accion
    nuevos_tags, cat_res = parsear_metadatos_mensaje(
        req.mensaje, req.tags, req.categoria_id, texto_fallback=texto_fuente
    )
    if cat_res is not None:
        b.categoria_id = cat_res

    if b.categoria_id is None:
        b.categoria_id = sesion.categoria_id or 1

    b.tags = combinar_tags(b.tipo_plantilla, b.tags, nuevos_tags)
    if len(b.tags) < 2:
        return construir_respuesta(sesion, msg_pedir_tag_adicional(b.tipo_plantilla), [])

    msg, ops = validar_borrador(sesion, PREFIJO_METADATOS_REGISTRADOS)
    return construir_respuesta(sesion, msg, ops)


async def handle_revision_borrador(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    texto_edicion = req.texto
    if texto_edicion is None and opcion == "editar" and req.mensaje and req.mensaje.strip().lower() != "editar":
        texto_edicion = req.mensaje

    hubo_cambios = any(v is not None for v in (req.titulo, texto_edicion, req.categoria_id, req.tags))

    if opcion == "sanitizar":
        limpio = sanitizar_borrador(texto=req.texto or b.texto, titulo=req.titulo or b.titulo)
        b.titulo = limpio["titulo_sanitizado"]
        b.texto = limpio["texto_sanitizado"]
        msg, ops = validar_borrador(sesion, PREFIJO_DATOS_SANITIZADOS)
        return construir_respuesta(sesion, msg, ops, aviso_privacidad=limpio.get("aviso_privacidad"))

    if hubo_cambios:
        ops_actuales = (
            OPCIONES_REVISION_VALIDO
            if (sesion.validacion and sesion.validacion.valido)
            else OPCIONES_REVISION_BLOQUEANTE
        )
        if req.titulo is not None:
            tit_nuevo = req.titulo.strip()
            err_tit = validar_longitud_maxima(tit_nuevo, TITULO_MAX, "título")
            if err_tit:
                return construir_respuesta(sesion, err_tit, ops_actuales)
            b.titulo = tit_nuevo

        if texto_edicion is not None:
            txt_nuevo = texto_edicion.strip()
            texto_base = ""
            if sesion.coincidencias and sesion.coincidencias[0].texto_original:
                texto_base = sesion.coincidencias[0].texto_original.strip()

            if b.modo == "enriquecimiento" and texto_base and texto_base not in txt_nuevo:
                txt_nuevo = f"{texto_base}\n\n{txt_nuevo}"

            err_txt = validar_longitud_maxima(txt_nuevo, TEXTO_MAX, "texto")
            if err_txt:
                return construir_respuesta(sesion, err_txt, ops_actuales)
            b.texto = txt_nuevo

        if req.categoria_id is not None:
            b.categoria_id = req.categoria_id
        if req.tags is not None:
            plantilla_nueva = extraer_tipo_plantilla(req.tags) or b.tipo_plantilla
            b.tipo_plantilla = plantilla_nueva
            b.tags = combinar_tags(plantilla_nueva, req.tags)

        msg, ops = validar_borrador(sesion, PREFIJO_BORRADOR_ACTUALIZADO)
        return construir_respuesta(sesion, msg, ops)

    if opcion == "editar":
        ops = (
            OPCIONES_REVISION_VALIDO
            if (sesion.validacion and sesion.validacion.valido)
            else OPCIONES_REVISION_BLOQUEANTE
        )
        return construir_respuesta(sesion, MSG_PEDIR_EDICION, ops)

    if opcion == "aprobar":
        if not sesion.validacion or not sesion.validacion.valido:
            msg, ops = validar_borrador(sesion, PREFIJO_ERROR_APROBACION)
            return construir_respuesta(sesion, msg, ops)
        limpio = sanitizar_borrador(texto=b.texto, titulo=b.titulo)
        b.titulo = limpio["titulo_sanitizado"]
        b.texto = limpio["texto_sanitizado"]
        sesion.estado = EstadoFlujo.APROBADO
        if sesion.validacion.status == "Listo con ajustes sugeridos":
            mensaje_aprobado = (
                f"Artículo '{b.titulo}' APROBADO: observaciones de estilo confirmadas por el redactor. "
                "Listo para publicación."
            )
        else:
            mensaje_aprobado = msg_articulo_aprobado(b.titulo)
        return construir_respuesta(
            sesion,
            mensaje_aprobado,
            OPCIONES_REINICIAR,
            aviso_privacidad=limpio.get("aviso_privacidad"),
        )

    if opcion == "rechazar":
        sesion.estado = EstadoFlujo.RECHAZADO
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    msg, ops = validar_borrador(sesion)
    return construir_respuesta(sesion, msg, ops)


EstadoHandler = Callable[
    [SesionChat, ChatOrquestadorRequest, str, BuscadorDuplicados],
    Coroutine[None, None, ChatOrquestadorResponse],
]

STATE_HANDLERS: Dict[EstadoFlujo, EstadoHandler] = {
    EstadoFlujo.ESPERANDO_TITULO: handle_esperando_titulo,
    EstadoFlujo.DECISION_TITULO: handle_decision_titulo,
    EstadoFlujo.ESPERANDO_TEXTO: handle_esperando_texto,
    EstadoFlujo.DECISION_TEXTO: handle_decision_texto,
    EstadoFlujo.ESPERANDO_PLANTILLA: handle_esperando_plantilla,
    EstadoFlujo.ESPERANDO_METADATOS: handle_esperando_metadatos,
    EstadoFlujo.REVISION_BORRADOR: handle_revision_borrador,
    EstadoFlujo.SUBSANANDO_BORRADOR: handle_revision_borrador,
}
