import asyncio
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.api import get_buscador_duplicados, get_baco_agent
from baco.server.services.buscar_duplicados import BuscadorDuplicados


@pytest.fixture(scope="module")
def mock_buscador():
    """Crea un mock completo de BuscadorDuplicados para aislar los tests de la DB real."""
    return MagicMock(spec=BuscadorDuplicados)


@pytest.fixture(scope="module")
def client(mock_buscador):
    """Cliente de pruebas de FastAPI con dependencias y recursos mockeados."""
    def override_get_buscador_duplicados():
        yield mock_buscador

    app.dependency_overrides[get_buscador_duplicados] = override_get_buscador_duplicados

    with patch("baco.server.app.main.db_pool"):
        with patch("baco.server.services.embeddings.get_model_titulo"):
            with patch("baco.server.services.embeddings.get_model_texto"):
                with TestClient(app) as test_client:
                    yield test_client

    app.dependency_overrides.clear()


# ==============================================================================
# 1. Tests de la API REST (api.py)
# ==============================================================================

def test_endpoint_titulo_exacto_encontrado(client, mock_buscador):
    mock_buscador.buscar_por_titulo.return_value = [
        (10, "Factura Electronica", "https://bc.finneg.com/t/10")
    ]
    resp = client.get("/titulo_exacto", params={"titulo": "Factura Electronica"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://bc.finneg.com/t/10"
    assert "Ya hay un titulo exactamente igual" in data["mensaje"]


def test_endpoint_titulo_exacto_no_encontrado(client, mock_buscador):
    mock_buscador.buscar_por_titulo.return_value = []
    resp = client.get("/titulo_exacto", params={"titulo": "Titulo Inexistente"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] is None


def test_endpoint_buscar_duplicados(client, mock_buscador):
    mock_buscador.evaluar_coincidencias.return_value = {
        "encontrado": True,
        "mensaje": "Coincidencia exacta por titulo",
        "link": "https://bc.finneg.com/t/55"
    }
    resp = client.get("/buscar_duplicados", params={"titulo": "Facturacion AFIP", "limite": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert data["encontrado"] is True
    assert data["link"] == "https://bc.finneg.com/t/55"


def test_endpoint_validar_post_duplicados_bloqueante_texto_corto(client):
    payload = {
        "id": 1,
        "titulo": "Prueba Corta",
        "texto": "Muy corto",
        "categoria_id": 5,
        "tags": [{"name": "instructivo"}, {"name": "ventas"}]
    }
    resp = client.post("/validar_post_duplicados", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valido"] is False
    assert data["status"] == "Pendiente"
    assert any("muy breve" in f["description"] for f in data["findings"])


def test_endpoint_validar_post_duplicados_valido(client):
    texto_valido_mas_300 = (
        "Este es un texto explicativo con una extension lo suficientemente extensa como para superar "
        "con total comodidad los 300 caracteres que exige la regla de negocio del sistema de documentacion "
        "de Finnegans. No contiene marcadores pendientes de tipo indicar y detalla de manera exhaustiva "
        "todas las instrucciones necesarias para la configuracion correcta del modulo."
    )
    payload = {
        "id": 2,
        "titulo": "Configuracion de Factura",
        "texto": texto_valido_mas_300,
        "categoria_id": 5,
        "tags": [{"name": "instructivo"}, {"name": "ventas"}]
    }
    resp = client.post("/validar_post_duplicados", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valido"] is True
    assert data["status"] == "Listo"


# ==============================================================================
# 2. Tests del Servidor MCP (mcp_server.py)
# ==============================================================================

def test_mcp_server_expone_solo_una_tool():
    """Garantiza que el servidor FastMCP solo registre y exponga consultar_agente_baco."""
    from baco.server.app.mcp_server import mcp
    tools = asyncio.run(mcp.list_tools())
    nombres_tools = [t.name for t in tools]
    assert nombres_tools == ["consultar_agente_baco"]
    assert len(nombres_tools) == 1


def test_mcp_server_consultar_agente_delega_y_serializa_respuesta():
    from baco.server.app.mcp_server import consultar_agente_baco

    agente = MagicMock(return_value=123)
    with patch("baco.server.app.mcp_server.create_agent", return_value=agente):
        resultado = consultar_agente_baco("validar este artículo")

    agente.assert_called_once_with("validar este artículo")
    assert resultado == "123"


def test_chat_baco_delega_al_agente_inyectado(client):
    agente = MagicMock(return_value="respuesta del agente")
    app.dependency_overrides[get_baco_agent] = lambda: agente
    try:
        resp = client.post("/chat_baco", json={"prompt": "hola"})
    finally:
        app.dependency_overrides.pop(get_baco_agent, None)

    assert resp.status_code == 200
    assert resp.json() == {"response": "respuesta del agente"}
    agente.assert_called_once_with("hola")


def test_chat_baco_rechaza_prompt_ausente(client):
    app.dependency_overrides[get_baco_agent] = lambda: MagicMock()
    try:
        resp = client.post("/chat_baco", json={})
    finally:
        app.dependency_overrides.pop(get_baco_agent, None)

    assert resp.status_code == 422


# ==============================================================================
# 3. Tests del Orquestador y OpenAPI (main.py)
# ==============================================================================

def test_main_app_incluye_rutas_esperadas(client):
    """Verifica que las rutas REST y el montaje MCP esten registrados en OpenAPI."""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"].keys()
    assert "/titulo_exacto" in paths
    assert "/buscar_duplicados" in paths
    assert "/validar_post_duplicados" in paths
    assert "/chat_baco" in paths
