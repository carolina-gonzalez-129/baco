
from baco.server.schemas.chat_orquestado import (
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.handlers import STATE_HANDLERS
from baco.server.services.orquestador.mensajes import (
    MENSAJE_BIENVENIDA,
    OPCIONES_REINICIAR,
    msg_sesion_finalizada,
)
from baco.server.services.orquestador.sesion import gestor_sesiones
from baco.server.services.orquestador.validaciones import (
    construir_respuesta,
    interpretar_opcion,
)

async def manejar_turno(
    req: ChatOrquestadorRequest, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    sesion, es_nueva = gestor_sesiones.obtener_o_crear(req.session_id)
    opcion = interpretar_opcion(req)

    if opcion == "reiniciar":
        gestor_sesiones.eliminar(sesion.session_id)
        sesion, _ = gestor_sesiones.obtener_o_crear(sesion.session_id)
        return construir_respuesta(sesion, MENSAJE_BIENVENIDA, [])

    entrada_titulo = (req.titulo or req.mensaje or "").strip()
    if es_nueva and not entrada_titulo and not req.accion:
        return construir_respuesta(sesion, MENSAJE_BIENVENIDA, [])

    handler = STATE_HANDLERS.get(sesion.estado)
    if not handler:
        return construir_respuesta(
            sesion,
            msg_sesion_finalizada(sesion.estado.value),
            OPCIONES_REINICIAR,
        )

    return await handler(sesion, req, opcion, buscador)
