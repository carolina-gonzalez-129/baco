from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados
from baco.server.app.main import app
from baco.server.services.buscar_duplicados import BuscadorDuplicados, extraer_url


def _patches_arranque():
    return (
        patch("baco.server.db.config.crear_ro_pool"),
        patch("baco.server.services.embeddings.get_model_titulo"),
        patch("baco.server.services.embeddings.get_model_texto"),
    )


def test_extraer_url_soporta_dict_y_tupla():
    assert extraer_url({"id": 1, "titulo": "x", "url": "https://a/t/1"}) == "https://a/t/1"
    assert extraer_url((1, "x", "https://a/t/1")) == "https://a/t/1"
    assert extraer_url(None) is None


def test_titulo_exacto_con_filas_dict_como_las_devuelve_dict_row():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)
    with patch.object(buscador, "buscar_por_titulo", return_value=[{"id": 10, "titulo": "Factura", "url": "https://bc/t/10"}]):
        res = buscador.evaluar_titulo("Factura")
        assert res is not None
        assert res["link"] == "https://bc/t/10"


def test_mcp_se_monta_en_la_raiz_para_que_el_endpoint_sea_slash_mcp():
    from baco.server.app.mcp_server import mcp_http_app

    assert "/mcp" in {getattr(r, "path", None) for r in mcp_http_app.routes}
    montajes = [r for r in app.routes if r.__class__.__name__ == "Mount"]
    assert any(m.path == "" for m in montajes)  # Starlette normaliza el mount "/" a ""
    assert not any(m.path == "/mcp" for m in montajes)  # antes: /mcp + /mcp = /mcp/mcp


def test_lifespan_de_la_app_ejecuta_el_lifespan_de_fastmcp():
    eventos = []

    @asynccontextmanager
    async def fake_lifespan(a):
        eventos.append("entro")
        yield
        eventos.append("salio")

    p1, p2, p3 = _patches_arranque()
    with p1, p2, p3, patch("baco.server.app.main.mcp_http_app") as mock_mcp:
        mock_mcp.lifespan = fake_lifespan
        with TestClient(app):
            assert eventos == ["entro"]
    assert eventos == ["entro", "salio"]
