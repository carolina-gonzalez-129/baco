import json
import pytest
import respx
import httpx
from datetime import datetime, timezone

from baco.server.discourse.actualizar_articulos_editados import pedir, ErrorAPIDiscourse
from baco.server.db.ingesta import normalizar_articulo

BASE_URL = "https://bc-dev.finneg.com"


@respx.mock
def test_pedir_con_429_y_retry_after():
    """Simula un 429 con Retry-After que se recupera exitosamente en el segundo intento."""
    route = respx.get(f"{BASE_URL}/test-rate-limit")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"status": "recuperado"})
    ]

    with httpx.Client(base_url=BASE_URL) as client:
        res = pedir(client, "/test-rate-limit")
        assert res == {"status": "recuperado"}
        assert route.call_count == 2


@respx.mock
def test_pedir_con_502_bad_gateway_reintenta():
    """Simula un 502/503 del proxy/gateway que se recupera en el siguiente intento."""
    route = respx.get(f"{BASE_URL}/test-502")
    route.side_effect = [
        httpx.Response(502),
        httpx.Response(200, json={"ok": True})
    ]

    with httpx.Client(base_url=BASE_URL) as client:
        res = pedir(client, "/test-502")
        assert res == {"ok": True}
        assert route.call_count == 2


@respx.mock
def test_pedir_falla_tras_max_reintentos(monkeypatch):
    """Verifica que tras 5 intentos fallidos levante ErrorAPIDiscourse."""
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    route = respx.get(f"{BASE_URL}/test-falla-total")
    route.return_value = httpx.Response(500, json={"error": "Server Error"})

    with httpx.Client(base_url=BASE_URL) as client:
        with pytest.raises(ErrorAPIDiscourse):
            pedir(client, "/test-falla-total")
    assert route.call_count == 5


@respx.mock
def test_normalizacion_articulo_discourse_mock():
    """Verifica la normalización con payload realista simulado con respx."""
    respx.get(f"{BASE_URL}/t/8888.json").respond(
        200,
        json={
            "id": 8888,
            "title": "Instructivo: Gestión de Facturación Electrónica",
            "category_id": 42,
            "slug": "instructivo-gestion-facturacion",
            "tags": [{"id": 1, "name": "afip", "slug": "afip"}],
            "post_stream": {
                "posts": [
                    {
                        "post_number": 1,
                        "raw": "Texto explicativo detallado con pasos a seguir.",
                        "cooked": "<p>Texto explicativo detallado con pasos a seguir.</p>",
                        "updated_at": "2026-10-14T10:00:00Z"
                    }
                ]
            }
        }
    )

    with httpx.Client(base_url=BASE_URL) as client:
        resp = client.get("/t/8888.json").json()
        primer_post = resp["post_stream"]["posts"][0]
        item = {
            "id": resp["id"],
            "title": resp["title"],
            "category_id": resp["category_id"],
            "slug": resp["slug"],
            "tags": resp["tags"],
            "raw": primer_post["raw"],
            "cooked": primer_post["cooked"],
            "updated_at": primer_post["updated_at"],
        }
        norm = normalizar_articulo(item, base_url=BASE_URL)

        assert norm["id"] == 8888
        assert norm["titulo"] == "Instructivo: Gestión de Facturación Electrónica"
        assert norm["categoria_id"] == 42
        assert "8888" in norm["url"]
        assert len(norm["tags"]) == 1
        assert norm["tags"][0]["slug"] == "afip"
