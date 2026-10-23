from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.api import get_buscador_duplicados
from baco.server.app.middleware import API_KEY
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.app.mcp_server import validar_formato


@pytest.fixture
def mock_buscador_api():
    return MagicMock(spec=BuscadorDuplicados)


@pytest.fixture
def client_api(mock_buscador_api):
    def override_buscador():
        yield mock_buscador_api

    app.dependency_overrides[get_buscador_duplicados] = override_buscador

    with patch("baco.server.db.config.crear_ro_pool"):
        with patch("baco.server.services.embeddings.get_model_titulo"):
            with patch("baco.server.services.embeddings.get_model_texto"):
                with TestClient(app, headers={"X-API-Key": API_KEY}, raise_server_exceptions=False) as test_client:
                    yield test_client

    app.dependency_overrides.clear()


def test_api_payload_invalido_retorna_422_unprocessable_entity(client_api):
    payload_invalido = {
        "categoria_id": "TAMPOCO_ES_NUMERO",
        "tags": "DEBERIA_SER_LISTA"
    }

    resp = client_api.post("/chat", json=payload_invalido)
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_api_tags_vacios_retorna_articulo_invalido_con_hallazgo_bloqueante():
    texto_valido = (
        "Para configurar el punto de venta de facturación electrónica en Finnegans, "
        "es necesario verificar que los parámetros de AFIP estén sincronizados. "
        "Primero ingresar al módulo de Ventas, luego seleccionar Configuración de Parámetros. "
        "Allí verificar el número de punto de venta asignado por el ente fiscal."
    )
    resultado = validar_formato(
        titulo="Configuración de Parámetros AFIP",
        texto=texto_valido,
        tags=[],
        categoria_id=5
    )

    assert resultado.valido is False
    assert resultado.status == "Pendiente"
    assert any(
        h.severidad == "Bloqueante" and h.campo == "tags"
        for h in resultado.hallazgos
    )


def test_api_error_de_base_de_datos_retorna_error_controlado_sin_traceback(client_api, mock_buscador_api):
    mock_buscador_api.evaluar_titulo.side_effect = RuntimeError(
        "Falla catastrófica de conexión al socket PostgreSQL: connection refused"
    )

    resp = client_api.post("/chat", json={"mensaje": "Prueba de caída DB con título largo válido"})

    assert resp.status_code == 500
    assert "Traceback (most recent call last)" not in resp.text
    assert "baco/server/" not in resp.text
