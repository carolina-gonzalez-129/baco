from unittest.mock import MagicMock
import pytest

from baco.server.schemas.chat_orquestado import (
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.sesion import (
    SESIONES,
    SesionChat,
    clave_busqueda,
)


@pytest.fixture
def mock_buscador():
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.cur = None
    buscador.obtener_articulo.return_value = None
    return buscador


@pytest.mark.anyio
async def test_descartar_repito_mismo_titulo_no_busca_cambio_titulo_si_busca(mock_buscador):
    sid = "test-sesion-descarte-titulo"
    SESIONES[sid] = SesionChat(session_id=sid, estado=EstadoFlujo.ESPERANDO_TITULO)

    # 1. Configurar coincidencia en evaluar_titulo
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Ya existe un artículo con exactamente este título",
        "link": "https://bc.finneg.com/t/101",
        "coincidencias": [(101, "Configuración de Facturación Electrónica", "https://bc.finneg.com/t/101")],
    }

    # 2. Enviar título inicial -> detecta coincidencia y pasa a DECISION_TITULO
    titulo_original = "Configuración de Facturación Electrónica"
    req_tit = ChatOrquestadorRequest(session_id=sid, titulo=titulo_original)
    resp_tit = await manejar_turno(req_tit, mock_buscador)

    assert resp_tit.estado == EstadoFlujo.DECISION_TITULO
    assert mock_buscador.evaluar_titulo.call_count == 1
    mock_buscador.evaluar_titulo.assert_called_with(titulo_original, 1)

    # 3. Usuario descarta la coincidencia -> pasa a ESPERANDO_TEXTO
    req_desc = ChatOrquestadorRequest(session_id=sid, accion="descartar")
    resp_desc = await manejar_turno(req_desc, mock_buscador)
    assert resp_desc.estado == EstadoFlujo.ESPERANDO_TEXTO

    # Verificar que la clave quedó registrada en memoria de la sesión
    clave_esperada = clave_busqueda("titulo", titulo_original)
    assert clave_esperada in SESIONES[sid].busquedas_descartadas

    # 4. Volver a ESPERANDO_TITULO con 'volver'
    req_volver = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp_volver = await manejar_turno(req_volver, mock_buscador)
    assert resp_volver.estado == EstadoFlujo.ESPERANDO_TITULO
    # Regla: volver NO borra busquedas_descartadas
    assert clave_esperada in SESIONES[sid].busquedas_descartadas

    # 5. Repetir el mismo título (incluso con mayúsculas/espacios variados)
    mock_buscador.evaluar_titulo.reset_mock()
    titulo_repetido = "  configuración DE facturación electrónica  "
    req_repetido = ChatOrquestadorRequest(session_id=sid, titulo=titulo_repetido)
    resp_repetido = await manejar_turno(req_repetido, mock_buscador)

    # NO se debió ejecutar evaluar_titulo
    mock_buscador.evaluar_titulo.assert_not_called()
    assert resp_repetido.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert (
        resp_repetido.mensaje
        == "Omití las coincidencias que ya descartaste. No encontré nada nuevo. Por favor, enviame el texto o desarrollo del artículo."
    )

    # 6. Volver a ESPERANDO_TITULO y enviar un título DISTINTO
    await manejar_turno(req_volver, mock_buscador)
    titulo_distinto = "Configuración de Módulo de Tesorería General"
    mock_buscador.evaluar_titulo.return_value = None
    req_distinto = ChatOrquestadorRequest(session_id=sid, titulo=titulo_distinto)
    resp_distinto = await manejar_turno(req_distinto, mock_buscador)

    # Para el nuevo título SÍ se ejecuta la búsqueda y mantiene el mensaje original
    mock_buscador.evaluar_titulo.assert_called_once_with(titulo_distinto, 1)
    assert resp_distinto.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert (
        resp_distinto.mensaje
        == "No encontré nada similar. Por favor, enviame el texto o desarrollo del artículo."
    )


@pytest.mark.anyio
async def test_descartar_repito_mismo_texto_no_busca_cambio_texto_si_busca(mock_buscador):
    sid = "test-sesion-descarte-texto"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo="Gestión de Cobranzas y Retenciones Bancarias",
    )

    texto_original = "Este es un texto suficientemente largo que supera el umbral mínimo para evaluar duplicados y probar descarte."
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Ya existe un artículo con la misma descripción",
        "link": "https://bc.finneg.com/t/202",
        "coincidencias": [(202, "Cobranzas Bancarias", "https://bc.finneg.com/t/202")],
    }

    # 1. Enviar texto inicial -> detecta coincidencia y pasa a DECISION_TEXTO
    req_txt = ChatOrquestadorRequest(session_id=sid, accion="confirmar_texto", texto=texto_original)
    resp_txt = await manejar_turno(req_txt, mock_buscador)

    assert resp_txt.estado == EstadoFlujo.DECISION_TEXTO
    assert mock_buscador.evaluar_texto.call_count == 1

    # 2. Usuario descarta la coincidencia
    req_desc = ChatOrquestadorRequest(session_id=sid, accion="descartar")
    resp_desc = await manejar_turno(req_desc, mock_buscador)

    # Verificar que la clave del texto quedó registrada en busquedas_descartadas
    clave_txt = clave_busqueda("texto", texto_original)
    assert clave_txt in SESIONES[sid].busquedas_descartadas

    # 3. Volver a ESPERANDO_TEXTO
    req_volver = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp_volver = await manejar_turno(req_volver, mock_buscador)
    # Regla: volver NO borra busquedas_descartadas
    assert clave_txt in SESIONES[sid].busquedas_descartadas

    # 4. Enviar el mismo texto de nuevo
    mock_buscador.evaluar_texto.reset_mock()
    texto_repetido = "  este es un texto suficientemente largo que supera el umbral mínimo para evaluar duplicados y probar descarte.  "
    req_txt_repetido = ChatOrquestadorRequest(session_id=sid, accion="confirmar_texto", texto=texto_repetido)
    resp_txt_repetido = await manejar_turno(req_txt_repetido, mock_buscador)

    # NO se debió ejecutar evaluar_texto
    mock_buscador.evaluar_texto.assert_not_called()
    assert "Omití las coincidencias que ya descartaste" in resp_txt_repetido.mensaje

    # 5. Volver y enviar un texto DISTINTO
    await manejar_turno(req_volver, mock_buscador)
    texto_distinto = "Texto totalmente diferente para verificar que cuando cambia el contenido sí se dispara la búsqueda en evaluar_texto."
    mock_buscador.evaluar_texto.return_value = None
    req_txt_distinto = ChatOrquestadorRequest(session_id=sid, accion="confirmar_texto", texto=texto_distinto)
    resp_txt_distinto = await manejar_turno(req_txt_distinto, mock_buscador)

    # Para el texto nuevo SÍ se ejecuta la búsqueda
    assert mock_buscador.evaluar_texto.call_count == 1
