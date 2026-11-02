from baco.server.schemas.chat_orquestado import (
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.edicion import (
    ESTADOS_EDICION_LIBRE,
    adoptar_resultado_skill_pendiente,
    aplicar_edicion_campos,
    categoria_difiere,
    handle_reaplicar_skill,
    plantilla_difiere,
    tags_difiere,
)
from baco.server.services.orquestador.validaciones import extraer_tipo_plantilla
from baco.server.services.orquestador.handlers import STATE_HANDLERS
from baco.server.services.orquestador.mensajes import (
    MENSAJE_BIENVENIDA,
    MSG_BORRADOR_FINALIZADO,
    OPCIONES_FINALIZADO,
    MSG_SESION_EXPIRADA,
    OPCIONES_REINICIAR,
    msg_sesion_finalizada,
    obtener_ayuda_contextual,
)
from baco.server.services.orquestador.sesion import gestor_sesiones
from baco.server.services.orquestador.validaciones import (
    cargar_catalogos_sesion,
    construir_respuesta,
    interpretar_opcion,
    validar_borrador,
)


async def manejar_turno(
    req: ChatOrquestadorRequest, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    sesion, es_nueva, fue_expirada = gestor_sesiones.obtener_o_crear(req.session_id)
    opcion = interpretar_opcion(req)

    if opcion == "reiniciar":
        gestor_sesiones.eliminar(sesion.session_id)
        sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
        await cargar_catalogos_sesion(sesion, buscador)
        return construir_respuesta(sesion, MENSAJE_BIENVENIDA, [])

    await cargar_catalogos_sesion(sesion, buscador)

    if fue_expirada:
        return construir_respuesta(sesion, MSG_SESION_EXPIRADA, OPCIONES_REINICIAR)

    if opcion == "ayuda":
        msg, ops = obtener_ayuda_contextual(sesion)
        return construir_respuesta(sesion, msg, ops)

    entrada_titulo = (req.titulo or req.mensaje or "").strip()
    if es_nueva and not entrada_titulo and not req.accion:
        return construir_respuesta(sesion, MENSAJE_BIENVENIDA, [])

    if sesion.estado == EstadoFlujo.FINALIZADO:
        if opcion == "volver":
            sesion.estado = EstadoFlujo.REVISION_BORRADOR
            if sesion.borrador:
                sesion.borrador.finalizado = False
            msg, ops = validar_borrador(sesion)
            return construir_respuesta(sesion, msg, ops)

        hubo_intento_edicion = bool(
            req.texto is not None
            or req.titulo is not None
            or req.categoria_id is not None
            or req.tags is not None
            or req.tipo_plantilla is not None
            or opcion in ("editar", "sanitizar")
        )
        if hubo_intento_edicion:
            txt_edicion = req.texto
            if txt_edicion is None and opcion == "editar" and req.mensaje and req.mensaje.strip().lower() != "editar":
                txt_edicion = req.mensaje

            tiene_datos_edicion = any(
                v is not None
                for v in (req.titulo, txt_edicion, req.categoria_id, req.tags, req.tipo_plantilla)
            )
            if tiene_datos_edicion:
                b_fin = sesion.borrador
                plantilla_fin = (
                    (b_fin.tipo_plantilla if b_fin else sesion.tipo_plantilla)
                    or extraer_tipo_plantilla((b_fin.tags if b_fin else sesion.tags) or [])
                )
                cambio_plantilla_fin = False
                if req.tipo_plantilla is not None:
                    try:
                        cambio_plantilla_fin = plantilla_difiere(req.tipo_plantilla, plantilla_fin)
                    except ValueError:
                        cambio_plantilla_fin = True
                if cambio_plantilla_fin or sesion.huella_difiere(
                    titulo=req.titulo,
                    texto=txt_edicion,
                    categoria_id=req.categoria_id,
                    tags=req.tags,
                ):
                    sesion.estado = EstadoFlujo.REVISION_BORRADOR
                    if sesion.borrador:
                        sesion.borrador.finalizado = False
                else:
                    return construir_respuesta(
                        sesion,
                        MSG_BORRADOR_FINALIZADO,
                        OPCIONES_FINALIZADO,
                    )
            else:
                sesion.estado = EstadoFlujo.REVISION_BORRADOR
                if sesion.borrador:
                    sesion.borrador.finalizado = False
        elif opcion == "copiar_borrador" or (not hubo_intento_edicion and not opcion):
            return construir_respuesta(
                sesion,
                MSG_BORRADOR_FINALIZADO,
                OPCIONES_FINALIZADO,
            )

    res_edicion = None
    if sesion.estado in ESTADOS_EDICION_LIBRE:
        res_edicion = aplicar_edicion_campos(sesion, req)
        if not res_edicion.ok:
            return construir_respuesta(
                sesion,
                res_edicion.error or "",
                sesion.ultimas_opciones,
            )

        if opcion == "reaplicar":
            return await handle_reaplicar_skill(sesion, req, buscador)

        if opcion in ("continuar", "continuar_revision"):
            adoptar_resultado_skill_pendiente(sesion)

        b_act = sesion.borrador
        tags_act = (b_act.tags if b_act else sesion.tags) or []
        plantilla_act = (
            (b_act.tipo_plantilla if b_act else sesion.tipo_plantilla)
            or extraer_tipo_plantilla(tags_act)
        )
        cat_act = b_act.categoria_id if b_act else sesion.categoria_id
        try:
            cambio_plantilla_req = plantilla_difiere(req.tipo_plantilla, plantilla_act)
        except ValueError:
            cambio_plantilla_req = True
        meta_o_plantilla_difiere = (
            cambio_plantilla_req
            or categoria_difiere(req.categoria_id, cat_act)
            or tags_difiere(req.tags, tags_act, plantilla=plantilla_act)
        )
        if req.titulo is not None or req.texto is not None:
            es_paso_metadatos_o_plantilla = sesion.estado in (
                EstadoFlujo.ESPERANDO_PLANTILLA,
                EstadoFlujo.ESPERANDO_METADATOS,
            ) and meta_o_plantilla_difiere
        else:
            es_paso_metadatos_o_plantilla = sesion.estado in (
                EstadoFlujo.ESPERANDO_PLANTILLA,
                EstadoFlujo.ESPERANDO_METADATOS,
            ) and (
                req.tipo_plantilla is not None
                or req.tags is not None
                or req.categoria_id is not None
            )
        tiene_campos_req = any(
            v is not None
            for v in (req.titulo, req.texto, req.tipo_plantilla, req.categoria_id, req.tags)
        )
        es_solo_edicion = (
            not (req.accion and req.accion.strip())
            and not (req.mensaje and req.mensaje.strip())
            and tiene_campos_req
            and not es_paso_metadatos_o_plantilla
        )
        if es_solo_edicion:
            opciones_edicion = res_edicion.opciones_sugeridas or sesion.ultimas_opciones
            sesion.ultimas_opciones = list(opciones_edicion)
            mensaje_edicion = res_edicion.aviso_skill_desactualizada or res_edicion.aviso or ""
            return construir_respuesta(
                sesion,
                mensaje_edicion,
                opciones_edicion,
                aviso_privacidad=res_edicion.aviso_privacidad,
            )

    handler = STATE_HANDLERS.get(sesion.estado)
    if not handler:
        return construir_respuesta(
            sesion,
            msg_sesion_finalizada(sesion.estado.value),
            OPCIONES_REINICIAR,
        )

    resp_handler = await handler(sesion, req, opcion, buscador)
    if res_edicion is not None and res_edicion.aviso_privacidad and not resp_handler.aviso_privacidad:
        resp_handler.aviso_privacidad = res_edicion.aviso_privacidad
    return resp_handler
