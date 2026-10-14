import math
import os

import httpx
import pytest

from baco.server.discourse import actualizar_nuevos_articulos as sincronizacion
from baco.server.services.embeddings import DIM_TEXTO, DIM_TITULO, embedding_texto, embedding_titulo


@pytest.mark.integration
def test_http_discourse_retry_con_transport_realista(monkeypatch):
    respuestas = iter(
        [
            httpx.Response(
                429,
                headers={"Retry-After": "0"},
                request=httpx.Request("GET", "https://discourse.test/latest.json"),
            ),
            httpx.Response(
                200,
                json={"topic_list": {"topics": [{"id": 1}]}},
                request=httpx.Request("GET", "https://discourse.test/latest.json"),
            ),
        ]
    )

    def handler(request):
        return next(respuestas)

    cliente = httpx.Client(
        base_url="https://discourse.test",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(sincronizacion.time, "sleep", lambda _seconds: None)
    try:
        resultado = sincronizacion.pedir(cliente, "/latest.json")
    finally:
        cliente.close()

    assert resultado["topic_list"]["topics"] == [{"id": 1}]


@pytest.mark.integration
def test_postgresql_normalizar_texto_si_se_configura():
    dsn = os.getenv("BACO_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Definir BACO_TEST_DATABASE_URL para ejecutar la integración PostgreSQL")

    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT normalizar_texto(%s);", ("  Configuración  Ágil  ",))
                resultado = cur.fetchone()[0]
    except Exception as exc:
        pytest.skip(f"PostgreSQL no disponible o esquema BACO incompleto: {exc}")

    assert resultado == "configuracion agil"


@pytest.mark.integration
def test_modelos_onnx_generan_vectores_normalizados_si_se_habilita():
    if os.getenv("RUN_ONNX_INTEGRATION") != "1":
        pytest.skip("Definir RUN_ONNX_INTEGRATION=1 para cargar los modelos ONNX reales")

    vector_titulo = embedding_titulo("Configurar facturación electrónica")
    vector_texto = embedding_texto("Ingresar al módulo de ventas y configurar los parámetros.")

    assert vector_titulo is not None
    assert vector_texto is not None
    assert len(vector_titulo) == DIM_TITULO
    assert len(vector_texto) == DIM_TEXTO
    assert math.isclose(sum(valor * valor for valor in vector_titulo), 1.0, rel_tol=1e-4)
    assert math.isclose(sum(valor * valor for valor in vector_texto), 1.0, rel_tol=1e-4)
