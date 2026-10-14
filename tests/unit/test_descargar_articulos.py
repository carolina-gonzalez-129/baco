import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from baco.server.discourse import descargar_articulos as modulo


class Respuesta:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("GET", "https://test"), response=httpx.Response(self.status_code)
            )

    def json(self):
        return self._payload


def test_pedir_reintenta_rate_limit_y_devuelve_json():
    http = MagicMock()
    http.get.side_effect = [
        Respuesta(429, headers={"Retry-After": "1"}),
        Respuesta(200, {"ok": True}),
    ]

    with patch.object(modulo.time, "sleep"):
        assert modulo.pedir(http, "/latest.json") == {"ok": True}

    assert http.get.call_count == 2


def test_pedir_propaga_error_despues_de_agotar_reintentos():
    http = MagicMock()
    http.get.side_effect = httpx.ConnectError("sin conexión")

    with patch.object(modulo.time, "sleep"), pytest.raises(httpx.ConnectError):
        modulo.pedir(http, "/latest.json")


def test_listar_temas_recorrre_paginas_hasta_que_no_haya_mas():
    http = MagicMock()
    respuestas = iter(
        [
            {"topic_list": {"topics": [{"id": 1}], "more_topics_url": "/latest?page=1"}},
            {"topic_list": {"topics": [{"id": 2}], "more_topics_url": None}},
        ]
    )

    with patch.object(modulo, "pedir", side_effect=lambda *_args, **_kwargs: next(respuestas)):
        assert list(modulo.listar_temas(http)) == [{"id": 1}, {"id": 2}]


def test_limpiar_texto_elimina_html_y_preserva_lineas():
    html = "<h1>Título</h1><p>Primer párrafo</p><p>Segundo <b>párrafo</b></p>"

    assert modulo.limpiar_texto(html) == "Título\nPrimer párrafo\nSegundo\npárrafo"


def test_guardar_escribe_json_atomico(tmp_path):
    salida = tmp_path / "data" / "articulos.json"
    salida.parent.mkdir()
    with patch.object(modulo, "SALIDA", salida):
        modulo.guardar({1: {"id": 1, "titulo": "Artículo"}})

    assert json.loads(salida.read_text(encoding="utf-8")) == [{"id": 1, "titulo": "Artículo"}]
    assert not salida.with_suffix(".json.tmp").exists()
