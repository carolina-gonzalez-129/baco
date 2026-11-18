from unittest.mock import MagicMock

import pytest

from baco.server.schemas.chat_orquestado import (
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.sesion import (
    BorradorSesion,
    SesionChat,
    gestor_sesiones,
)

TITULO_VALIDO = "Título Válido Para Pruebas De Orquestador"
TEXTO_VALIDO = (
    "Este es un texto suficientemente largo y descriptivo para cumplir con todas las validaciones "
    "de longitud mínima requeridas por el asistente de base de conocimiento de Finnegans."
)
TEXTO_EDITADO_VALIDO = (
    "Este es el texto modificado durante la revisión intermedia con suficiente contenido "
    "y longitud para superar todas las reglas de validación en una sola request."
)


@pytest.fixture
def mock_buscador():
    return MagicMock(spec=BuscadorDuplicados)


@pytest.mark.anyio
async def test_continuar_con_cambios_avanza_en_una_request(mock_buscador):
    """
    Arreglo 1: Si llega 'continuar' en REVISION_TIPO junto con cambios en el texto
    (hubo_cambios), aplica los cambios vía edicion.py y avanza a metadatos en la
    MISMA request sin obligar a dos llamadas.
    """
    sid = "test-continuar-con-cambios-una-request"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        texto_limpio=TEXTO_VALIDO,
        tipo_plantilla="instructivo",
        tags=["instructivo"],
        categoria_id=None,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_TIPO,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=["instructivo"],
        categoria_id=None,
        borrador=borrador,
        ultimas_opciones=["aplicar_plantilla", "continuar"],
    )
    gestor_sesiones.sesiones[sid] = sesion

    req = ChatOrquestadorRequest(
        session_id=sid,
        accion="continuar",
        texto=TEXTO_EDITADO_VALIDO,
    )
    resp = await manejar_turno(req, mock_buscador)

    # 1. Los cambios del texto fueron aplicados en el borrador
    assert TEXTO_EDITADO_VALIDO in sesion.borrador.texto_limpio

    # 2. En la MISMA request avanzó a ESPERANDO_METADATOS
    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert sesion.estado == EstadoFlujo.ESPERANDO_METADATOS
