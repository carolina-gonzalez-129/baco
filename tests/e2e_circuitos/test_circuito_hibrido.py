import json
import httpx
import pytest
import respx
from datetime import datetime, timezone

from baco.server.db.ingesta import normalizar_articulo, upsert_articulos
from baco.server.services.embeddings import embedding_titulo

BASE_URL = "https://bc-dev.finneg.com"


@respx.mock
def test_circuito_hibrido_completo_discourse_a_busqueda_semantica(db_conn):
    """
    Circuito Híbrido End-to-End:
    1. Discourse Mock (respx): Simula respuesta de API de un nuevo artículo técnico.
    2. Ingesta: Normalización de datos crudos.
    3. Base de Datos Docker (Postgres): Upsert con columnas STORED.
    4. Modelo ONNX Real: Cálculo de vector de título (384 dims, normalizado).
    5. Búsqueda Semántica Vectorial en SQL: Consulta usando operador <=> de pgvector.
    """
    tema_id = 7777
    titulo_articulo = "Instructivo: Configuración de Punto de Venta y Factura Electrónica"
    texto_articulo = (
        "# Facturación\n"
        "Pasos para dar de alta un punto de venta en AFIP y vincularlo en Finnegans para emitir comprobantes."
    )

    # 1. Simulación HTTP con respx
    respx.get(f"{BASE_URL}/t/{tema_id}.json").respond(
        200,
        json={
            "id": tema_id,
            "title": titulo_articulo,
            "category_id": 10,
            "slug": "instructivo-configuracion-punto-de-venta",
            "tags": [{"id": 30, "name": "Facturación", "slug": "facturacion"}],
            "post_stream": {
                "posts": [
                    {
                        "post_number": 1,
                        "raw": texto_articulo,
                        "cooked": f"<p>{texto_articulo}</p>",
                        "updated_at": "2026-10-14T12:00:00Z"
                    }
                ]
            }
        }
    )

    # 2. Descarga y Normalización
    with httpx.Client(base_url=BASE_URL) as client:
        datos = client.get(f"/t/{tema_id}.json").json()
        primer_post = datos["post_stream"]["posts"][0]
        item = {
            "id": datos["id"],
            "title": datos["title"],
            "category_id": datos["category_id"],
            "slug": datos["slug"],
            "tags": datos["tags"],
            "raw": primer_post["raw"],
            "cooked": primer_post["cooked"],
            "updated_at": primer_post["updated_at"],
        }
        articulo_norm = normalizar_articulo(item, base_url=BASE_URL)

    # 3. Inserción en PostgreSQL real (Docker)
    resumen = upsert_articulos(db_conn, [articulo_norm])
    assert resumen.insertados == 1

    # 4. Cálculo de Embeddings con ONNX Real
    vector_titulo = embedding_titulo(articulo_norm["titulo"])
    assert vector_titulo is not None and len(vector_titulo) == 384
    str_vector = "[" + ",".join(str(x) for x in vector_titulo) + "]"

    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE articulos SET embedding_titulo = %s WHERE id = %s;",
            (str_vector, tema_id)
        )
        db_conn.commit()

    # 5. Búsqueda Semántica Vectorial en PostgreSQL
    # Simulamos que un usuario busca: "Configuración de Punto de Venta y Factura Electrónica"
    query_usuario = "Configuración de Punto de Venta y Factura Electrónica"
    vector_query = embedding_titulo(query_usuario)
    str_query = "[" + ",".join(str(x) for x in vector_query) + "]"

    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, titulo, (1 - (embedding_titulo <=> %s::vector)) AS similitud_coseno
            FROM articulos
            WHERE embedding_titulo IS NOT NULL
            ORDER BY embedding_titulo <=> %s::vector ASC
            LIMIT 1;
            """,
            (str_query, str_query)
        )
        row = cur.fetchone()
        assert row is not None
        recuperado_id, recuperado_tit, similitud = row
        assert recuperado_id == tema_id
        # La similitud coseno con el núcleo del título debe ser superior a 0.85
        assert similitud > 0.85
