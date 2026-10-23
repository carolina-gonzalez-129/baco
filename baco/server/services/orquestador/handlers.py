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
    MSG_ELEGIR_PLANTILLA,
    MSG_PEDIR_EDICION,
    MSG_RECHAZADO,
    MSG_SIN_COINCIDENCIAS_TITULO,
    OPCIONES_ENRIQUECER_CONTINUAR,
    OPCIONES_ENRIQUECER_DESCARTAR,
    OPCIONES_SERIE_DECISION,
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
    msg_actualizar_serie_cargado,
    msg_articulo_aprobado,
    msg_articulo_muy_largo,
    msg_coincidencia,
    msg_enriquecer_cargado,
    msg_error_longitud_maxima,
    msg_error_longitud_minima,
    msg_opcion_invalida,
    msg_pedir_tag_adicional,
    msg_texto_vacio,
    prefijo_borrador_creado,
    prefijo_borrador_enriquecido,
)
from baco.server.services.orquestador.sesion import SesionChat
from baco.server.services.orquestador.validaciones import (
    actualizar_metadatos_sesion,
    avanzar_a_metadatos_o_revision,
    cargar_datos_articulo,
    combinar_tags,
    consolidar_texto_enriquecimiento,
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
    if not titulo:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(sesion, msg_error_longitud_minima("título", TITULO_MIN, intento), [])

    if len(titulo) < TITULO_MIN:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(sesion, msg_error_longitud_minima("título", TITULO_MIN, intento), [])

    if len(titulo) > TITULO_MAX:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(sesion, msg_error_longitud_maxima("título", TITULO_MAX, intento), [])

    sesion.limpiar_fallos("ESPERANDO_TITULO")
    sesion.titulo = titulo
    actualizar_metadatos_sesion(sesion, req)

    res_tit = await run_in_threadpool(buscador.evaluar_titulo, titulo, 1)
    if res_tit and res_tit.get("coincidencias"):
        es_serie = "serie" in (res_tit.get("mensaje") or "").lower()
        coincs = normalizar_coincidencias(
            res_tit["coincidencias"],
            mensaje=res_tit.get("mensaje", ""),
            tipo_coincidencia="serie" if es_serie else "duplicado",
        )
        if coincs:
            sesion.coincidencias = coincs
            sesion.estado = EstadoFlujo.DECISION_TITULO
            primero = sesion.coincidencias[0]
            ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
            return construir_respuesta(
                sesion,
                msg_coincidencia(res_tit["mensaje"], primero.titulo, primero.url),
                ops,
            )

    sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
    return construir_respuesta(sesion, MSG_SIN_COINCIDENCIAS_TITULO, ["volver"])


async def handle_decision_titulo(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    if opcion in ("enriquecer", "actualizar"):
        sesion.limpiar_fallos("DECISION_TITULO")
        if not sesion.coincidencias:
            sesion.estado = EstadoFlujo.ESPERANDO_TITULO
            return construir_respuesta(
                sesion,
                "[Placeholder] No se encontró la coincidencia previa seleccionada. Por favor, ingresá el título de tu artículo:",
                [],
            )
        elegido = sesion.coincidencias[0]
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        if validar_longitud_maxima(texto_base, TEXTO_MAX, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_enviado = (req.texto or "").strip()
        texto_consolidado, aviso_priv = consolidar_texto_enriquecimiento(texto_base, texto_enviado)

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
            es_serie = elegido.tipo_coincidencia == "serie"
            msg_carga = (
                msg_actualizar_serie_cargado(elegido.id, elegido.titulo)
                if es_serie
                else msg_enriquecer_cargado(elegido.id, elegido.titulo)
            )
            return construir_respuesta(
                sesion,
                msg_carga,
                ["descartar", "volver", "reiniciar"],
            )

        err = validar_longitud(texto_consolidado, TEXTO_MIN, TEXTO_MAX, "texto")
        if err:
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            return construir_respuesta(sesion, err, ["descartar", "volver"])

        return avanzar_a_metadatos_o_revision(
            sesion, prefijo_borrador_creado(elegido.id), aviso_privacidad=aviso_priv
        )

    if opcion in ("descartar", "continuar"):
        sesion.limpiar_fallos("DECISION_TITULO")
        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(sesion, MSG_DESCARTAR_COINCIDENCIA_TITULO, ["volver"])

    if opcion == "volver":
        sesion.limpiar_fallos("DECISION_TITULO")
        sesion.coincidencias = []
        sesion.estado = EstadoFlujo.ESPERANDO_TITULO
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Ingresá un nuevo título para tu artículo:",
            [],
        )

    intento = sesion.registrar_fallo("DECISION_TITULO")
    elegido = sesion.coincidencias[0] if sesion.coincidencias else None
    es_serie = elegido and elegido.tipo_coincidencia == "serie"
    ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
    return construir_respuesta(sesion, msg_opcion_invalida(intento), ops)


async def handle_esperando_texto(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    if opcion == "volver":
        sesion.limpiar_fallos("ESPERANDO_TEXTO")
        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            sesion.estado = EstadoFlujo.DECISION_TITULO
            elegido = sesion.coincidencias[0] if sesion.coincidencias else None
            es_serie = elegido and elegido.tipo_coincidencia == "serie"
            ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
            return construir_respuesta(
                sesion,
                "[Placeholder] Volvemos al paso anterior. ¿Deseás enriquecer el artículo encontrado o descartarlo?",
                ops,
            )
        sesion.estado = EstadoFlujo.ESPERANDO_TITULO
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Ingresá un nuevo título para tu artículo:",
            [],
        )

    if opcion in ("descartar", "continuar"):
        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            sesion.borrador = None
            sesion.coincidencias = []
            sesion.limpiar_fallos("ESPERANDO_TEXTO")
            texto_directo = (req.texto or "").strip()
            if not texto_directo:
                return construir_respuesta(
                    sesion,
                    "[Placeholder] Descartamos el artículo existente. Ingresá el texto o los pasos para redactar tu propio artículo:",
                    ["volver"],
                )

    texto_raw = (req.texto or req.mensaje or "").strip()
    if not texto_raw:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO")
        ops_texto = ["descartar", "volver"] if (sesion.borrador and sesion.borrador.modo == "enriquecimiento") else ["volver"]
        return construir_respuesta(sesion, msg_texto_vacio(intento), ops_texto)

    sesion.limpiar_fallos("ESPERANDO_TEXTO")
    actualizar_metadatos_sesion(sesion, req)

    if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
        texto_base = ""
        if sesion.coincidencias and sesion.coincidencias[0].texto_original:
            texto_base = sesion.coincidencias[0].texto_original.strip()
        elif sesion.borrador.texto:
            texto_base = sesion.borrador.texto.strip()

        texto_consolidado, aviso_priv = consolidar_texto_enriquecimiento(texto_base, texto_raw)

        if len(texto_consolidado) < TEXTO_MIN:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MIN")
            return construir_respuesta(sesion, msg_error_longitud_minima("texto", TEXTO_MIN, intento), [])

        if len(texto_consolidado) > TEXTO_MAX:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
            return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX, intento), [])

        sesion.borrador.texto = texto_consolidado
        sesion.texto = texto_consolidado
        if req.categoria_id is not None:
            sesion.borrador.categoria_id = req.categoria_id
        if req.tags is not None:
            sesion.borrador.tags = req.tags
        return avanzar_a_metadatos_o_revision(
            sesion, prefijo_borrador_creado(sesion.borrador.articulo_original_id), aviso_privacidad=aviso_priv
        )

    if len(texto_raw) < TEXTO_MIN:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MIN")
        return construir_respuesta(sesion, msg_error_longitud_minima("texto", TEXTO_MIN, intento), [])

    if len(texto_raw) > TEXTO_MAX:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
        return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX, intento), [])

    sesion.texto = texto_raw

    sanit_txt = sanitizar_borrador(texto=texto_raw)
    texto_busqueda = sanit_txt["texto_sanitizado"]
    aviso_privacidad = sanit_txt.get("aviso_privacidad")

    res_txt = await run_in_threadpool(buscador.evaluar_texto, texto_busqueda, True, sesion.titulo, 1)
    if res_txt and res_txt.get("coincidencias"):
        coincs = normalizar_coincidencias(
            res_txt["coincidencias"], mensaje=res_txt.get("mensaje", ""), tipo_coincidencia="semantico"
        )
        if coincs:
            sesion.coincidencias = coincs
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
        sesion.limpiar_fallos("DECISION_TEXTO")
        if not sesion.coincidencias:
            return construir_respuesta(
                sesion,
                "[Placeholder] No se encontró el artículo coincidente para enriquecer. Tocá 'continuar' para usar tu propio texto:",
                ["continuar", "reiniciar"],
            )
        elegido = sesion.coincidencias[0]
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        if validar_longitud_maxima(texto_base, TEXTO_MAX, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_aporte = (req.texto or sesion.texto or "").strip()
        texto_enriquecido, aviso_priv = consolidar_texto_enriquecimiento(texto_base, texto_aporte)

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
        sesion.limpiar_fallos("DECISION_TEXTO")
        sesion.borrador = BorradorSesion(
            modo="nuevo",
            titulo=sesion.titulo,
            texto=sesion.texto,
            tipo_plantilla=extraer_tipo_plantilla(sesion.tags),
            categoria_id=sesion.categoria_id,
            tags=list(sesion.tags),
        )
        return avanzar_a_metadatos_o_revision(sesion, PREFIJO_CONTINUAR_PROPIO)

    if opcion == "volver":
        sesion.limpiar_fallos("DECISION_TEXTO")
        sesion.coincidencias = []
        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Ingresá el texto corregido para tu artículo:",
            ["volver"],
        )

    intento = sesion.registrar_fallo("DECISION_TEXTO")
    return construir_respuesta(sesion, msg_opcion_invalida(intento), OPCIONES_ENRIQUECER_CONTINUAR)


async def handle_esperando_plantilla(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    if opcion == "volver":
        sesion.limpiar_fallos("ESPERANDO_PLANTILLA")
        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Ingresá el texto actualizado para tu artículo:",
            ["volver"],
        )

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
    if opcion == "volver":
        sesion.limpiar_fallos("ESPERANDO_METADATOS")
        sesion.estado = EstadoFlujo.ESPERANDO_PLANTILLA
        if b:
            b.tipo_plantilla = None
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos a la selección de formato. ¿Qué plantilla preferís para este artículo?",
            OPCIONES_PLANTILLAS,
        )

    if req.categoria_id is not None:
        b.categoria_id = req.categoria_id

    texto_fuente = req.mensaje or req.texto or req.accion
    nuevos_tags, cat_res = parsear_metadatos_mensaje(
        req.mensaje,
        req.tags,
        req.categoria_id,
        texto_fallback=texto_fuente,
        categorias_disponibles=sesion.categorias_disponibles,
        tags_disponibles=sesion.tags_disponibles,
    )
    if cat_res is not None:
        b.categoria_id = cat_res

    if b.categoria_id is None:
        b.categoria_id = sesion.categoria_id or 1

    b.tags = combinar_tags(b.tipo_plantilla, b.tags, nuevos_tags)
    sesion.tags = list(b.tags)
    if len(b.tags) < 2:
        intento = sesion.registrar_fallo("ESPERANDO_METADATOS")
        return construir_respuesta(sesion, msg_pedir_tag_adicional(b.tipo_plantilla or "", intento), [])

    sesion.limpiar_fallos("ESPERANDO_METADATOS")
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

    if sesion.confirmando_rechazo:
        if opcion in ("confirmar_rechazo", "rechazar"):
            sesion.confirmando_rechazo = False
            sesion.estado = EstadoFlujo.RECHAZADO
            return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)
        if opcion == "volver":
            sesion.confirmando_rechazo = False
            msg, ops = validar_borrador(sesion)
            return construir_respuesta(
                sesion,
                "[Placeholder] Operación cancelada. Mantenemos tu borrador intacto:\n\n" + msg,
                ops,
            )
        if opcion in ("editar", "sanitizar", "aprobar") or hubo_cambios:
            sesion.confirmando_rechazo = False
        else:
            return construir_respuesta(
                sesion,
                "[Placeholder] Por favor confirmá si querés descartar el artículo tocando 'confirmar_rechazo' o 'volver' para continuar trabajando en él.",
                ["confirmar_rechazo", "volver"],
            )

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

    if opcion == "volver":
        sesion.limpiar_fallos("REVISION_BORRADOR")
        if b and b.modo == "enriquecimiento":
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            return construir_respuesta(
                sesion,
                "[Placeholder] Volvemos al paso anterior. Ingresá el texto o tu aporte actualizado para el artículo:",
                ["descartar", "volver"],
            )
        sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Podés redefinir las etiquetas o tags para clasificar tu artículo:",
            ["volver"],
        )

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
                f"¡Impecable! Tu artículo '{b.titulo}' está muy bien formulado "
                "(observaciones de estilo confirmadas por el redactor). "
                "Si querés comenzar con otro tema, tocá 'reiniciar'."
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
        sesion.confirmando_rechazo = True
        return construir_respuesta(
            sesion,
            "[Placeholder] ¿Estás seguro de que querés descartar todo el artículo? Se perderán los cambios realizados en esta sesión.",
            ["confirmar_rechazo", "volver"],
        )

    if opcion == "confirmar_rechazo":
        sesion.confirmando_rechazo = False
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
