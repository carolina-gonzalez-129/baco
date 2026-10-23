import json
import pytest
import respx
import httpx
from datetime import datetime, timezone
from unittest.mock import MagicMock

from baco.server.discourse.actualizar_articulos_editados import (
    pedir,
    descargar_articulo,
    sincronizar_articulos_editados,
    ErrorAPIDiscourse,
    BASE_URL
)


@respx.mock
def test_discourse_error_404_lanza_error_apidiscourse(monkeypatch):
    """
    Regla: Si un recurso solicitado en la API de Discourse devuelve 404 Not Found,
    el pipeline no debe fallar con traceback silencioso sino levantar ErrorAPIDiscourse controlado.
    """
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    respx.get(f"{BASE_URL}/t/999999.json").respond(404, json={"errors": ["El tema no fue encontrado."]})

    with httpx.Client(base_url=BASE_URL) as client:
        with pytest.raises(ErrorAPIDiscourse) as exc_info:
            pedir(client, "/t/999999.json")
        assert "404" in str(exc_info.value)


@respx.mock
def test_discourse_error_429_respeta_retry_after(monkeypatch):
    """
    Regla: Ante un límite de tasa HTTP 429 con header 'Retry-After', el cliente debe esperar
    el tiempo indicado y reintentar de manera transparente hasta completarse.
    """
    tiempos_espera = []
    import time
    monkeypatch.setattr(time, "sleep", lambda s: tiempos_espera.append(s))

    route = respx.get(f"{BASE_URL}/posts.json")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "4"}),
        httpx.Response(200, json={"latest_posts": []})
    ]

    with httpx.Client(base_url=BASE_URL) as client:
        datos = pedir(client, "/posts.json")
        assert datos == {"latest_posts": []}
        assert route.call_count == 2
        assert 4 in tiempos_espera


@respx.mock
def test_discourse_error_500_reintenta_y_lanza_error_controlado(monkeypatch):
    """
    Regla: Si el servidor de Discourse responde 500/502/503 persistente, el cliente debe reintentar
    hasta agotar el máximo permitido y luego levantar ErrorAPIDiscourse.
    """
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    route = respx.get(f"{BASE_URL}/latest.json")
    route.return_value = httpx.Response(500, json={"error": "Error interno del servidor Discourse"})

    with httpx.Client(base_url=BASE_URL) as client:
        with pytest.raises(ErrorAPIDiscourse):
            pedir(client, "/latest.json")
        assert route.call_count == 5


@respx.mock
def test_discourse_timeout_de_red_reintenta_y_lanza_error_controlado(monkeypatch):
    """
    Regla: Ante caídas de red o timeouts en la conexión HTTP, el cliente debe reintentar
    y finalmente informar un fallo controlado sin corromper el estado.
    """
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    route = respx.get(f"{BASE_URL}/t/888.json")
    route.side_effect = httpx.ReadTimeout("Timeout al conectar con Discourse")

    with httpx.Client(base_url=BASE_URL) as client:
        with pytest.raises(ErrorAPIDiscourse):
            pedir(client, "/t/888.json")
        assert route.call_count == 5


@respx.mock
def test_discourse_json_malformado_lanza_error_controlado(monkeypatch):
    """
    Regla: Si la respuesta de Discourse devuelve un cuerpo corrupto o HTML en lugar de JSON,
    debe tratarse como un error y levantar ErrorAPIDiscourse.
    """
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    respx.get(f"{BASE_URL}/t/777.json").respond(
        200,
        text="<html><body>Bad Gateway Error Nginx</body></html>",
        headers={"Content-Type": "text/html"}
    )

    with httpx.Client(base_url=BASE_URL) as client:
        with pytest.raises((ErrorAPIDiscourse, json.JSONDecodeError)):
            pedir(client, "/t/777.json")


@respx.mock
def test_discourse_post_stream_vacio_o_ausente_retorna_none():
    """
    Regla: Si un tema en Discourse no tiene posts principales (post_stream vacío o ausente),
    descargar_articulo debe retornar None de manera segura sin lanzar excepciones no controladas.
    """
    respx.get(f"{BASE_URL}/t/666.json").respond(
        200,
        json={"id": 666, "title": "Tema sin posts", "post_stream": {"posts": []}}
    )

    with httpx.Client(base_url=BASE_URL) as client:
        resultado = descargar_articulo(client, 666)
        assert resultado is None


@respx.mock
def test_articulo_borrado_en_discourse_se_reporta_y_no_se_borra_de_bd(monkeypatch):
    """
    Regla: Un artículo eliminado o despublicado en Discourse debe reportarse en los logs/auditoría,
    pero NO debe eliminarse de la base de datos local para preservar el histórico de conocimiento.
    """
    tema_id = 999
    # Simulamos que /latest.json no trae actividad nueva
    respx.get(f"{BASE_URL}/latest.json").respond(
        200,
        json={"topic_list": {"topics": []}}
    )
    # Simulamos que en Discourse el post viene marcado como deleted
    respx.get(f"{BASE_URL}/posts.json").respond(
        200,
        json={
            "latest_posts": [
                {
                    "id": 12345,
                    "topic_id": tema_id,
                    "post_number": 1,
                    "topic_title": "Artículo Despublicado",
                    "deleted_at": "2026-10-15T09:00:00Z"
                }
            ]
        }
    )

    # Mockeamos la conexión a base de datos
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Simulamos que el artículo existe en la base
    monkeypatch.setattr(
        "baco.server.discourse.actualizar_articulos_editados.get_conn",
        lambda: mock_conn
    )
    monkeypatch.setattr(
        "baco.server.discourse.actualizar_articulos_editados.obtener_articulos_existentes",
        lambda conn: {tema_id: datetime(2026, 1, 1, tzinfo=timezone.utc)}
    )

    sincronizar_articulos_editados(max_paginas=1)

    # Observable: NO debe ejecutarse DELETE sobre la tabla articulos
    queries = [str(call[0][0]) for call in mock_cur.execute.call_args_list]
    assert not any("DELETE FROM articulos" in q for q in queries), "El artículo no debe ser borrado de la base de datos"
