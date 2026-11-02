"""Convergencia del troncal post-duplicados y skills como pasos opcionales separados (branch-arreglando)."""
from unittest.mock import MagicMock, patch

import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador import validaciones
from baco.server.services.orquestador.continuar import _registrar_finalizado, continuar
from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.sesion import SesionChat, gestor_sesiones


TEXTO = (
    "### Pasos de Configuración\n\n"
    "1. Abrir el menú principal de Ventas y seleccionar Facturación.\n"
    "2. Completar los parámetros del punto de venta electrónico.\n\n"
    "### Consideraciones\n\n"
    "Se requiere perfil de administrador activo para guardar los cambios."
)
TITULO = "Configurar Facturación Electrónica en Ventas"


def _sesion(sid: str, estado: EstadoFlujo, **borrador) -> SesionChat:
    gestor_sesiones.eliminar(sid)
    sesion, _, _ = gestor_sesiones.obtener_o_crear(sid)
    sesion.session_id = sid
    gestor_sesiones.sesiones[sid] = sesion
    sesion.estado = estado
    sesion.titulo = TITULO
    datos = dict(modo="nuevo", titulo=TITULO, bloques_texto=[TEXTO])
    datos.update(borrador)
    sesion.borrador = BorradorSesion(**datos)
    sesion.bloques_texto = [TEXTO]
    sesion.texto_limpio = TEXTO
    sesion.texto = TEXTO
    return sesion


@pytest.mark.anyio
async def test_elegir_plantilla_no_ejecuta_skills_y_ofrece_aplicar_como_paso_aparte():
    sesion = _sesion("conv-elegir-plantilla", EstadoFlujo.ESPERANDO_PLANTILLA)
    agente = MagicMock(return_value="NO DEBERIA USARSE")
    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="instructivo")
    req._baco_agent = agente

    resp = await manejar_turno(req, MagicMock(spec=BuscadorDuplicados))

    agente.assert_not_called()
    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.revision_intermedia is True
    assert not sesion.borrador.resultado_skill_pendiente
    assert sesion.borrador.bloques_texto == [TEXTO]
    assert resp.opciones == ["aplicar_plantilla", "continuar_revision", "volver"]


@pytest.mark.anyio
async def test_continuar_sin_aplicar_plantilla_pide_metadatos_sin_ejecutar_skills():
    sesion = _sesion(
        "conv-continuar-sin-aplicar",
        EstadoFlujo.REVISION_BORRADOR,
        tipo_plantilla="instructivo",
        tags=["instructivo"],
        revision_intermedia=True,
    )
    agente = MagicMock(return_value="NO DEBERIA USARSE")
    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="continuar_revision")
    req._baco_agent = agente

    resp = await manejar_turno(req, MagicMock(spec=BuscadorDuplicados))

    agente.assert_not_called()
    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert sesion.borrador.bloques_texto == [TEXTO]


@pytest.mark.anyio
async def test_metadatos_completos_ofrecen_auditar_sin_ejecutarlo():
    sesion = _sesion(
        "conv-auditor-opcional",
        EstadoFlujo.ESPERANDO_METADATOS,
        tipo_plantilla="instructivo",
        tags=["instructivo"],
        revision_intermedia=False,
    )
    agente = MagicMock(return_value="NO DEBERIA USARSE")
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id, categoria_id=20, tags=["instructivo", "ventas"]
    )
    req._baco_agent = agente

    with patch(
        "baco.server.services.orquestador.handlers.resolver_categoria",
        return_value=MagicMock(categoria_id=20, categoria_nombre="Ventas", estado="ok"),
    ):
        resp = await manejar_turno(req, MagicMock(spec=BuscadorDuplicados))

    agente.assert_not_called()
    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.revision_intermedia is False
    assert "auditar" in resp.opciones
    assert "continuar" in resp.opciones


def test_continuar_con_metadatos_heredados_pendientes_no_recursa():
    sesion = _sesion(
        "conv-heredados-sin-recursion",
        EstadoFlujo.REVISION_BORRADOR,
        modo="enriquecimiento",
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
        categoria_id=20,
        revision_intermedia=True,
        metadatos_anteriores={"categoria_id": 20, "tags": ["instructivo", "ventas"]},
    )
    sesion.borrador.metadatos_heredados_revisados = False

    resp = continuar(sesion)  # antes: RecursionError

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert resp.opciones == ["aceptar_metadatos", "rechazar_metadatos", "volver"]
    # El detalle de los heredados va solo en el banner, no repetido en el chat
    assert resp.aviso_metadatos_heredados
    assert "ventas" not in resp.mensaje.lower()

    resp_fin = _registrar_finalizado(sesion)
    assert resp_fin.opciones == ["aceptar_metadatos", "rechazar_metadatos", "volver"]


def test_aceptar_heredados_converge_al_paso_de_aplicar_plantilla():
    sesion = _sesion(
        "conv-heredados-aceptar",
        EstadoFlujo.REVISION_BORRADOR,
        modo="enriquecimiento",
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
        categoria_id=20,
        revision_intermedia=True,
        metadatos_anteriores={"categoria_id": 20, "tags": ["instructivo", "ventas"]},
    )
    sesion.borrador.metadatos_heredados_revisados = False

    resp = continuar(sesion, opcion="aceptar_metadatos")

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.revision_intermedia is True
    assert "aplicar_plantilla" in resp.opciones


def test_compuerta_llama_una_sola_vez_a_validar_borrador():
    sesion = _sesion(
        "conv-compuerta-una-vez",
        EstadoFlujo.REVISION_BORRADOR,
        tipo_plantilla="instructivo",
        tags=["instructivo"],
        revision_intermedia=True,
    )
    sesion.validacion = None
    original = validaciones.validar_borrador
    with patch.object(validaciones, "validar_borrador", side_effect=original) as espia:
        validaciones.verificar_compuerta_avance(sesion)
    assert espia.call_count == 1
