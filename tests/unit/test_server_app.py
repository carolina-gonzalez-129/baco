import asyncio
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.api import get_buscador_duplicados
from baco.server.app.middleware import API_KEY, DOCS_USER, DOCS_PASSWORD
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.schemas.chat_orquestado import EstadoFlujo


@pytest.fixture(scope="module")
def mock_buscador():
    return MagicMock(spec=BuscadorDuplicados)


@pytest.fixture(scope="module")
def client(mock_buscador):
    def override_get_buscador_duplicados():
        yield mock_buscador

    app.dependency_overrides[get_buscador_duplicados] = override_get_buscador_duplicados

    with patch("baco.server.db.config.crear_ro_pool"):
        with patch("baco.server.services.embeddings.get_model_titulo"):
            with patch("baco.server.services.embeddings.get_model_texto"):
                with TestClient(app, headers={"X-API-Key": API_KEY}) as test_client:
                    yield test_client

    app.dependency_overrides.clear()


# ==============================================================================
# 1. Tests de la API REST (api.py)
# ==============================================================================

def test_endpoint_chat_bienvenida_y_seteo_cookie(client):
    resp = client.post("/chat", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] == EstadoFlujo.ESPERANDO_TITULO
    assert "baco_session" in client.cookies
    assert client.cookies["baco_session"] == data["session_id"]
    assert resp.headers.get("X-Session-ID") == data["session_id"]


def test_endpoint_borrador_sin_credencial_retorna_401():
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as unauth_client:
            unauth_client.cookies.clear()
            resp = unauth_client.get("/chat/borrador")
            assert resp.status_code == 401
            assert "No se encontró una sesión activa" in resp.json()["detail"]


def test_endpoint_aplicar_plantilla_sin_credencial_retorna_401():
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as unauth_client:
            unauth_client.cookies.clear()
            resp = unauth_client.post("/chat/aplicar-plantilla")
            assert resp.status_code == 401


def test_endpoint_auditar_semantica_sin_credencial_retorna_401():
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as unauth_client:
            unauth_client.cookies.clear()
            resp = unauth_client.post("/chat/auditar-semantica")
            assert resp.status_code == 401


def test_endpoint_revalidar_post_skill_sin_credencial_retorna_401():
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as unauth_client:
            unauth_client.cookies.clear()
            resp = unauth_client.post("/chat/revalidar-post-skill")
            assert resp.status_code == 401


# ==============================================================================
# 3. Tests de OpenAPI y Rutas (main.py)
# ==============================================================================

def test_main_app_incluye_rutas_esperadas(client):
    resp = client.get("/openapi.json", auth=(DOCS_USER, DOCS_PASSWORD))
    assert resp.status_code == 200
    schema = resp.json()
    paths = schema["paths"].keys()
    assert "/chat" in paths
    assert "/chat/borrador" in paths
    assert "/chat/aplicar-plantilla" in paths
    assert "/chat/auditar-semantica" in paths
    assert "/chat/revalidar-post-skill" in paths
