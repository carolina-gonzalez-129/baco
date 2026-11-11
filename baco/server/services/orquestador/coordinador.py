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
    MSG_CAMBIO_PLANTILLA_DESCARTADO,
    OPCIONES_FINALIZADO,
    MSG_SESION_EXPIRADA,
    MSG_OPCION_NO_DISPONIBLE,
    OPCIONES_REINICIAR,
    msg_cambios_guardados,
    msg_sesion_finalizada,
    obtener_ayuda_contextual,
)
from baco.server.services.orquestador.sesion import gestor_sesiones
from baco.server.services.orquestador.contrato import (
    es_accion,
    filtrar_campos_no_editables,
    opcion_permitida,
)
from baco.server.services.orquestador.validaciones import (
    cargar_catalogos_sesion,
    construir_respuesta,
    interpretar_opcion,
    validar_borrador,
)


async def manejar_turno(
    req: ChatOrquestadorRequest, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    # Si el turno descarta implícitamente un cambio de plantilla pendiente, se avisa.
    sesion_previa = gestor_sesiones.sesiones.get(req.session_id) if req.session_id else None
    pendiente_previo = getattr(sesion_previa, "plantilla_pendiente", None)
    opcion_turno = interpretar_opcion(req)
    resp = await _manejar_turno(req, buscador)
    if (
        pendiente_previo
        and sesion_previa.plantilla_pendiente is None
        and opcion_turno not in ("confirmar_plantilla", "cancelar_plantilla", "reiniciar")
    ):
        resp.mensaje = f"{MSG_CAMBIO_PLANTILLA_DESCARTADO}\n\n{resp.mensaje}"
    return resp


async def _manejar_turno(
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
        ops_previas = list(sesion.ultimas_opciones)
        nav_previa = list(sesion.ultima_navegacion)
        msg, ops = obtener_ayuda_contextual(sesion)
        resp_ayuda = construir_respuesta(sesion, msg, ops)
        # La ayuda no quita lo que el turno anterior ya habilitaba.
        sesion.ultimas_opciones = list(dict.fromkeys(ops_previas + sesion.ultimas_opciones))
        sesion.ultima_navegacion = list(dict.fromkeys(nav_previa + sesion.ultima_navegacion))
        return resp_ayuda

    entrada_titulo = (req.titulo or req.mensaje or "").strip()
    if es_nueva and not entrada_titulo and not req.accion:
        return construir_respuesta(sesion, MENSAJE_BIENVENIDA, [])

    # Contrato: solo se acepta una opción que el back devolvió en el turno anterior.
    if not es_nueva and es_accion(sesion, req, opcion) and not opcion_permitida(sesion, opcion):
        return construir_respuesta(
            sesion,
            MSG_OPCION_NO_DISPONIBLE,
            sesion.ultimas_opciones,
        )

    # Contrato: tipo, categoría y etiquetas fuera de `editables` se descartan con aviso.
    descartes_contrato = filtrar_campos_no_editables(sesion, req)
    hay_otra_cosa = any(
        v is not None and (not isinstance(v, str) or v.strip())
        for v in (req.accion, req.mensaje, req.titulo, req.texto, req.texto_editor,
                  req.tipo_plantilla, req.categoria_id, req.tags)
    )
    if descartes_contrato and not hay_otra_cosa:
        return construir_respuesta(
            sesion,
            msg_cambios_guardados([], descartes_contrato),
            sesion.ultimas_opciones,
        )

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

        if opcion == "continuar":
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
            # Detalle de lo guardado/descartado, seguido de los avisos que correspondan.
            partes_msg = [msg_cambios_guardados(
                res_edicion.cambios, descartes_contrato + list(res_edicion.descartes or [])
            )]
            partes_msg += [a for a in (res_edicion.aviso_skill_desactualizada, res_edicion.aviso) if a]
            mensaje_edicion = "\n\n".join(partes_msg)
            # En revisión, si el paso quedó bloqueado (p. ej. marcadores [Indicar...]) y se
            # guardaron cambios, se revalida: si se resolvieron, vuelve a habilitarse Continuar.
            if (
                sesion.estado in (EstadoFlujo.REVISION_TIPO, EstadoFlujo.REVISION_METADATOS)
                and sesion.validacion is not None
                and not sesion.validacion.valido
                and (res_edicion.cambios or res_edicion.descartes)
            ):
                mensaje_edicion, opciones_edicion = validar_borrador(
                    sesion, mensaje_edicion + "\n\n", reingreso=True
                )
            sesion.ultimas_opciones = list(opciones_edicion)
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
