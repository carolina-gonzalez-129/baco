
from baco.server.schemas.chat_orquestado import (
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.handlers import STATE_HANDLERS
from baco.server.services.orquestador.mensajes import (
    MENSAJE_BIENVENIDA,
    MSG_BORRADOR_FINALIZADO,
    MSG_CONFORMIDAD_REGISTRADA,
    OPCIONES_FINALIZADO,
    MSG_SESION_EXPIRADA,
    OPCIONES_CONFORMIDAD,
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

    if sesion.estado == EstadoFlujo.CONFORMIDAD_USUARIO:
        hubo_intento_edicion = bool(
            req.texto is not None
            or req.titulo is not None
            or req.categoria_id is not None
            or req.tags is not None
            or opcion in ("editar", "sanitizar", "volver")
        )
        if hubo_intento_edicion:
            sesion.estado = EstadoFlujo.REVISION_BORRADOR
            if sesion.borrador:
                sesion.borrador.conforme = False
                sesion.borrador.conforme_en = None
                sesion.borrador.conformidad_invalidada = True
        elif opcion == "copiar_borrador":
            return construir_respuesta(
                sesion,
                MSG_CONFORMIDAD_REGISTRADA,
                OPCIONES_CONFORMIDAD,
            )

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
            or opcion in ("editar", "sanitizar")
        )
        if hubo_intento_edicion:
            sesion.estado = EstadoFlujo.REVISION_BORRADOR
            if sesion.borrador:
                sesion.borrador.finalizado = False
        elif opcion == "copiar_borrador" or (not hubo_intento_edicion and not opcion):
            return construir_respuesta(
                sesion,
                MSG_BORRADOR_FINALIZADO,
                OPCIONES_FINALIZADO,
            )

    handler = STATE_HANDLERS.get(sesion.estado)
    if not handler:
        return construir_respuesta(
            sesion,
            msg_sesion_finalizada(sesion.estado.value),
            OPCIONES_REINICIAR,
        )

    return await handler(sesion, req, opcion, buscador)
