import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.api import get_buscador_duplicados
from baco.server.services.buscar_duplicados import BuscadorDuplicados


@pytest.fixture
def mock_buscador_api():
    return MagicMock(spec=BuscadorDuplicados)


@pytest.fixture
def client_api(mock_buscador_api):
    def override_buscador():
        yield mock_buscador_api

    app.dependency_overrides[get_buscador_duplicados] = override_buscador

    with patch("baco.server.app.main.db_pool"):
        with patch("baco.server.services.embeddings.get_model_titulo"):
            with patch("baco.server.services.embeddings.get_model_texto"):
                with TestClient(app, raise_server_exceptions=False) as test_client:
                    yield test_client

    app.dependency_overrides.clear()


def test_api_payload_invalido_retorna_422_unprocessable_entity(client_api):
    """
    Regla: Si el cuerpo de la solicitud no respeta el esquema requerido (por ejemplo, tipos incompatibles),
    la API debe rechazarlo inmediatamente con código HTTP 422 Unprocessable Entity.
    """
    payload_invalido = {
        "id": "NO_ES_UN_NUMERO",
        "categoria_id": "TAMPOCO_ES_NUMERO",
        "tags": "DEBERIA_SER_LISTA"
    }

    resp = client_api.post("/validar_post_duplicados", json=payload_invalido)
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.xfail(
    reason="Regla de negocio: el parámetro 'limite' debe estar acotado entre 1 y 10. "
           "El endpoint /buscar_duplicados actual define 'limite: int = 3' sin Query(ge=1, le=10), "
           "permitiendo límites arbitrarios (ej. 0 o 100).",
    strict=True
)
def test_api_limite_fuera_de_rango_1_a_10_debe_retornar_422(client_api):
    """
    Regla: El parámetro límite debe restringirse al rango de 1 a 10 resultados.
    Valores inferiores a 1 o superiores a 10 deben rechazarse con error de validación 422.
    """
    resp_cero = client_api.get("/buscar_duplicados", params={"titulo": "Factura", "limite": 0})
    resp_cien = client_api.get("/buscar_duplicados", params={"titulo": "Factura", "limite": 100})

    assert resp_cero.status_code == 422, "limite=0 debe ser rechazado con 422"
    assert resp_cien.status_code == 422, "limite=100 debe ser rechazado con 422"


def test_api_tags_vacios_retorna_articulo_invalido_con_hallazgo_bloqueante(client_api):
    """
    Regla: Un artículo presentado sin etiquetas (tags=[]) debe ser invalidado determinísticamente
    por el endpoint /validar_post_duplicados, reportando status Pendiente y hallazgo bloqueante.
    """
    articulo_sin_tags = {
        "id": 701,
        "titulo": "Configuración de Parámetros AFIP",
        "categoria_id": 5,
        "tags": [],
        "texto": (
            "Para configurar el punto de venta de facturación electrónica en Finnegans, "
            "es necesario verificar que los parámetros de AFIP estén sincronizados. "
            "Primero ingresar al módulo de Ventas, luego seleccionar Configuración de Parámetros. "
            "Allí verificar el número de punto de venta asignado por el ente fiscal."
        )
    }

    resp = client_api.post("/validar_post_duplicados", json=articulo_sin_tags)
    assert resp.status_code == 200
    data = resp.json()

    assert data["valido"] is False
    assert data["status"] == "Pendiente"
    assert any(
        f["severity"] == "Bloqueante" and f["field"] == "tags"
        for f in data["findings"]
    )


def test_api_error_de_base_de_datos_retorna_error_controlado_sin_traceback(client_api, mock_buscador_api):
    """
    Regla: Ante una caída o error inesperado en la base de datos, la API debe devolver
    un error HTTP controlado (500) y JAMÁS filtrar tracebacks de código interno al cliente.
    """
    mock_buscador_api.buscar_por_titulo.side_effect = RuntimeError(
        "Falla catastrófica de conexión al socket PostgreSQL: connection refused"
    )

    resp = client_api.get("/titulo_exacto", params={"titulo": "Prueba de caída DB"})

    assert resp.status_code == 500
    # Seguridad: no filtrar traceback en la respuesta HTTP
    assert "Traceback (most recent call last)" not in resp.text
    assert "baco/server/" not in resp.text
