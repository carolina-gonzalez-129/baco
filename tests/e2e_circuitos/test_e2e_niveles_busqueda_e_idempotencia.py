import pytest
from datetime import datetime, timezone
import numpy as np

from baco.server.db.ingesta import upsert_articulos
from baco.server.services.embeddings import embedding_titulo, embedding_texto


def test_e2e_niveles_busqueda_y_recuperacion(db_conn):
    """
    Inserta un artículo, genera hashes y embeddings, y valida que cada nivel
    lo recupere por separado:
      1. Hash exacto (hash_titulo)
      2. Serie (base_titulo en Postgres)
      3. Trigrama (titulo_normalizado con pg_trgm)
      4. Embedding (distancia coseno <=> con pgvector)
    """
    art_id = 9001
    titulo_base_ejemplo = "Liquidacion de Ganancias Cuarta Categoria 2026"
    texto_ejemplo = "Detalle del instructivo para calcular ganancias cuarta categoría paso a paso."

    # 1. Inserción mediante upsert_articulos
    art = {
        "id": art_id,
        "titulo": titulo_base_ejemplo,
        "categoria_id": 5,
        "url": f"https://bc-dev.finneg.com/t/{art_id}",
        "texto": texto_ejemplo,
        "actualizado": datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc),
        "tags": [{"id": 1, "name": "Impuestos", "slug": "impuestos"}]
    }
    resumen = upsert_articulos(db_conn, [art])
    assert resumen.insertados == 1

    # 2. Generar embeddings reales e insertarlos
    v_tit = embedding_titulo(titulo_base_ejemplo)
    str_v_tit = "[" + ",".join(str(f) for f in v_tit) + "]"
    with db_conn.cursor() as cur:
        cur.execute("UPDATE articulos SET embedding_titulo = %s WHERE id = %s;", (str_v_tit, art_id))
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        db_conn.commit()

    with db_conn.cursor() as cur:
        # Nivel 1: Búsqueda por Hash Exacto
        cur.execute("SELECT hash_titulo FROM articulos WHERE id = %s;", (art_id,))
        hash_en_db = cur.fetchone()[0]
        cur.execute("SELECT id FROM articulos WHERE hash_titulo = %s;", (hash_en_db,))
        assert cur.fetchone()[0] == art_id

        # Nivel 2: Búsqueda por Serie (base_titulo quita el año 2026)
        cur.execute("SELECT base_titulo FROM articulos WHERE id = %s;", (art_id,))
        serie_en_db = cur.fetchone()[0]
        assert "2026" not in serie_en_db
        cur.execute("SELECT id FROM articulos WHERE base_titulo = %s;", (serie_en_db,))
        assert cur.fetchone()[0] == art_id

        # Nivel 3: Búsqueda por Trigrama (con variaciones/errores ortográficos)
        cur.execute(
            """
            SELECT id FROM articulos
            WHERE similarity(titulo_normalizado, 'liquidacion de ganancia cuarta categoria') > 0.4
            ORDER BY similarity(titulo_normalizado, 'liquidacion de ganancia cuarta categoria') DESC
            LIMIT 1;
            """
        )
        assert cur.fetchone()[0] == art_id

        # Nivel 4: Búsqueda por Embedding (Similitud Coseno <=>)
        v_query = embedding_titulo("cómo calcular impuesto a las ganancias 4ta categoria")
        str_query = "[" + ",".join(str(f) for f in v_query) + "]"
        cur.execute(
            """
            SELECT id, 1 - (embedding_titulo <=> %s::vector) AS similitud
            FROM articulos
            ORDER BY embedding_titulo <=> %s::vector ASC
            LIMIT 1;
            """,
            (str_query, str_query)
        )
        row = cur.fetchone()
        assert row[0] == art_id
        assert row[1] > 0.45  # Similitud semántica relevante recuperada en Top-1


def test_e2e_idempotencia_y_edicion_invalida_embeddings(db_conn):
    """
    1. Re-ejecutar la ingesta debe ser idempotente: sin duplicados y sin_cambios.
    2. Editar un artículo con contenido nuevo debe actualizarlo y poner sus embeddings en NULL.
    """
    art_id = 9002
    art = {
        "id": art_id,
        "titulo": "Título Original para Prueba",
        "categoria_id": 2,
        "url": f"https://bc-dev.finneg.com/t/{art_id}",
        "texto": "Texto original del artículo.",
        "actualizado": datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc),
        "tags": []
    }

    # 1. Inserción inicial
    r1 = upsert_articulos(db_conn, [art])
    assert r1.insertados == 1

    # Cargar dummy embedding para comprobar invalidación posterior
    with db_conn.cursor() as cur:
        cur.execute("UPDATE articulos SET embedding_titulo = %s WHERE id = %s;", ("[" + ",".join(["0.01"] * 384) + "]", art_id))
        db_conn.commit()

    # 2. Re-ingesta idéntica -> Idempotencia
    r2 = upsert_articulos(db_conn, [art])
    assert r2.sin_cambios == 1
    assert r2.insertados == 0
    assert r2.actualizados == 0

    # Comprobar que el embedding NO fue tocado ni recalculado de más
    with db_conn.cursor() as cur:
        cur.execute("SELECT embedding_titulo IS NOT NULL FROM articulos WHERE id = %s;", (art_id,))
        assert cur.fetchone()[0] is True

    # 3. Edición del artículo con fecha posterior y nuevo texto
    art_modificado = dict(art)
    art_modificado["titulo"] = "Título Modificado para Prueba"
    art_modificado["actualizado"] = datetime(2026, 10, 14, 11, 0, 0, tzinfo=timezone.utc)

    r3 = upsert_articulos(db_conn, [art_modificado])
    assert r3.actualizados == 1

    # 4. Verificar que al cambiar el título, el embedding_titulo quedó invalidado (puesto en NULL)
    with db_conn.cursor() as cur:
        cur.execute("SELECT embedding_titulo IS NULL, titulo FROM articulos WHERE id = %s;", (art_id,))
        es_null, tit_actual = cur.fetchone()
        assert es_null is True
        assert tit_actual == "Título Modificado para Prueba"
