"""Contrato `guardan_campos`: las acciones declaradas viajan con los campos del panel y el back
los guarda antes de ejecutarlas (paso 2 post-demo: disparidad de contratos front/back)."""
from unittest.mock import MagicMock

import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    CoincidenciaArticulo,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador import manejar_turno
from baco.server.services.orquestador.mensajes import MSG_PEDIR_EDICION
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos

TITULO = "Cómo configurar el punto de venta electrónico AFIP"
TEXTO = (
    "Para configurar el punto de venta electrónico en el sistema Finnegans ERP es necesario ingresar "
    "al maestro de puntos de venta dentro del módulo de Ventas y asociar el certificado digital vigente."
)
TEXTO_EDITADO = TEXTO + " Después verificá que el tipo de emisión esté habilitado para comprobantes electrónicos."


@pytest.fixture(autouse=True)
def limpiar():
    SESIONES.clear()
    limpiar_cache_catalogos()
    yield
    SESIONES.clear()
    limpiar_cache_catalogos()


@pytest.fixture
def buscador():
    b = MagicMock(spec=BuscadorDuplicados)
    b.cur = None
    b.obtener_articulo.return_value = None
    return b


def _sesion_revision(sid, ultimas, **extra):
    borrador = BorradorSesion(
        modo="nuevo", titulo=TITULO, bloques_texto=[TEXTO], recursos={},
        tipo_plantilla="instructivo", tags=["instructivo"],
    )
    s = SesionChat(session_id=sid, estado=EstadoFlujo.REVISION_TIPO, titulo=TITULO, **extra)
    s.borrador = borrador
    s.ultimas_opciones = list(ultimas)
    SESIONES[sid] = s
    return s


@pytest.mark.anyio
async def test_seguir_editando_guarda_texto_del_panel(buscador):
    s = _sesion_revision("g-editar", ["editar", "rechazar"])
    resp = await manejar_turno(
        ChatOrquestadorRequest(session_id="g-editar", accion="editar", titulo=TITULO, texto=TEXTO_EDITADO),
        buscador,
    )
    assert s.borrador.texto_limpio.strip() == TEXTO_EDITADO
    assert resp.mensaje != MSG_PEDIR_EDICION


@pytest.mark.anyio
async def test_seguir_editando_sin_cambios_pide_edicion(buscador):
    _sesion_revision("g-editar-0", ["editar", "rechazar"])
    resp = await manejar_turno(
        ChatOrquestadorRequest(session_id="g-editar-0", accion="editar", titulo=TITULO, texto=TEXTO),
        buscador,
    )
    assert resp.mensaje == MSG_PEDIR_EDICION


@pytest.mark.anyio
async def test_cancelar_rechazo_conserva_lo_editado(buscador):
    s = _sesion_revision("g-cancel", ["confirmar_rechazo", "cancelar_rechazo"], confirmando_rechazo=True)
    await manejar_turno(
        ChatOrquestadorRequest(session_id="g-cancel", accion="cancelar_rechazo", texto=TEXTO_EDITADO),
        buscador,
    )
    assert s.confirmando_rechazo is False
    assert s.borrador is not None
    assert s.borrador.texto_limpio.strip() == TEXTO_EDITADO


def _sesion_decision_texto(sid):
    c = CoincidenciaArticulo(id=7, titulo="Otro", url="https://x/t/7", score=0.9, tipo_coincidencia="semantico")
    s = SesionChat(
        session_id=sid, estado=EstadoFlujo.DECISION_TEXTO, titulo=TITULO,
        texto=TEXTO, texto_limpio=TEXTO, bloques_texto=[TEXTO], coincidencias=[c],
    )
    s.ultimas_opciones = ["enriquecer", "continuar"]
    SESIONES[sid] = s
    return s


@pytest.mark.anyio
async def test_continuar_con_mi_texto_usa_el_texto_del_panel(buscador):
    s = _sesion_decision_texto("g-dt")
    resp = await manejar_turno(
        ChatOrquestadorRequest(session_id="g-dt", accion="continuar", texto=TEXTO_EDITADO), buscador
    )
    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert s.borrador.texto_limpio.strip() == TEXTO_EDITADO
    buscador.evaluar_texto.assert_not_called()


@pytest.mark.anyio
async def test_continuar_con_texto_corto_no_avanza(buscador):
    s = _sesion_decision_texto("g-dt-corto")
    resp = await manejar_turno(
        ChatOrquestadorRequest(session_id="g-dt-corto", accion="continuar", texto="corto"), buscador
    )
    assert resp.estado == EstadoFlujo.DECISION_TEXTO
    assert s.borrador is None
    assert s.coincidencias


@pytest.mark.anyio
async def test_respuesta_declara_guardan_campos(buscador):
    _sesion_decision_texto("g-decl")
    resp = await manejar_turno(ChatOrquestadorRequest(session_id="g-decl", accion="ayuda"), buscador)
    assert set(resp.guardan_campos) <= {"enriquecer", "continuar"}


@pytest.mark.anyio
async def test_reaplicar_solo_con_skill_pendiente(buscador):
    s = _sesion_revision("g-reap", ["continuar"])
    resp = await manejar_turno(ChatOrquestadorRequest(session_id="g-reap", accion="ayuda"), buscador)
    assert "reaplicar" not in resp.guardan_campos
    s.borrador.resultado_skill_pendiente = True
    s.borrador.skill_pendiente = "plantilla"
    resp = await manejar_turno(ChatOrquestadorRequest(session_id="g-reap", accion="ayuda"), buscador)
    assert "reaplicar" in resp.guardan_campos
