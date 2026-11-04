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
from baco.server.services.orquestador.handlers import (
    STATE_HANDLERS,
    gestionar_cambio_plantilla_pendiente,
)
from baco.server.services.orquestador.mensajes import (
    MENSAJE_BIENVENIDA,
    MSG_BORRADOR_FINALIZADO,
    OPCIONES_FINALIZADO,
    MSG_SESION_EXPIRADA,
    OPCIONES_REINICIAR,
    msg_cambios_guardados,
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
        # FINALIZADO es terminal: la edición ocurre antes, en EDICION_FINAL.
        return construir_respuesta(
            sesion,
            MSG_BORRADOR_FINALIZADO,
            OPCIONES_FINALIZADO,
        )

    if sesion.estado == EstadoFlujo.EDICION_FINAL:
        resp_plantilla, req = await gestionar_cambio_plantilla_pendiente(sesion, req, opcion)
        if resp_plantilla is not None:
            return resp_plantilla

    res_edicion = None
    if sesion.estado in ESTADOS_EDICION_LIBRE or sesion.estado == EstadoFlujo.EDICION_FINAL:
        res_edicion = aplicar_edicion_campos(sesion, req)
        req._res_edicion = res_edicion
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
            # En EDICION_FINAL, un cambio de plantilla sigue yendo al handler (reaplica la skill).
            and not (
                sesion.estado == EstadoFlujo.EDICION_FINAL
                and res_edicion.tipo_plantilla_nueva is not None
            )
        )
        if es_solo_edicion:
            opciones_edicion = res_edicion.opciones_sugeridas or sesion.ultimas_opciones
            sesion.ultimas_opciones = list(opciones_edicion)
            # Detalle de lo guardado/descartado, seguido de los avisos que correspondan.
            partes_msg = [msg_cambios_guardados(res_edicion.cambios, res_edicion.descartes)]
            partes_msg += [a for a in (res_edicion.aviso_skill_desactualizada, res_edicion.aviso) if a]
            mensaje_edicion = "\n\n".join(partes_msg)
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
