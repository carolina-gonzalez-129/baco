"""Rama arreglar-meta-datos: carga de categoría y tags por chat vs. panel.

1. Los metadatos heredados se precargan en el panel (sin banner ni botones
   Mantener / Elegir otros) y se confirman con "Enviar datos".
2. Con heredados sin mostrar, el texto libre del chat no se toma como tag.
3. Si la carga por chat completa los metadatos, no se avanza solo: se pide
   confirmar con "Enviar datos", igual que desde el panel.
4. La carga desde el panel (envía tags) sigue avanzando directo.
"""

from unittest.mock import MagicMock
import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador import manejar_turno
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos


TEXTO_VALIDO = (
    "Para configurar el punto de venta electrónico en el sistema Finnegans ERP es necesario ingresar "
    "al maestro de puntos de venta dentro del módulo de Ventas, asociar el certificado digital vigente "
    "otorgado por AFIP y verificar que el tipo de emisión esté habilitado para comprobantes electrónicos."
)
TITULO_VALIDO = "Configurar el punto de venta electrónico AFIP"
META_ANT = {"categoria_id": 5, "categoria_nombre": "Ventas", "tags": ["instructivo", "ventas"]}


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
    return buscador


def _sesion(sid, tags, categoria_id, heredados):
    borrador = BorradorSesion(
        modo="enriquecimiento" if heredados else "nuevo",
        articulo_original_id=505 if heredados else None,
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=categoria_id,
        categoria_nombre="Ventas" if categoria_id == 5 else None,
        tags=list(tags),
        metadatos_anteriores=dict(META_ANT) if heredados else None,
        metadatos_heredados_revisados=False,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_METADATOS,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=list(tags),
        categoria_id=categoria_id,
        borrador=borrador,
        metadatos_anteriores=dict(META_ANT) if heredados else None,
        metadatos_heredados_revisados=False,
    )
    SESIONES[sid] = sesion
    return sesion


@pytest.mark.anyio
async def test_heredados_se_precargan_sin_banner_y_piden_enviar_datos(mock_buscador):
    sesion = _sesion("meta-hola", ["instructivo"], None, heredados=True)
    # El front envía mensaje + categoria_id desde el chat.
    req = ChatOrquestadorRequest(session_id="meta-hola", mensaje="hola", categoria_id=5)
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert "hola" not in sesion.borrador.tags
    assert sesion.borrador.tags == ["instructivo", "ventas"]
    assert sesion.borrador.categoria_id == 5
    assert resp.aviso_metadatos_heredados is None
    assert resp.opciones == ["enviar_datos", "volver"]
    assert "Enviar datos" in resp.mensaje


@pytest.mark.anyio
async def test_heredados_precargados_se_confirman_con_enviar_datos(mock_buscador):
    _sesion("meta-enviar", ["instructivo"], None, heredados=True)
    await manejar_turno(ChatOrquestadorRequest(session_id="meta-enviar", mensaje="hola"), mock_buscador)
    resp = await manejar_turno(
        ChatOrquestadorRequest(session_id="meta-enviar", accion="enviar_datos"), mock_buscador
    )
    assert resp.estado == EstadoFlujo.REVISION_BORRADOR


@pytest.mark.anyio
async def test_carga_por_chat_completa_pide_enviar_datos(mock_buscador):
    sesion = _sesion("meta-chat", ["instructivo"], 5, heredados=False)
    req = ChatOrquestadorRequest(session_id="meta-chat", mensaje="facturacion", categoria_id=5)
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert "facturacion" in sesion.borrador.tags
    assert resp.opciones == ["enviar_datos", "volver"]
    assert "Enviar datos" in resp.mensaje

    resp2 = await manejar_turno(
        ChatOrquestadorRequest(session_id="meta-chat", accion="enviar_datos"), mock_buscador
    )
    assert resp2.estado == EstadoFlujo.REVISION_BORRADOR


@pytest.mark.anyio
async def test_carga_por_chat_incompleta_sigue_pidiendo_lo_que_falta(mock_buscador):
    sesion = _sesion("meta-incompleto", ["instructivo"], None, heredados=False)
    req = ChatOrquestadorRequest(session_id="meta-incompleto", accion="enviar_datos")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.opciones == ["volver"]
    assert "enviar_datos" not in sesion.borrador.tags


@pytest.mark.anyio
async def test_carga_desde_panel_avanza_directo(mock_buscador):
    _sesion("meta-panel", ["instructivo"], None, heredados=False)
    req = ChatOrquestadorRequest(
        session_id="meta-panel", tags=["instructivo", "facturacion"], categoria_id=5
    )
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
