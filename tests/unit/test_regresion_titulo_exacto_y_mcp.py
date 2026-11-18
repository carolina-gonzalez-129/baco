from unittest.mock import MagicMock, patch

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
