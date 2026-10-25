from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.api import get_buscador_duplicados
from baco.server.app.middleware import API_KEY
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.schemas.chat_orquestado import BorradorSesion, EstadoFlujo
from baco.server.services.orquestador.sesion import (
    SESIONES,
    TTL_SEGUNDOS,
    SesionChat,
)

TEXTO_VALIDO = (
    "Para dar de alta un punto de venta en Finnegans ERP es necesario ingresar al maestro de "
    "puntos de venta en el módulo de Ventas, asociar el certificado digital vigente otorgado "
    "por AFIP y comprobar que el tipo de comprobante electrónico se encuentre habilitado."
)


@pytest.fixture(autouse=True)
def limpiar_sesiones():
    SESIONES.clear()
    yield
    SESIONES.clear()


@pytest.fixture
def mock_buscador():
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.cur = MagicMock()
    buscador.obtener_articulo.return_value = None
    buscador.evaluar_titulo.return_value = {"mensaje": "Sin duplicados", "coincidencias": []}
    buscador.evaluar_texto.return_value = {"mensaje": "Sin duplicados", "coincidencias": []}
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


def test_prioridad_cookie_gana_sobre_header(client):
    sid_cookie = "sesion-cookie-ganadora"
    sid_header = "sesion-header-perdedora"

    SESIONES[sid_cookie] = SesionChat(
        session_id=sid_cookie,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Título Cookie",
        texto=TEXTO_VALIDO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título Cookie",
            texto=TEXTO_VALIDO,
            texto_original_conforme=TEXTO_VALIDO,
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            tipo_plantilla="instructivo",
        ),
    )
    SESIONES[sid_header] = SesionChat(
        session_id=sid_header,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Título Header",
        texto=TEXTO_VALIDO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título Header",
            texto=TEXTO_VALIDO,
            texto_original_conforme=TEXTO_VALIDO,
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            tipo_plantilla="instructivo",
        ),
    )

    client.cookies.set("baco_session", sid_cookie)
    resp = client.get("/chat/borrador", headers={"X-Session-ID": sid_header})

    assert resp.status_code == 200
    assert resp.json()["titulo"] == "Título Cookie"


def test_prioridad_header_gana_sobre_body_y_body_se_ignora(client):
    sid_header = "sesion-header-valida"
    SESIONES[sid_header] = SesionChat(
        session_id=sid_header,
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo="Título Existente en Header",
        texto="",
    )

    client.cookies.clear()
    resp = client.post(
        "/chat",
        headers={"X-Session-ID": sid_header},
        json={
            "session_id": "sesion-inventada-en-body",
            "accion": "confirmar_texto",
            "texto": TEXTO_VALIDO,
            "tags": ["instructivo", "ventas"],
            "categoria_id": 5,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["session_id"] == sid_header
    assert resp.json()["estado"] == EstadoFlujo.REVISION_BORRADOR


def test_body_session_id_se_ignora_completamente_creando_sesion_nueva(client):
    id_forzado_en_body = "mi-id-arbitrario-1234"
    client.cookies.clear()

    resp = client.post(
        "/chat",
        json={"session_id": id_forzado_en_body, "mensaje": "Título para Nuevo Artículo Válido"}
    )

    assert resp.status_code == 200
    sid_asignado = resp.json()["session_id"]
    assert sid_asignado != id_forzado_en_body
    assert id_forzado_en_body not in SESIONES
    assert sid_asignado in SESIONES


def test_cookie_sale_con_httponly_path_y_max_age_igual_a_ttl(client):
    client.cookies.clear()
    resp = client.post("/chat", json={})
    assert resp.status_code == 200

    set_cookie = resp.headers.get("set-cookie", "")
    assert f"Max-Age={TTL_SEGUNDOS}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/" in set_cookie


def test_estado_rechazado_borra_la_cookie(client):
    sid = "sesion-a-rechazar"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Artículo Rechazable",
        texto=TEXTO_VALIDO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Artículo Rechazable",
            texto=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
        ),
    )

    client.cookies.set("baco_session", sid)
    client.post("/chat", json={"accion": "rechazar"})
    resp = client.post("/chat", json={"accion": "confirmar_rechazo"})

    assert resp.status_code == 200
    assert resp.json()["estado"] == EstadoFlujo.RECHAZADO

    # Al ser RECHAZADO, debe eliminarse la cookie baco_session
    set_cookie = resp.headers.get("set-cookie", "")
    assert ('baco_session=""' in set_cookie or "Max-Age=0" in set_cookie or "baco_session=;" in set_cookie)


def test_estado_conformidad_mantiene_cookie_y_permite_get_borrador(client):
    sid = "sesion-a-dar-conformidad"
    from baco.server.schemas.validacion import ResumenValidacionSchema, ValidarFormatoResponse
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Artículo para Conformidad",
        texto=TEXTO_VALIDO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Artículo para Conformidad",
            texto=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
        ),
        validacion=ValidarFormatoResponse(
            valido=True,
            status="Listo",
            findings=[],
            resumen=ResumenValidacionSchema(longitud_texto=len(TEXTO_VALIDO), tags_count=2),
        ),
    )

    client.cookies.set("baco_session", sid)
    resp = client.post("/chat", json={"accion": "conforme"})

    assert resp.status_code == 200
    assert resp.json()["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO

    set_cookie = resp.headers.get("set-cookie", "")
    assert f"Max-Age={TTL_SEGUNDOS}" in set_cookie

    # El front consulta GET /chat/borrador tras dar conformidad y la cookie sigue activa
    resp_borrador = client.get("/chat/borrador")
    assert resp_borrador.status_code == 200
    assert resp_borrador.json()["titulo"] == "Artículo para Conformidad"


def test_endpoints_sin_sesion_retornan_401(client):
    client.cookies.clear()

    resp_borrador = client.get("/chat/borrador")
    assert resp_borrador.status_code == 401
    assert "No se encontró una sesión activa" in resp_borrador.json()["detail"]

    resp_plantilla = client.post("/chat/aplicar-plantilla")
    assert resp_plantilla.status_code == 401
    assert "No se encontró una sesión activa" in resp_plantilla.json()["detail"]

    resp_semantica = client.post("/chat/auditar-semantica")
    assert resp_semantica.status_code == 401
    assert "No se encontró una sesión activa" in resp_semantica.json()["detail"]


def test_cors_preflight_origen_permitido(client):
    resp = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, X-API-Key",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_origen_no_permitido(client):
    resp = client.options(
        "/chat",
        headers={
            "Origin": "https://sitio-malicioso.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") is None
    assert resp.headers.get("access-control-allow-credentials") is None
