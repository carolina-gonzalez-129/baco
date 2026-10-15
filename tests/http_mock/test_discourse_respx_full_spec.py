import pytest
import respx
import httpx
from datetime import datetime, timezone
from unittest.mock import MagicMock

from baco.server.discourse.actualizar_articulos_editados import pedir, ErrorAPIDiscourse
from baco.server.discourse.actualizar_nuevos_articulos import sincronizar_articulos

BASE_URL = "https://bc-dev.finneg.com"


@respx.mock(assert_all_mocked=True)
def test_discourse_paginacion_multiples_paginas(respx_mock):
    """Verifica que la paginación avance correctamente por múltiples páginas."""
    respx_mock.get(f"{BASE_URL}/latest.json", params={"page": "0", "order": "created"}).respond(
        200, json={"topic_list": {"topics": [{"id": 101, "title": "Tema 101"}]}}
    )
    respx_mock.get(f"{BASE_URL}/latest.json", params={"page": "1", "order": "created"}).respond(
        200, json={"topic_list": {"topics": [{"id": 102, "title": "Tema 102"}]}}
    )
    respx_mock.get(f"{BASE_URL}/latest.json", params={"page": "2", "order": "created"}).respond(
        200, json={"topic_list": {"topics": []}}  # Fin de la paginación
    )

    with httpx.Client(base_url=BASE_URL) as client:
        p0 = client.get("/latest.json", params={"page": 0, "order": "created"}).json()
        p1 = client.get("/latest.json", params={"page": 1, "order": "created"}).json()
        p2 = client.get("/latest.json", params={"page": 2, "order": "created"}).json()

        assert len(p0["topic_list"]["topics"]) == 1
        assert len(p1["topic_list"]["topics"]) == 1
        assert len(p2["topic_list"]["topics"]) == 0


@respx.mock(assert_all_mocked=True)
def test_discourse_error_429_con_retry_after(respx_mock, monkeypatch):
    """Comprueba que ante 429 se lea el header Retry-After y se reintente con éxito."""
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    route = respx_mock.get(f"{BASE_URL}/posts.json")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"latest_posts": []})
    ]

    with httpx.Client(base_url=BASE_URL) as client:
        datos = pedir(client, "/posts.json")
        assert datos == {"latest_posts": []}
        assert route.call_count == 2


@respx.mock(assert_all_mocked=True)
def test_discourse_timeout_lanza_error_controlado(respx_mock, monkeypatch):
    """Verifica que un timeout repetido agote los reintentos y levante ErrorAPIDiscourse."""
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    route = respx_mock.get(f"{BASE_URL}/t/999.json")
    route.side_effect = httpx.ConnectTimeout("Connection timed out")

    with httpx.Client(base_url=BASE_URL) as client:
        with pytest.raises(ErrorAPIDiscourse) as exc_info:
            pedir(client, "/t/999.json")
        assert "tras 5 intentos" in str(exc_info.value)
        assert route.call_count == 5


@respx.mock(assert_all_mocked=True)
def test_discourse_respuesta_vacia_retorna_json_vacio(respx_mock):
    """Verifica el comportamiento ante endpoints que devuelven JSON vacío."""
    respx_mock.get(f"{BASE_URL}/posts.json").respond(200, json={})

    with httpx.Client(base_url=BASE_URL) as client:
        res = pedir(client, "/posts.json")
        assert res == {}


@respx.mock(assert_all_mocked=True)
def test_tema_borrado_en_discourse_se_reporta_pero_no_se_elimina_sin_flag_purgar(respx_mock, monkeypatch, capsys):
    """
    Cuando un artículo está en la base pero ya no en Discourse:
    En modo --completo SIN --purgar, se reporta en el resumen pero NO se ejecuta DELETE.
    """
    respx_mock.get(f"{BASE_URL}/latest.json", params={"page": 0, "order": "created"}).respond(
        200,
        json={"topic_list": {"topics": [{"id": 50, "title": "Tema Vigente"}]}}
    )
    respx_mock.get(f"{BASE_URL}/t/50.json").respond(
        200,
        json={
            "id": 50,
            "title": "Tema Vigente",
            "category_id": 1,
            "slug": "tema-vigente",
            "post_stream": {"posts": [{"post_number": 1, "raw": "Contenido", "updated_at": "2026-10-14T10:00:00Z"}]}
        }
    )

    # Base con el tema 50 (vigente) y el tema 99 (borrado de Discourse)
    cur = MagicMock()
    cur.fetchall.return_value = [(50,), (99,)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    monkeypatch.setattr("baco.server.discourse.actualizar_nuevos_articulos.get_conn", lambda: conn)
    monkeypatch.setattr("baco.server.discourse.actualizar_nuevos_articulos.upsert_articulos", lambda c, arts: MagicMock(insertados=0, actualizados=0))
    monkeypatch.setattr("baco.server.discourse.actualizar_nuevos_articulos.actualizar_embeddings_articulo", lambda c, tid, tit, txt: False)

    codigo = sincronizar_articulos(completo=True, purgar=False)
    assert codigo == 0

    # Verificar que NO se ejecutó ninguna query DELETE
    deletes = [c for c in cur.execute.call_args_list if c.args and "DELETE FROM articulos" in str(c.args[0])]
    assert len(deletes) == 0

    captured = capsys.readouterr()
    assert "artículos están en la base pero ya no en Discourse" in captured.out
    assert "99" in captured.out


@respx.mock(assert_all_mocked=True)
def test_llamada_no_mockeada_falla_automaticamente(respx_mock):
    """Verifica que si se intenta hacer una llamada a una ruta no mockeada, el test falla de inmediato."""
    with httpx.Client(base_url=BASE_URL) as client:
        with pytest.raises(respx.models.AllMockedAssertionError):
            client.get("/ruta-no-mockeada")
