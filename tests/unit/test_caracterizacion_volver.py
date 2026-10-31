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
    MSG_OPERACION_CANCELADA,
    MSG_VOLVER_ENRIQUECER_O_DESCARTAR,
    MSG_VOLVER_METADATOS,
    MSG_VOLVER_PLANTILLA,
    MSG_VOLVER_TEXTO,
    MSG_VOLVER_TEXTO_ACTUALIZADO,
    MSG_VOLVER_TITULO,
    OPCIONES_ENRIQUECER_CONTINUAR,
    OPCIONES_ENRIQUECER_DESCARTAR,
    OPCIONES_PLANTILLAS,
)
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.retroceso import PREFIJO_VOLVER_REVISION
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
    Vuelve a DECISION_TITULO con MSG_VOLVER_ENRIQUECER_O_DESCARTAR y opciones OPCIONES_ENRIQUECER_DESCARTAR.
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
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.DECISION_TITULO
    assert resp.mensaje == MSG_VOLVER_ENRIQUECER_O_DESCARTAR
    assert resp.opciones == OPCIONES_ENRIQUECER_DESCARTAR

    assert sesion.estado == EstadoFlujo.DECISION_TITULO
    assert sesion.texto_en_edicion == ""
    assert "ESPERANDO_TEXTO" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == ["instructivo", "ventas"]
    assert sesion.categoria_id == 5
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores == {"categoria_id": 5, "tags": ["instructivo", "ventas"]}
    assert sesion.metadatos_heredados_revisados is False

    # Campos del borrador
    assert sesion.borrador.modo == "enriquecimiento"
    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.tags == ["instructivo", "ventas"]
    assert sesion.borrador.categoria_id == 5
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.metadatos_anteriores == {"categoria_id": 5, "tags": ["instructivo", "ventas"]}
    assert sesion.borrador.metadatos_heredados_revisados is False


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
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.DECISION_TEXTO
    assert resp.opciones == OPCIONES_ENRIQUECER_CONTINUAR
    assert sesion.estado == EstadoFlujo.DECISION_TEXTO
    assert sesion.texto_en_edicion == ""

    # Verificación exhaustiva de campos de sesión
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == ["soluciones"]
    assert sesion.categoria_id == 3
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False

    # Verificación exhaustiva de campos del borrador
    assert sesion.borrador.modo == "enriquecimiento"
    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.tags == ["soluciones"]
    assert sesion.borrador.categoria_id == 3
    assert sesion.borrador.tipo_plantilla == "soluciones"
    assert sesion.borrador.metadatos_anteriores is None
    assert sesion.borrador.metadatos_heredados_revisados is False


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
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert resp.mensaje == MSG_VOLVER_TEXTO
    assert resp.opciones == ["volver"]

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
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert resp.mensaje == MSG_VOLVER_TEXTO_ACTUALIZADO
    assert resp.opciones == ["confirmar_texto", "volver"]

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
    NOTA COMPORTAMIENTO ACTUAL: Dado que metadatos_anteriores existe y metadatos_heredados_revisados
    pasa a False, avanzar_a_metadatos_o_revision redirige inmediatamente a REVISION_BORRADOR
    mostrando las opciones ['aceptar', 'rechazar', ...].
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
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    # Verifica que avanzó a REVISION_BORRADOR esperando aceptar/rechazar metadatos heredados
    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert "aceptar" in resp.opciones
    assert "rechazar" in resp.opciones

    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert "ESPERANDO_PLANTILLA" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.categoria_id == 5
    assert sesion.tags == ["instructivo", "ventas"]
    assert sesion.metadatos_anteriores == metadatos_ant
    assert sesion.metadatos_heredados_revisados is False
    assert sesion.confirmando_rechazo is False
    # validacion se ejecuta dentro de avanzar_a_metadatos_o_revision cuando hay metadatos anteriores
    assert sesion.validacion is not None

    # Verifica campos restaurados en el borrador
    # NOTA COMPORTAMIENTO ACTUAL:
    # avanzar_a_metadatos_o_revision ejecuta validar_borrador, el cual genera un
    # 'titulo_sanitizado' (quitando 'Cómo ') y actualiza b.titulo = 'Configurar el punto de venta electrónico AFIP',
    # mientras que sesion.titulo conserva el valor original.
    assert sesion.borrador.titulo == "Configurar el punto de venta electrónico AFIP"
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.metadatos_anteriores == metadatos_ant
    assert sesion.borrador.metadatos_heredados_revisados is False
    assert sesion.borrador.categoria_id == 5
    assert sesion.borrador.categoria_nombre == "Ventas"
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
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert resp.mensaje.startswith(PREFIJO_VOLVER_REVISION)
    assert "continuar_revision" in resp.opciones

    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert "ESPERANDO_METADATOS" not in sesion.intentos_fallidos_por_estado
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.revision_intermedia is True
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
async def test_volver_en_revision_borrador_rechazo_activo_linea_1223(mock_buscador):
    """
    Caracterización handlers.py L1223 (_resolver_flujo_rechazo):
    Cuando sesion.confirmando_rechazo es True en REVISION_BORRADOR, 'volver'
    cancela el rechazo (sesion.confirmando_rechazo = False), permanece en REVISION_BORRADOR,
    ejecuta validar_borrador(sesion) y devuelve MSG_OPERACION_CANCELADA + mensaje de validación.
    El borrador y sus campos NO se descartan.
    """
    sid = "test-volver-l1223"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=5,
        categoria_nombre="Ventas",
        tags=["instructivo", "ventas"],
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=["instructivo", "ventas"],
        categoria_id=5,
        borrador=borrador,
        confirmando_rechazo=True,  # Usuario había presionado 'rechazar' previamente
        validacion=None,
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert resp.mensaje.startswith(MSG_OPERACION_CANCELADA)

    # sesion.confirmando_rechazo debe haberse reseteado a False
    assert sesion.confirmando_rechazo is False
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador is not None
    assert sesion.validacion is not None  # Se ejecutó la validación

    # Campos de sesión y borrador preservados
    # NOTA DE COMPORTAMIENTO ACTUAL:
    # validar_borrador ejecuta validar_texto_y_estructura_post_duplicados, que genera un
    # 'titulo_sanitizado' (quitando prefijos como 'Cómo ') y muta b.titulo = res['titulo_sanitizado'].
    # Sin embargo, sesion.titulo NO se actualiza en este camino y conserva el valor original.
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.borrador.titulo == "Configurar el punto de venta electrónico AFIP"
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.tags == ["instructivo", "ventas"]
    assert sesion.borrador.categoria_id == 5
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False


# ==============================================================================
# Punto 7: handlers.py ~ línea 1521 (handle_revision_borrador)
# ==============================================================================

@pytest.mark.anyio
async def test_volver_en_revision_borrador_linea_1521_modo_nuevo(mock_buscador):
    """
    Caracterización handlers.py L1521 (Modo nuevo):
    En REVISION_BORRADOR sin confirmando_rechazo, 'volver' limpia fallos de REVISION_BORRADOR,
    transiciona a ESPERANDO_METADATOS, y retorna MSG_VOLVER_METADATOS con opciones ['volver'].
    Los campos del borrador y de la sesión se mantienen intactos.
    """
    sid = "test-volver-l1521-nuevo"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=5,
        categoria_nombre="Ventas",
        tags=["instructivo", "ventas"],
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=["instructivo", "ventas"],
        categoria_id=5,
        borrador=borrador,
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    sesion.registrar_fallo("REVISION_BORRADOR")
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.mensaje == MSG_VOLVER_METADATOS
    assert resp.opciones == ["volver"]

    assert sesion.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert "REVISION_BORRADOR" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == ["instructivo", "ventas"]
    assert sesion.categoria_id == 5
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False

    assert sesion.borrador.modo == "nuevo"
    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.categoria_id == 5
    assert sesion.borrador.tags == ["instructivo", "ventas"]


@pytest.mark.anyio
async def test_volver_en_revision_borrador_linea_1521_modo_enriquecimiento(mock_buscador):
    """
    Caracterización handlers.py L1521 (Modo enriquecimiento):
    En REVISION_BORRADOR sin confirmando_rechazo, cuando borrador.modo == 'enriquecimiento',
    'volver' transiciona a DECISION_TITULO retornando MSG_VOLVER_ENRIQUECER_O_DESCARTAR
    con opciones OPCIONES_ENRIQUECER_DESCARTAR.
    """
    sid = "test-volver-l1521-enriq"
    coincidencia = CoincidenciaArticulo(
        id=606,
        titulo="Artículo Original Enriquecido",
        url="https://bc.finneg.com/t/606",
        score=0.91,
        tipo_coincidencia="exacto",
    )
    borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=606,
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="soluciones",
        categoria_id=4,
        categoria_nombre="Impuestos",
        tags=["soluciones", "afip"],
        metadatos_anteriores={"categoria_id": 4, "tags": ["soluciones", "afip"]},
        metadatos_heredados_revisados=True,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=["soluciones", "afip"],
        categoria_id=4,
        coincidencias=[coincidencia],
        borrador=borrador,
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores={"categoria_id": 4, "tags": ["soluciones", "afip"]},
        metadatos_heredados_revisados=True,
    )
    sesion.registrar_fallo("REVISION_BORRADOR")
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.DECISION_TITULO
    assert resp.mensaje == MSG_VOLVER_ENRIQUECER_O_DESCARTAR
    assert resp.opciones == OPCIONES_ENRIQUECER_DESCARTAR

    assert sesion.estado == EstadoFlujo.DECISION_TITULO
    assert "REVISION_BORRADOR" not in sesion.intentos_fallidos_por_estado
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == ["soluciones", "afip"]
    assert sesion.categoria_id == 4
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores == {"categoria_id": 4, "tags": ["soluciones", "afip"]}
    assert sesion.metadatos_heredados_revisados is True

    assert sesion.borrador.modo == "enriquecimiento"
    assert sesion.borrador.articulo_original_id == 606
    assert sesion.borrador.tipo_plantilla == "soluciones"


@pytest.mark.anyio
async def test_volver_en_subsanando_borrador_modo_nuevo(mock_buscador):
    """
    Caracterización SUBSANANDO_BORRADOR (Modo nuevo):
    Al compartir handler con REVISION_BORRADOR, debe retroceder exactamente igual hacia ESPERANDO_METADATOS.
    """
    sid = "test-volver-subsanando-nuevo"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=5,
        categoria_nombre="Ventas",
        tags=["instructivo", "ventas"],
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.SUBSANANDO_BORRADOR,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=["instructivo", "ventas"],
        categoria_id=5,
        borrador=borrador,
    )
    sesion.registrar_fallo("SUBSANANDO_BORRADOR")
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.mensaje == MSG_VOLVER_METADATOS
    assert resp.opciones == ["volver"]
    assert sesion.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert "SUBSANANDO_BORRADOR" not in sesion.intentos_fallidos_por_estado


# ==============================================================================
# Punto 8: coordinador.py ~ líneas 50-70 (CONFORMIDAD_USUARIO -> volver)
# ==============================================================================

@pytest.mark.anyio
async def test_volver_en_conformidad_usuario_coordinador_modo_nuevo(mock_buscador):
    """
    Caracterización coordinador.py (CONFORMIDAD_USUARIO con 'volver', Modo nuevo):
    Cuando la sesión está en CONFORMIDAD_USUARIO y se recibe 'volver':
    1. coordinador.py detecta intento de edición (opcion in ('editar', 'sanitizar', 'volver')),
       cambia sesion.estado a REVISION_BORRADOR e invalida la conformidad:
       - b.conforme = False
       - b.conforme_en = None
       - b.conformidad_invalidada = True
    2. Invoca el handler de REVISION_BORRADOR con opcion='volver', el cual ejecuta la línea 1521,
       transicionando finalmente a ESPERANDO_METADATOS.
    """
    sid = "test-volver-coord-conf-nuevo"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=5,
        categoria_nombre="Ventas",
        tags=["instructivo", "ventas"],
        conforme=True,
        conforme_en="2026-10-30T22:00:00Z",
        conformidad_invalidada=False,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=["instructivo", "ventas"],
        categoria_id=5,
        borrador=borrador,
        confirmando_rechazo=False,
        validacion=None,
        metadatos_anteriores=None,
        metadatos_heredados_revisados=False,
    )
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    # Estado final tras pasar por coordinador (a REVISION_BORRADOR) y luego handler (a ESPERANDO_METADATOS)
    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.mensaje == MSG_VOLVER_METADATOS
    assert resp.opciones == ["volver"]

    assert sesion.estado == EstadoFlujo.ESPERANDO_METADATOS

    # Verificación de invalidación de conformidad
    assert sesion.borrador.conforme is False
    assert sesion.borrador.conforme_en is None
    assert sesion.borrador.conformidad_invalidada is True

    # Campos conservados
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == ["instructivo", "ventas"]
    assert sesion.categoria_id == 5
    assert sesion.confirmando_rechazo is False
    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.categoria_id == 5
    assert sesion.borrador.tags == ["instructivo", "ventas"]
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False


@pytest.mark.anyio
async def test_volver_en_conformidad_usuario_coordinador_modo_enriquecimiento(mock_buscador):
    """
    Caracterización coordinador.py (CONFORMIDAD_USUARIO con 'volver', Modo enriquecimiento):
    1. coordinador.py invalida conformidad (conforme=False, conforme_en=None, conformidad_invalidada=True)
       y setea estado a REVISION_BORRADOR.
    2. handle_revision_borrador procesa 'volver' para modo 'enriquecimiento' (línea 1521),
       transicionando finalmente a DECISION_TITULO.
    """
    sid = "test-volver-coord-conf-enriq"
    coincidencia = CoincidenciaArticulo(
        id=707,
        titulo="Artículo Coincidente Previo",
        url="https://bc.finneg.com/t/707",
        score=0.90,
        tipo_coincidencia="exacto",
    )
    borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=707,
        titulo=TITULO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo",
        categoria_id=5,
        categoria_nombre="Ventas",
        tags=["instructivo", "ventas"],
        conforme=True,
        conforme_en="2026-10-30T22:00:00Z",
        conformidad_invalidada=False,
    )
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo=TITULO_VALIDO,
        texto=TEXTO_VALIDO,
        tags=["instructivo", "ventas"],
        categoria_id=5,
        coincidencias=[coincidencia],
        borrador=borrador,
        confirmando_rechazo=False,
        validacion=None,
    )
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest(session_id=sid, accion="volver")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.DECISION_TITULO
    assert resp.mensaje == MSG_VOLVER_ENRIQUECER_O_DESCARTAR
    assert resp.opciones == OPCIONES_ENRIQUECER_DESCARTAR

    assert sesion.estado == EstadoFlujo.DECISION_TITULO
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.texto == TEXTO_VALIDO
    assert sesion.tags == ["instructivo", "ventas"]
    assert sesion.categoria_id == 5
    assert sesion.confirmando_rechazo is False
    assert sesion.validacion is None
    assert sesion.metadatos_anteriores is None
    assert sesion.metadatos_heredados_revisados is False

    assert sesion.borrador.conforme is False
    assert sesion.borrador.conforme_en is None
    assert sesion.borrador.conformidad_invalidada is True

    assert sesion.borrador.modo == "enriquecimiento"
    assert sesion.borrador.articulo_original_id == 707
    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.categoria_id == 5
    assert sesion.borrador.tags == ["instructivo", "ventas"]
    assert sesion.borrador.metadatos_anteriores is None
    assert sesion.borrador.metadatos_heredados_revisados is False
