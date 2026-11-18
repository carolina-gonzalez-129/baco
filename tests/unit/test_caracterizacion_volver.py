"""
Tests de caracterización para la opción "volver" en el orquestador.

Fijan el comportamiento ACTUAL antes de la refactorización del flujo.
Cubre los 7 puntos en handlers.py y el procesamiento desde coordinador.py en CONFORMIDAD_USUARIO.
"""

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
from baco.server.services.orquestador.mensajes import (
    MSG_ENRIQUECIMIENTO_DESCARTADO,
    MSG_VOLVER_ENRIQUECER_O_DESCARTAR,
    MSG_VOLVER_PLANTILLA,
    MSG_VOLVER_TEXTO,
    MSG_VOLVER_TEXTO_ACTUALIZADO,
    MSG_VOLVER_TITULO,
    OPCIONES_ENRIQUECER_CONTINUAR,
    OPCIONES_ENRIQUECER_DESCARTAR,
    OPCIONES_PLANTILLAS,
)
from baco.server.services.orquestador.retroceso import PREFIJO_VOLVER_REVISION
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos

TEXTO_VALIDO = (
    "Para configurar el punto de venta electrónico en el sistema Finnegans ERP es necesario ingresar "
    "al maestro de puntos de venta dentro del módulo de Ventas, asociar el certificado digital vigente "
    "otorgado por AFIP y verificar que el tipo de emisión esté habilitado para comprobantes electrónicos."
)
TITULO_VALIDO = "Cómo configurar el punto de venta electrónico AFIP"


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


# ==============================================================================
# Punto 1: handlers.py ~ línea 466 (handle_decision_titulo)
# ==============================================================================

@pytest.mark.anyio
async def test_volver_en_decision_titulo_linea_466(mock_buscador):
    """
    Caracterización handlers.py L466:
    En DECISION_TITULO, 'volver' limpia los fallos del estado, vacía las coincidencias
    y regresa a ESPERANDO_TITULO con MSG_VOLVER_TITULO y opciones vacías.
    """
    sid = "test-volver-l466"
    coincidencia = CoincidenciaArticulo(
        id=101,
        titulo="Artículo Existente Similitud",
        url="https://bc.finneg.com/t/101",
        score=0.92,
        tipo_coincidencia="exacto",
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.DECISION_TITULO,
        titulo=TITULO_VALIDO,
        texto="",
        tags=[],
        categoria_id=None,
        coincidencias=[coincidencia],
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion.registrar_fallo("DECISION_TITULO")
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    # Verificación de respuesta y transición
    assert resp.estado == EstadoFlujo.ESPERANDO_TITULO
    assert resp.mensaje == MSG_VOLVER_TITULO
    assert resp.opciones == []

    # Verificación de estado y campos de sesión
    assert sesion.estado == EstadoFlujo.ESPERANDO_TITULO
    assert sesion.coincidencias == []
    assert "DECISION_TITULO" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == ""
    assert sesion.tags == []
    assert sesion.categoria_id is None
    assert sesion.borrador is None
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False


# ==============================================================================
# Punto 2: handlers.py ~ línea 486 (handle_esperando_texto)
# ==============================================================================

@pytest.mark.anyio
async def test_volver_en_esperando_texto_linea_486_modo_nuevo(mock_buscador):
    """
    Caracterización handlers.py L486 (Modo Nuevo / sin borrador enriquecimiento):
    En ESPERANDO_TEXTO, 'volver' limpia fallos, resetea texto_en_edicion y vuelve a
    ESPERANDO_TITULO con MSG_VOLVER_TITULO.
    """
    sid = "test-volver-l486-nuevo"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo=TITULO_VALIDO,
        texto="",
        texto_en_edicion="Texto borrador parcial que no se confirmó",
        tags=[],
        categoria_id=None,
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion.registrar_fallo("ESPERANDO_TEXTO")
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_TITULO
    assert resp.mensaje == MSG_VOLVER_TITULO
    assert resp.opciones == []

    assert sesion.estado == EstadoFlujo.ESPERANDO_TITULO
    assert sesion.texto_en_edicion == ""
    assert "ESPERANDO_TEXTO" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == ""
    assert sesion.tags == []
    assert sesion.categoria_id is None
    assert sesion.borrador is None
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False


@pytest.mark.anyio
async def test_volver_en_esperando_texto_linea_486_modo_enriquecimiento_sin_semantico(mock_buscador):
    """
    Caracterización handlers.py L486 (Modo enriquecimiento, coincidencia no semántica):
    Vuelve a DECISION_TITULO avisando el descarte (MSG_ENRIQUECIMIENTO_DESCARTADO) y opciones OPCIONES_ENRIQUECER_DESCARTAR.
    Conserva el borrador existente intacto.
    """
    sid = "test-volver-l486-enriq"
    coincidencia = CoincidenciaArticulo(
        id=202,
        titulo="Artículo Existente Para Enriquecer",
        url="https://bc.finneg.com/t/202",
        score=0.95,
        tipo_coincidencia="exacto",
    )
    borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=202,
        articulo_original_url="https://bc.finneg.com/t/202",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=5,
        tags=["instructivo", "ventas"],
        metadatos_anteriores={"categoria_id": 5, "tags": ["instructivo", "ventas"]},
        metadatos_heredados_revisados=False,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        texto_en_edicion="Edición no guardada",
        tags=["instructivo", "ventas"],
        categoria_id=5,
        coincidencias=[coincidencia],
        borrador=borrador,
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores={"categoria_id": 5, "tags": ["instructivo", "ventas"]},
        metadatos_heredados_revisados=False,
    )
    sesion.registrar_fallo("ESPERANDO_TEXTO")
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.DECISION_TITULO
    assert resp.mensaje == MSG_ENRIQUECIMIENTO_DESCARTADO + MSG_VOLVER_ENRIQUECER_O_DESCARTAR
    assert resp.opciones == OPCIONES_ENRIQUECER_DESCARTAR

    assert sesion.estado == EstadoFlujo.DECISION_TITULO
    assert sesion.texto_en_edicion == ""
    assert "ESPERANDO_TEXTO" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == ""
    assert sesion.tags == ["instructivo", "ventas"]
    assert sesion.categoria_id == 5
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores == {"categoria_id": 5, "tags": ["instructivo", "ventas"]}
    assert sesion.metadatos_heredados_revisados is False

    # Campos del borrador
    assert sesion.borrador is None


@pytest.mark.anyio
async def test_volver_en_esperando_texto_linea_486_modo_enriquecimiento_con_semantico(mock_buscador):
    """
    Caracterización handlers.py L486 (Modo enriquecimiento, coincidencia semántica):
    Si alguna coincidencia tiene tipo_coincidencia == 'semantico', vuelve a DECISION_TEXTO
    con OPCIONES_ENRIQUECER_CONTINUAR.
    """
    sid = "test-volver-l486-semantico"
    coincidencia = CoincidenciaArticulo(
        id=303,
        titulo="Artículo Semánticamente Similar",
        url="https://bc.finneg.com/t/303",
        score=0.85,
        tipo_coincidencia="semantico",
        mensaje="Coincidencia semántica de texto",
    )
    borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=303,
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="soluciones",
        categoria_id=3,
        tags=["soluciones"],
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        texto_en_edicion="Texto pendiente",
        tags=["soluciones"],
        categoria_id=3,
        coincidencias=[coincidencia],
        borrador=borrador,
    )
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.DECISION_TEXTO
    assert resp.opciones == OPCIONES_ENRIQUECER_CONTINUAR
    assert sesion.estado == EstadoFlujo.DECISION_TEXTO
    assert sesion.texto_en_edicion == ""

    # Verificación exhaustiva de campos de sesión
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == ""
    assert sesion.tags == ["soluciones"]
    assert sesion.categoria_id == 3
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False

    # Verificación exhaustiva de campos del borrador
    assert sesion.borrador is None


# ==============================================================================
# Punto 3: handlers.py ~ línea 1033 (handle_decision_texto)
# ==============================================================================

@pytest.mark.anyio
async def test_volver_en_decision_texto_linea_1033(mock_buscador):
    """
    Caracterización handlers.py L1033:
    En DECISION_TEXTO, 'volver' limpia fallos de DECISION_TEXTO, vacía coincidencias
    y regresa a ESPERANDO_TEXTO con MSG_VOLVER_TEXTO y opciones ['volver'].
    """
    sid = "test-volver-l1033"
    coincidencia = CoincidenciaArticulo(
        id=404,
        titulo="Artículo Duplicado en Texto",
        url="https://bc.finneg.com/t/404",
        score=0.88,
        tipo_coincidencia="semantico",
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.DECISION_TEXTO,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=[],
        categoria_id=None,
        coincidencias=[coincidencia],
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion.registrar_fallo("DECISION_TEXTO")
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert resp.mensaje == MSG_VOLVER_TEXTO
    assert resp.opciones == []
    assert resp.navegacion == ["volver"]
    assert resp.accion_panel.accion == "confirmar_texto"

    assert sesion.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert sesion.coincidencias == []
    assert "DECISION_TEXTO" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == []
    assert sesion.categoria_id is None
    assert sesion.borrador is None
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False


# ==============================================================================
# Punto 4: handlers.py ~ línea 1051 (handle_esperando_plantilla)
# ==============================================================================

@pytest.mark.anyio
async def test_volver_en_esperando_plantilla_linea_1051_sin_metadatos_anteriores(mock_buscador):
    """
    Caracterización handlers.py L1051 (Sin metadatos_anteriores):
    En ESPERANDO_PLANTILLA sin metadatos heredados de versión previa, 'volver'
    limpia fallos y regresa a ESPERANDO_TEXTO con MSG_VOLVER_TEXTO_ACTUALIZADO
    y opciones ['confirmar_texto', 'volver'].
    """
    sid = "test-volver-l1051-sin-ant"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla=None,
        categoria_id=None,
        tags=[],
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_PLANTILLA,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=[],
        categoria_id=None,
        borrador=borrador,
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion.registrar_fallo("ESPERANDO_PLANTILLA")
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert resp.mensaje == MSG_VOLVER_TEXTO_ACTUALIZADO
    assert resp.opciones == []
    assert resp.navegacion == ["volver"]
    assert resp.accion_panel.accion == "confirmar_texto"

    assert sesion.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert "ESPERANDO_PLANTILLA" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == []
    assert sesion.categoria_id is None
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False

    assert sesion.borrador.modo == "nuevo"
    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.tipo_plantilla is None
    assert sesion.borrador.categoria_id is None
    assert sesion.borrador.tags == []
    assert sesion.borrador.metadatos_anteriores is None
    assert sesion.borrador.metadatos_heredados_revisados is False


@pytest.mark.anyio
async def test_volver_en_esperando_plantilla_linea_1051_con_metadatos_anteriores(mock_buscador):
    """
    Caracterización handlers.py L1051 (Con metadatos_anteriores):
    Si el borrador tiene metadatos_anteriores, al recibir 'volver' restaura los metadatos
    heredados (categoria_id, tags, tipo_plantilla), pone metadatos_heredados_revisados en False,
    y avanza vía avanzar_a_metadatos_o_revision(sesion).
    Contrato vigente: vuelve al paso de texto (Editor con el artículo base, "Es un tema distinto");
    los heredados quedan restaurados en el borrador para precargarse en el paso de metadatos.
    """
    sid = "test-volver-l1051-con-ant"
    metadatos_ant = {
        "categoria_id": 5,
        "categoria_nombre": "Ventas",
        "tags": ["instructivo", "ventas"],
    }
    borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=505,
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla=None,  # en este estado aún no se había elegido plantilla nueva
        categoria_id=None,
        tags=[],
        metadatos_anteriores=metadatos_ant,
        metadatos_heredados_revisados=True,  # Supongamos que venía revisado o no
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_PLANTILLA,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=[],
        categoria_id=None,
        borrador=borrador,
        metadatos_anteriores=metadatos_ant,
        metadatos_heredados_revisados=True,
    )
    sesion.registrar_fallo("ESPERANDO_PLANTILLA")
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert resp.accion_panel.accion == "confirmar_texto"
    assert resp.opciones == ["descartar"]
    assert resp.navegacion == ["volver"]

    assert sesion.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert "ESPERANDO_PLANTILLA" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.confirmando_rechazo is False

    # Heredados restaurados en el borrador (pendientes de revisar en el paso de metadatos)
    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.metadatos_anteriores == metadatos_ant
    assert sesion.borrador.metadatos_heredados_revisados is False
    assert sesion.borrador.categoria_id == 5
    assert sesion.borrador.tags == ["instructivo", "ventas"]
    assert sesion.borrador.tipo_plantilla == "instructivo"


# ==============================================================================
# Punto 5: handlers.py ~ línea 1111 (handle_esperando_metadatos)
# ==============================================================================

@pytest.mark.anyio
async def test_volver_en_esperando_metadatos_linea_1111_con_tipo_plantilla(mock_buscador):
    """
    Caracterización handlers.py L1111 (con tipo_plantilla) — nuevo flujo:
    En ESPERANDO_METADATOS, 'volver' limpia fallos de ESPERANDO_METADATOS y transiciona
    a la revisión intermedia (REVISION_BORRADOR con revision_intermedia=True),
    conservando b.tipo_plantilla y ejecutando la validación del borrador.
    """
    sid = "test-volver-l1111-con-plantilla"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=None,
        tags=["instructivo"],
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_METADATOS,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=["instructivo"],
        categoria_id=None,
        borrador=borrador,
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion.registrar_fallo("ESPERANDO_METADATOS")
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.REVISION_TIPO
    assert resp.mensaje.startswith(PREFIJO_VOLVER_REVISION.strip())
    assert resp.opciones == ["aplicar_plantilla", "continuar"]
    assert resp.navegacion == []

    assert sesion.estado == EstadoFlujo.REVISION_TIPO
    assert "ESPERANDO_METADATOS" not in sesion.intentos_fallidos_por_estado
    assert sesion.borrador.tipo_plantilla == "instructivo"
    # Tags se conservan tal cual
    assert sesion.borrador.tags == ["instructivo"]
    assert sesion.tags == ["instructivo"]
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.categoria_id is None
    assert sesion.borrador.categoria_id is None
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is not None  # Se ejecutó la validación de la revisión intermedia
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False


@pytest.mark.anyio
async def test_volver_en_esperando_metadatos_linea_1111_sin_tipo_plantilla(mock_buscador):
    """
    Caracterización handlers.py L1111 (sin tipo_plantilla):
    Si el borrador no tenía tipo_plantilla (o era None), b.tipo_plantilla permanece None
    y la transición a ESPERANDO_PLANTILLA se ejecuta de igual forma.
    """
    sid = "test-volver-l1111-sin-plantilla"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla=None,
        categoria_id=None,
        tags=[],
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_METADATOS,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        borrador=borrador,
    )
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert resp.mensaje == MSG_VOLVER_PLANTILLA
    assert resp.opciones == OPCIONES_PLANTILLAS

    assert sesion.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == []
    assert sesion.categoria_id is None
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False

    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.tags == []
    assert sesion.borrador.categoria_id is None
    assert sesion.borrador.tipo_plantilla is None
    assert sesion.borrador.metadatos_anteriores is None
    assert sesion.borrador.metadatos_heredados_revisados is False


# ==============================================================================
# Punto 6: handlers.py ~ línea 1223 (_resolver_flujo_rechazo / REVISION_BORRADOR)
# ==============================================================================

@pytest.mark.anyio
async def test_volver_en_esperando_plantilla_modo_actualizar_con_metadatos_heredados(mock_buscador):
    """
    En flujo actualizar con metadatos heredados, estando en ESPERANDO_PLANTILLA,
    'volver' regresa al paso de texto (como en enriquecer) y no vuelve a pedir plantilla.
    """
    sid = "test-volver-actualizar-plantilla-con-metadatos"
    metadatos_ant = {
        "categoria_id": 5,
        "categoria_nombre": "Ventas",
        "tags": ["instructivo", "ventas"],
    }
    borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=505,
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla=None,
        categoria_id=None,
        tags=[],
        metadatos_anteriores=metadatos_ant,
        metadatos_heredados_revisados=True,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_PLANTILLA,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=[],
        categoria_id=None,
        borrador=borrador,
        metadatos_anteriores=metadatos_ant,
        metadatos_heredados_revisados=True,
    )
    sesion.registrar_fallo("ESPERANDO_PLANTILLA")
    sesion.ultima_navegacion = ["volver"]  # emitido por el back en el turno anterior
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert sesion.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert resp.accion_panel.accion == "confirmar_texto"
    assert resp.estado != EstadoFlujo.ESPERANDO_PLANTILLA
    assert resp.opciones != OPCIONES_PLANTILLAS


@pytest.mark.anyio
@pytest.mark.parametrize("estado", [
    EstadoFlujo.REVISION_TIPO,
    EstadoFlujo.REVISION_METADATOS,
    EstadoFlujo.EDICION_FINAL,
    EstadoFlujo.FINALIZADO,
])
async def test_volver_no_disponible_en_revisiones_ni_finalizado(mock_buscador, estado):
    """Contrato §1.4: los estados de revisión y FINALIZADO no ofrecen Volver.
    Una acción `volver` se rechaza sin cambiar estado ni borrador."""
    sid = f"test-volver-no-disp-{estado.value}"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=5,
        tags=["instructivo", "ventas"],
    )
    sesion = SesionChat(
        session_id=sid, estado=estado, titulo=TITULO_VALIDO, texto=TEXTO_VALIDO, borrador=borrador,
    )
    SESIONES[sid] = sesion
    previo = borrador.model_dump()

    resp = await manejar_turno(ChatOrquestadorRequest(session_id=sid, accion="volver"), mock_buscador)

    assert resp.estado == estado
    assert sesion.estado == estado
    assert "volver" not in resp.navegacion
    assert sesion.borrador.model_dump() == previo

