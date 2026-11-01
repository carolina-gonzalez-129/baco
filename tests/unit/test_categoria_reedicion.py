import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    CategoriaOpcion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.orquestador.handlers import _aplicar_mutaciones_borrador
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
    estado=EstadoFlujo.REVISION_BORRADOR,
    cat_id=1,
    cat_nombre="General",
    finalizado=False,
    plantilla="instructivo",
    tags=None,
):
    if tags is None:
        tags = ["instructivo", "ventas"]
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Configuración de Punto de Venta Electrónico AFIP",
        bloques_texto=[TEXTO_VALIDO],
        categoria_id=cat_id,
        categoria_nombre=cat_nombre,
        tipo_plantilla=plantilla,
        tags=list(tags),
        finalizado=finalizado,
        revision_intermedia=False,
    )
    sesion = SesionChat(
        session_id="test-categoria-reedicion",
        estado=estado,
        titulo="Configuración de Punto de Venta Electrónico AFIP",
        texto=TEXTO_VALIDO,
        categoria_id=cat_id,
        categoria_nombre=cat_nombre,
        tags=list(tags),
        borrador=borrador,
        categorias_disponibles=[
            CategoriaOpcion(id=1, nombre="General"),
            CategoriaOpcion(id=5, nombre="Ventas"),
            CategoriaOpcion(id=37, nombre="Agro"),
        ],
    )
    sesion.calcular_huella()
    SESIONES["test-categoria-reedicion"] = sesion
    return sesion


def test_cambiar_categoria_a_id_valido_distinto_actualiza_id_y_nombre():
    """Verifica que cambiar la categoría a un id válido distinto actualiza tanto categoria_id como categoria_nombre."""
    sesion = _crear_sesion(cat_id=1, cat_nombre="General")
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=5,
        hubo_cambios=True,
    )

    resp = _aplicar_mutaciones_borrador(sesion, req)

    assert resp.borrador.categoria_id == 5
    assert resp.borrador.categoria_nombre == "Ventas"
    assert sesion.borrador.categoria_id == 5
    assert sesion.borrador.categoria_nombre == "Ventas"
    assert sesion.categoria_id == 5
    assert sesion.categoria_nombre == "Ventas"


def test_mismo_id_que_actual_no_muta_categoria_id_ni_nombre():
    """Verifica que si req.categoria_id es igual al actual, no se muta categoria_id ni categoria_nombre."""
    sesion = _crear_sesion(cat_id=1, cat_nombre="General")
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=1,
        hubo_cambios=True,
    )

    _aplicar_mutaciones_borrador(sesion, req)

    assert sesion.borrador.categoria_id == 1
    assert sesion.borrador.categoria_nombre == "General"
    assert sesion.categoria_id == 1
    assert sesion.categoria_nombre == "General"


def test_req_categoria_id_none_no_muta_categoria():
    """Verifica que si req.categoria_id es None, se conservan intactos categoria_id y categoria_nombre."""
    sesion = _crear_sesion(cat_id=1, cat_nombre="General")
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=None,
        titulo="Nuevo Título Válido para Borrador",
        hubo_cambios=True,
    )

    _aplicar_mutaciones_borrador(sesion, req)

    assert sesion.borrador.categoria_id == 1
    assert sesion.borrador.categoria_nombre == "General"
    assert sesion.categoria_id == 1
    assert sesion.categoria_nombre == "General"


def test_categoria_id_inexistente_no_pisa_categoria_anterior():
    """Verifica que enviar un id de categoría inexistente (que no resuelve) no pisa la categoría previa."""
    sesion = _crear_sesion(cat_id=1, cat_nombre="General")
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=999999,
        hubo_cambios=True,
    )

    _aplicar_mutaciones_borrador(sesion, req)

    # Si no resuelve, no debe pisar la categoría existente
    assert sesion.borrador.categoria_id == 1
    assert sesion.borrador.categoria_nombre == "General"


def test_cambiar_categoria_en_finalizado_vuelve_a_revision_y_finalizado_false():
    """Verifica que cambiar la categoría desde estado FINALIZADO altera la huella, volviendo a REVISION_BORRADOR con finalizado=False."""
    sesion = _crear_sesion(
        estado=EstadoFlujo.FINALIZADO,
        cat_id=1,
        cat_nombre="General",
        finalizado=True,
    )
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=5,
        hubo_cambios=True,
    )

    _aplicar_mutaciones_borrador(sesion, req)

    assert sesion.borrador.finalizado is False
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.categoria_id == 5
    assert sesion.borrador.categoria_nombre == "Ventas"


def test_cambiar_categoria_no_altera_tipo_plantilla_ni_tags():
    """Verifica que una mutación que solo modifica categoría preserve íntegros tipo_plantilla y tags."""
    sesion = _crear_sesion(
        cat_id=1,
        cat_nombre="General",
        plantilla="instructivo",
        tags=["instructivo", "ventas"],
    )
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=5,
        hubo_cambios=True,
    )

    _aplicar_mutaciones_borrador(sesion, req)

    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.tags == ["instructivo", "ventas"]
    assert sesion.tags == ["instructivo", "ventas"]
