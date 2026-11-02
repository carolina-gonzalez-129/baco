from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import BorradorSesion, EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.mensajes import (
    MSG_BORRADOR_FINALIZADO,
    OPCIONES_FINALIZADO,
)
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import (
    limpiar_cache_catalogos,
    obtener_etapa_flujo,
)

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
    buscador.cur = MagicMock()
    buscador.obtener_articulo.return_value = None
    return buscador


@pytest.fixture
def client(mock_buscador):
    def override_buscador():
        yield mock_buscador

    app.dependency_overrides[get_buscador_duplicados] = override_buscador
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as test_client:
            yield test_client
    app.dependency_overrides.clear()


def test_finalizar_sin_bloqueantes_lleva_a_finalizado_y_etapa_actual_5(client):
    """Verifica que finalizar sin bloqueantes lleva a FINALIZADO, responde con MSG_BORRADOR_FINALIZADO,
    establece finalizado=True, etapa.actual=5 y GET /chat/borrador lo acepta."""
    sid = "test-finalizar-valido"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            revision_intermedia=False,
        ),
    )
    SESIONES[sid] = sesion

    # Al consultar el turno sin acción para validar borrador
    r_check = client.post("/chat", headers={"X-Session-ID": sid}, json={}).json()
    assert "finalizar" in r_check["opciones"]

    # Ejecutar finalizar
    r = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "finalizar"}).json()
    assert r["estado"] == EstadoFlujo.FINALIZADO
    assert r["mensaje"] == MSG_BORRADOR_FINALIZADO
    assert r["opciones"] == OPCIONES_FINALIZADO
    assert r["etapa"]["actual"] == 5
    assert sesion.borrador.finalizado is True

    # GET /chat/borrador debe aceptar el estado FINALIZADO
    r_get = client.get("/chat/borrador", headers={"X-Session-ID": sid})
    assert r_get.status_code == 200
    assert r_get.json()["finalizado"] is True


def test_finalizar_no_se_ofrece_con_bloqueantes(client):
    """Verifica que con bloqueantes (ej. texto demasiado corto), finalizar no aparece en las opciones."""
    sid = "test-finalizar-bloqueante"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Texto Corto",
            bloques_texto=["Texto insuficiente."],
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            revision_intermedia=False,
        ),
    )
    SESIONES[sid] = sesion

    r = client.post("/chat", headers={"X-Session-ID": sid}, json={}).json()
    assert r["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "finalizar" not in r["opciones"]
    assert "editar" in r["opciones"]
    assert "rechazar" in r["opciones"]


def test_editar_desde_finalizado_vuelve_a_revision_y_finalizado_queda_false(client):
    """Verifica que si llega editar desde FINALIZADO, vuelve a REVISION_BORRADOR y finalizado=False."""
    sid = "test-finalizar-editar"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            finalizado=True,
            revision_intermedia=False,
        ),
    )
    SESIONES[sid] = sesion

    # Enviamos acción "editar"
    r = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "editar"}).json()
    assert r["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.finalizado is False


def test_etapa_flujo_finalizado_devuelve_actual_5():
    """Verifica que obtener_etapa_flujo para EstadoFlujo.FINALIZADO devuelve actual == 5."""
    etapa = obtener_etapa_flujo(EstadoFlujo.FINALIZADO)
    assert etapa.actual == 5
    assert etapa.nombre == "Conformidad"


def test_volver_desde_finalizado_va_a_revision_borrador_sin_retroceder(client):
    """Punto 1: En FINALIZADO, 'volver' va a REVISION_BORRADOR (finalizado=False) y responde con la revisión normal, sin llamar a retroceder()."""
    sid = "test-finalizar-volver"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            finalizado=True,
            revision_intermedia=False,
        ),
    )
    SESIONES[sid] = sesion

    r = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "volver"}).json()
    assert r["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.finalizado is False
    assert "finalizar" in r["opciones"]


def test_turno_vacio_en_finalizado_devuelve_msg_borrador_finalizado(client):
    """Punto 2: En FINALIZADO, un turno sin edición ni acción devuelve MSG_BORRADOR_FINALIZADO con OPCIONES_FINALIZADO."""
    sid = "test-finalizar-vacio"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            finalizado=True,
            revision_intermedia=False,
        ),
    )
    SESIONES[sid] = sesion

    r = client.post("/chat", headers={"X-Session-ID": sid}, json={}).json()
    assert r["estado"] == EstadoFlujo.FINALIZADO
    assert r["mensaje"] == MSG_BORRADOR_FINALIZADO
    assert r["opciones"] == OPCIONES_FINALIZADO
    assert sesion.borrador.finalizado is True


def test_desde_finalizado_agregar_item_lleva_a_revision_borrador_con_finalizado_false():
    """Desde FINALIZADO, agregar un ítem de contenido adicional lleva a REVISION_BORRADOR con finalizado False."""
    from baco.server.services.orquestador.sesion import gestor_sesiones

    sid = "test-finalizar-agregar-item"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=101,
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            finalizado=True,
        ),
    )
    SESIONES[sid] = sesion

    gestor_sesiones.agregar_contenido_adicional(sid, "Nota complementaria agregada")

    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.finalizado is False


def test_desde_finalizado_editar_texto_lleva_a_revision_borrador_con_finalizado_false():
    """Desde FINALIZADO, editar el texto con actualizar_borrador_texto lleva a REVISION_BORRADOR con finalizado False."""
    from baco.server.services.orquestador.sesion import gestor_sesiones

    sid = "test-finalizar-editar-texto"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            finalizado=True,
        ),
    )
    SESIONES[sid] = sesion

    ok = gestor_sesiones.actualizar_borrador_texto(sid, "Texto nuevo editado que invalida el borrador.")

    assert ok is True
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.finalizado is False

def test_misma_edicion_sin_cambios_no_invalida_finalizado(client):
    """Verifica que enviar una edición idéntica (sin cambios) desde FINALIZADO no invalida la finalización."""
    sid = "test-misma-edicion-sin-cambios"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            finalizado=True,
            revision_intermedia=False,
        ),
    )
    SESIONES[sid] = sesion

    # Enviamos edición con el mismo texto y título
    r = client.post(
        "/chat",
        headers={"X-Session-ID": sid},
        json={
            "accion": "editar",
            "texto": TEXTO_VALIDO,
            "titulo": "Configurar Punto de Venta Electrónico",
        },
    ).json()

    assert r["estado"] == EstadoFlujo.FINALIZADO
    assert r["mensaje"] == MSG_BORRADOR_FINALIZADO
    assert sesion.estado == EstadoFlujo.FINALIZADO
    assert sesion.borrador.finalizado is True


def test_edicion_con_cambio_real_invalida_finalizado(client):
    """Verifica que una edición con cambios reales desde FINALIZADO invalida la finalización y vuelve a REVISION_BORRADOR."""
    sid = "test-edicion-cambio-real"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            finalizado=True,
            revision_intermedia=False,
        ),
    )
    SESIONES[sid] = sesion

    nuevo_texto = (
        TEXTO_VALIDO + "\n\nSe agrega información adicional sustancial para verificar "
        "que el cambio real en el contenido invalida el estado de finalización del borrador."
    )

    r = client.post(
        "/chat",
        headers={"X-Session-ID": sid},
        json={"accion": "editar", "texto": nuevo_texto},
    ).json()

    assert r["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.finalizado is False


def test_actualizar_borrador_mismo_texto_no_invalida():
    """Verifica que actualizar_borrador_texto con el mismo texto no invalida finalizado."""
    from baco.server.services.orquestador.sesion import gestor_sesiones

    sid = "test-mismo-texto-no-invalida"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            finalizado=True,
        ),
    )
    SESIONES[sid] = sesion

    ok = gestor_sesiones.actualizar_borrador_texto(sid, TEXTO_VALIDO)

    assert ok is True
    assert sesion.estado == EstadoFlujo.FINALIZADO
    assert sesion.borrador.finalizado is True


def test_contenido_adicional_misma_modificacion_no_invalida_y_cambio_real_si():
    """Verifica que modificar un ítem de contenido adicional sin cambios no invalida, pero un cambio real sí."""
    from baco.server.services.orquestador.sesion import gestor_sesiones

    sid = "test-ca-mismo-contenido"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        borrador=BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=101,
            titulo="Artículo Enriquecido",
            bloques_texto=[TEXTO_VALIDO],
            finalizado=True,
        ),
    )
    SESIONES[sid] = sesion
    it = gestor_sesiones.agregar_contenido_adicional(sid, "Contenido base del ítem")

    # Restauramos finalizado y huella
    sesion.estado = EstadoFlujo.FINALIZADO
    sesion.borrador.finalizado = True
    sesion.guardar_huella()

    # 1. Modificar con el mismo contenido no invalida
    gestor_sesiones.modificar_item_contenido_adicional(sid, it.id, "Contenido base del ítem")
    assert sesion.estado == EstadoFlujo.FINALIZADO
    assert sesion.borrador.finalizado is True

    # 2. Reordenar con el mismo orden no invalida
    gestor_sesiones.reordenar_contenido_adicional(sid, [it.id])
    assert sesion.estado == EstadoFlujo.FINALIZADO
    assert sesion.borrador.finalizado is True

    # 3. Modificar con contenido diferente sí invalida
    gestor_sesiones.modificar_item_contenido_adicional(sid, it.id, "Contenido modificado y diferente")
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.finalizado is False



def test_revision_final_metadatos_anteriores_sin_revisar_continuar_no_finaliza_avisa(client):
    """Borrador en revisión final con metadatos_anteriores sin revisar + opción 'continuar':
    no debe finalizar ni recursar, debe responder con el aviso de metadatos heredados."""
    sid = "test-revision-final-meta-pendiente"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        borrador=BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=101,
            titulo="Configurar Punto de Venta Electrónico",
            bloques_texto=[TEXTO_VALIDO],
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            revision_intermedia=False,
            metadatos_anteriores={"categoria_id": 1, "categoria_nombre": "General", "tags": ["instructivo", "ventas"]},
            metadatos_heredados_revisados=False,
        ),
    )
    SESIONES[sid] = sesion

    r = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "continuar"}).json()
    assert r["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.finalizado is False
    assert r["aviso_metadatos_heredados"] is not None
    assert "Debés aceptar o rechazar los metadatos heredados antes de confirmar la finalización" in r["mensaje"]
