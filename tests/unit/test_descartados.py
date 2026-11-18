from unittest.mock import MagicMock

import pytest

from baco.server.schemas.chat_orquestado import (
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador import descartar_borrador, manejar_turno
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos

TEXTO_VALIDO = (
    "Para configurar el punto de venta electrónico en el sistema Finnegans ERP es necesario ingresar "
    "al maestro de puntos de venta dentro del módulo de Ventas, asociar el certificado digital vigente "
    "otorgado por AFIP y verificar que el tipo de emisión esté habilitado para comprobantes electrónicos."
)


@pytest.fixture(autouse=True)
def limpiar_sesiones():
    SESIONES.clear()
    limpiar_cache_catalogos()
    yield
    SESIONES.clear()
    limpiar_cache_catalogos()


@pytest.fixture
def mock_buscador():
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.cur = None
    buscador.obtener_articulo.return_value = None
    buscador.evaluar_titulo.return_value = None
    buscador.evaluar_texto.return_value = None
    return buscador


# ==============================================================================
# Casos de exclusión por tipo de búsqueda
# ==============================================================================


@pytest.mark.anyio
async def test_busqueda_hash_titulo_excluye_articulo_descartado(mock_buscador):
    """Verifica que un artículo descartado no vuelva a ofrecerse por búsqueda exacta de hash de título."""
    sid = "test-descartado-hash-titulo"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TITULO,
        articulos_descartados_ids=[101],
    )
    SESIONES[sid] = sesion

    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Ya existe un artículo con exactamente este título, ¿te gustaría mejorarlo?",
        "coincidencias": [(101, "Configuración de Punto de Venta AFIP", "https://bc.finneg.com/t/101")],
    }

    req = ChatOrquestadorRequest(
        session_id=sid,
        mensaje="Configuración de Punto de Venta AFIP",
    )
    resp = await manejar_turno(req, mock_buscador)

    # Al estar descartado el id 101, no debe volver a ofrecerse en DECISION_TITULO
    assert resp.estado != EstadoFlujo.DECISION_TITULO
    assert not any(c.id == 101 for c in (resp.coincidencias or []))


@pytest.mark.anyio
async def test_busqueda_serie_excluye_articulo_descartado(mock_buscador):
    """Verifica que un artículo descartado no vuelva a ofrecerse por búsqueda de serie periódica."""
    sid = "test-descartado-serie"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TITULO,
        articulos_descartados_ids=[102],
    )
    SESIONES[sid] = sesion

    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "El título parece pertenecer a la serie 'Novedades de la Versión', ¿te gustaría actualizar la última entrada?",
        "coincidencias": [(102, "Novedades de la Versión - Mayo 2026", "https://bc.finneg.com/t/102")],
    }

    req = ChatOrquestadorRequest(
        session_id=sid,
        mensaje="Novedades de la Versión - Junio 2026",
    )
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado != EstadoFlujo.DECISION_TITULO
    assert not any(c.id == 102 for c in (resp.coincidencias or []))


@pytest.mark.anyio
async def test_busqueda_trigramas_excluye_articulo_descartado(mock_buscador):
    """Verifica que un artículo descartado no vuelva a ofrecerse por similitud trigramática de título."""
    sid = "test-descartado-trigramas"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TITULO,
        articulos_descartados_ids=[103],
    )
    SESIONES[sid] = sesion

    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Encontramos un artículo cuyo titulo es muy similar, ¿te gustaría mejorarlo?",
        "coincidencias": [(103, "Configuración de Puntos de Ventas AFIP", "https://bc.finneg.com/t/103")],
    }

    req = ChatOrquestadorRequest(
        session_id=sid,
        mensaje="Configuración de Puntos de Venta AFIP",
    )
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado != EstadoFlujo.DECISION_TITULO
    assert not any(c.id == 103 for c in (resp.coincidencias or []))


@pytest.mark.anyio
async def test_busqueda_hash_texto_excluye_articulo_descartado(mock_buscador):
    """Verifica que un artículo descartado no vuelva a ofrecerse por búsqueda exacta de hash de texto."""
    sid = "test-descartado-hash-texto"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo="Configuración de Facturación AFIP",
        articulos_descartados_ids=[104],
    )
    SESIONES[sid] = sesion

    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Ya existe un artículo con exactamente la misma descripción, ¿te gustaría mejorarlo?",
        "coincidencias": [(104, "Artículo con Mismo Texto", "https://bc.finneg.com/t/104")],
    }

    req = ChatOrquestadorRequest(
        session_id=sid,
        accion="confirmar_texto",
        texto=TEXTO_VALIDO,
    )
    resp = await manejar_turno(req, mock_buscador)

    # En handlers.py L449/L822 las coincidencias se filtran con 'c.id not in sesion.articulos_descartados_ids'
    assert resp.estado != EstadoFlujo.DECISION_TEXTO
    assert not any(c.id == 104 for c in (resp.coincidencias or []))


@pytest.mark.anyio
async def test_busqueda_embeddings_excluye_articulo_descartado(mock_buscador):
    """Verifica que un artículo descartado no vuelva a ofrecerse por similitud semántica (embeddings)."""
    sid = "test-descartado-embeddings"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo="Configuración de Facturación AFIP",
        articulos_descartados_ids=[105],
    )
    SESIONES[sid] = sesion

    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Ya existe un artículo que explica prácticamente lo mismo, ¿te gustaría mejorarlo?",
        "coincidencias": [(105, "Artículo con Semántica Similar", "https://bc.finneg.com/t/105")],
    }

    req = ChatOrquestadorRequest(
        session_id=sid,
        accion="confirmar_texto",
        texto=TEXTO_VALIDO,
    )
    resp = await manejar_turno(req, mock_buscador)

    # Filtrado exitosamente en handlers.py L449/L822
    assert resp.estado != EstadoFlujo.DECISION_TEXTO
    assert not any(c.id == 105 for c in (resp.coincidencias or []))


# ==============================================================================
# Casos de vaciado de la lista de descartados
# ==============================================================================


@pytest.mark.anyio
async def test_reiniciar_vacia_lista_de_articulos_descartados(mock_buscador):
    """Verifica que enviar la acción 'reiniciar' reinicie la sesión y vacíe articulos_descartados_ids."""
    sid = "test-reiniciar-descartados"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TITULO,
        articulos_descartados_ids=[101, 102, 103],
    )
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(
        session_id=sid,
        accion="reiniciar",
    )
    resp = await manejar_turno(req, mock_buscador)

    nueva_sesion = SESIONES.get(resp.session_id)
    assert nueva_sesion is not None
    assert nueva_sesion.articulos_descartados_ids == []


def test_descartar_borrador_vacia_lista_de_articulos_descartados():
    """Verifica que descartar_borrador vacíe articulos_descartados_ids de la sesión."""
    from baco.server.services.orquestador.sesion import gestor_sesiones

    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.articulos_descartados_ids = [201, 202]

    descartar_borrador(sid)

    assert sesion.articulos_descartados_ids == []
