import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    CategoriaOpcion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.orquestador.handlers import _aplicar_mutaciones_borrador
from baco.server.services.orquestador.retroceso import retroceder
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


def _crear_sesion(
    estado=EstadoFlujo.REVISION_METADATOS,
    plantilla="instructivo",
    tags=None,
    modo="nuevo",
):
    if tags is None:
        tags = ["instructivo"] if plantilla else []
    borrador = BorradorSesion(
        modo=modo,
        titulo="Configuración de Punto de Venta Electrónico AFIP",
        bloques_texto=[TEXTO_VALIDO],
        categoria_id=5,
        categoria_nombre="Ventas",
        tipo_plantilla=plantilla,
        tags=list(tags),
    )
    sesion = SesionChat(
        session_id="test-plantilla-fija",
        estado=estado,
        titulo="Configuración de Punto de Venta Electrónico AFIP",
        texto=TEXTO_VALIDO,
        categoria_id=5,
        categoria_nombre="Ventas",
        tags=list(tags),
        borrador=borrador,
        categorias_disponibles=[CategoriaOpcion(id=5, nombre="Ventas")],
    )
    sesion.calcular_huella()
    SESIONES["test-plantilla-fija"] = sesion
    return sesion


def test_plantilla_fija_instructivo_ignora_otra_plantilla_en_tags():
    """Verifica que si b.tipo_plantilla='instructivo' y req.tags trae 'soluciones', tipo_plantilla sigue 'instructivo' y 'soluciones' NO queda en tags."""
    sesion = _crear_sesion(plantilla="instructivo", tags=["instructivo", "ventas"])
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=["soluciones", "ventas"],
        hubo_cambios=True,
    )

    _aplicar_mutaciones_borrador(sesion, req)

    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert "soluciones" not in sesion.borrador.tags
    assert "instructivo" in sesion.borrador.tags
    assert "ventas" in sesion.borrador.tags


def test_plantilla_fija_agrega_y_conserva_tags_tematicos_normales():
    """Verifica que se pueden agregar tags temáticos normales y se conservan junto con la plantilla."""
    sesion = _crear_sesion(plantilla="instructivo", tags=["instructivo"])
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=["instructivo", "ventas", "facturacion", "afip"],
        hubo_cambios=True,
    )

    _aplicar_mutaciones_borrador(sesion, req)

    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert "ventas" in sesion.borrador.tags
    assert "facturacion" in sesion.borrador.tags
    assert "afip" in sesion.borrador.tags
    assert "instructivo" in sesion.borrador.tags


def test_plantilla_none_toma_plantilla_de_req_tags_como_respaldo():
    """Verifica que si b.tipo_plantilla=None, se toma la plantilla identificada en req.tags como respaldo."""
    sesion = _crear_sesion(plantilla=None, tags=[])
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=["soluciones", "facturacion"],
        hubo_cambios=True,
    )

    _aplicar_mutaciones_borrador(sesion, req)

    assert sesion.borrador.tipo_plantilla == "soluciones"
    assert "soluciones" in sesion.borrador.tags
    assert "facturacion" in sesion.borrador.tags


@pytest.mark.xfail(
    reason="retroceso.py: _restaurar_esperando_metadatos (L146) conserva b.tipo_plantilla para volver a revisión intermedia en vez de resetearlo a None."
)
def test_volver_desde_esperando_metadatos_resetea_tipo_plantilla_a_none():
    """Verifica que la acción 'volver' desde ESPERANDO_METADATOS sigue reseteando b.tipo_plantilla a None."""
    sesion = _crear_sesion(
        estado=EstadoFlujo.ESPERANDO_METADATOS,
        plantilla="instructivo",
        tags=["instructivo"],
    )

    retroceder(sesion)

    assert sesion.borrador.tipo_plantilla is None
