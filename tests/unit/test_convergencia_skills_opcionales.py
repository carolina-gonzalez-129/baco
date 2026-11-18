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
    sesion.ultimas_opciones = ["instructivo", "soluciones"]
    sesion.ultima_navegacion = ["volver"]
    agente = MagicMock(return_value="NO DEBERIA USARSE")
    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="instructivo")
    req._baco_agent = agente

    resp = await manejar_turno(req, MagicMock(spec=BuscadorDuplicados))

    agente.assert_not_called()
    assert resp.estado == EstadoFlujo.REVISION_TIPO
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert not sesion.borrador.resultado_skill_pendiente
    assert sesion.borrador.bloques_texto == [TEXTO]
    # Aplicar la plantilla es un paso aparte y opcional; las revisiones no ofrecen Volver.
    assert resp.opciones == ["aplicar_plantilla", "continuar"]
    assert resp.navegacion == []


@pytest.mark.anyio
async def test_continuar_sin_aplicar_plantilla_pide_metadatos_sin_ejecutar_skills():
    sesion = _sesion(
        "conv-continuar-sin-aplicar",
        EstadoFlujo.REVISION_TIPO,
        tipo_plantilla="instructivo",
        tags=["instructivo"],
    )
    sesion.ultimas_opciones = ["aplicar_plantilla", "continuar"]
    agente = MagicMock(return_value="NO DEBERIA USARSE")
    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="continuar")
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
    assert resp.estado == EstadoFlujo.REVISION_METADATOS
    assert "auditar" in resp.opciones
    assert "continuar" in resp.opciones


HEREDADOS = {"categoria_id": 20, "categoria_nombre": "Ventas", "tags": ["instructivo", "ventas", "facturacion"]}


def _sesion_enriquecer(sid: str, estado: EstadoFlujo, **extra) -> SesionChat:
    datos = dict(
        modo="enriquecimiento",
        tipo_plantilla="instructivo",
        tags=list(HEREDADOS["tags"]),
        categoria_id=20,
        metadatos_anteriores=dict(HEREDADOS),
    )
    datos.update(extra)
    sesion = _sesion(sid, estado, **datos)
    sesion.borrador.metadatos_heredados_revisados = False
    return sesion


def test_enriquecer_pide_primero_el_tipo_de_plantilla_aunque_venga_heredado():
    sesion = _sesion_enriquecer("conv-enriq-plantilla-primero", EstadoFlujo.ESPERANDO_TEXTO)

    resp = continuar(sesion)

    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert resp.opciones == ["instructivo", "soluciones"]
    assert resp.navegacion == ["volver"]
    assert not resp.aviso_metadatos_heredados


def test_heredados_se_deciden_en_el_paso_de_tags_y_categoria_sin_recursion():
    sesion = _sesion_enriquecer(
        "conv-heredados-paso3", EstadoFlujo.REVISION_TIPO, 
    )

    resp = continuar(sesion)  # Continuar sin aplicar plantilla

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    # Heredados precargados en el panel, sin banner; se confirman con Enviar datos.
    assert resp.opciones == []
    assert resp.navegacion == ["volver"]
    assert resp.accion_panel.accion == "enviar_datos"
    assert resp.aviso_metadatos_heredados is None
    assert "Enviar datos" in resp.mensaje


def test_registrar_finalizado_con_heredados_pendientes_no_recursa():
    # Los heredados se resuelven en ESPERANDO_METADATOS (antes de REVISION_METADATOS);
    # finalizar desde EDICION_FINAL ya no los consulta ni recursa.
    sesion = _sesion_enriquecer("conv-heredados-finalizar", EstadoFlujo.EDICION_FINAL)

    resp = _registrar_finalizado(sesion)  # antes: RecursionError

    assert resp.estado == EstadoFlujo.FINALIZADO
    assert resp.navegacion == ["ver_articulo_final"]


def test_volver_desde_plantilla_en_enriquecer_vuelve_al_texto():
    from baco.server.services.orquestador.retroceso import retroceder

    sesion = _sesion_enriquecer("conv-volver-plantilla-enriq", EstadoFlujo.ESPERANDO_PLANTILLA)

    resp = retroceder(sesion)

    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert resp.accion_panel.accion == "confirmar_texto"
    assert "descartar" in resp.opciones


def test_compuerta_llama_una_sola_vez_a_validar_borrador():
    sesion = _sesion(
        "conv-compuerta-una-vez",
        EstadoFlujo.REVISION_METADATOS,
        tipo_plantilla="instructivo",
        tags=["instructivo"],
    )
    sesion.validacion = None
    original = validaciones.validar_borrador
    with patch.object(validaciones, "validar_borrador", side_effect=original) as espia:
        validaciones.verificar_compuerta_avance(sesion)
    assert espia.call_count == 1
