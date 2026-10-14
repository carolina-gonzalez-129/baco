import pytest
from datetime import datetime, timezone
from baco.server.db.ingesta import upsert_articulos


def test_columnas_stored_se_calculan_automaticamente(db_conn):
    """Verifica que las columnas STORED (titulo_normalizado, hash_titulo, texto_sin_headers) funcionen en PostgreSQL real."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto)
            VALUES (%s, %s, %s, %s)
            RETURNING titulo_normalizado, hash_titulo, texto_sin_headers, hash_texto;
            """,
            (
                1001,
                "¿Cómo CONFIGURAR facturación electrónica?",
                "https://bc-dev.finneg.com/t/1001",
                "# Título Principal\nTexto explicativo paso a paso."
            )
        )
        row = cur.fetchone()
        assert row is not None
        tit_norm, hash_tit, txt_sin_headers, hash_txt = row

        # normalizar_texto quita signos y acentos
        assert "como configurar facturacion electronica" in tit_norm
        assert hash_tit is not None and len(hash_tit) == 32  # MD5
        # limpiar_headers quita el # Título Principal
        assert "# Título Principal" not in txt_sin_headers
        assert "Texto explicativo paso a paso." in txt_sin_headers
        assert hash_txt is not None


def test_vector_extension_insercion_y_lectura(db_conn):
    """Verifica que la extensión pgvector acepte e indexe embeddings vectoriales."""
    dummy_vec = "[" + ",".join(["0.05"] * 384) + "]"
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto, embedding_titulo)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, embedding_titulo <-> %s AS distancia;
            """,
            (
                1002,
                "Artículo con Vector",
                "https://bc-dev.finneg.com/t/1002",
                "Contenido de prueba.",
                dummy_vec,
                dummy_vec
            )
        )
        row = cur.fetchone()
        assert row is not None
        art_id, distancia = row
        assert art_id == 1002
        # La distancia euclidiana o coseno contra sí mismo debe ser 0.0
        assert pytest.approx(distancia, abs=1e-5) == 0.0


def test_on_delete_cascade_articulo_tags(db_conn):
    """Verifica que el borrado físico de un artículo elimine automáticamente sus tags en articulo_tags."""
    with db_conn.cursor() as cur:
        # Insertar artículo
        cur.execute(
            "INSERT INTO articulos (id, titulo, url, texto) VALUES (1003, 'Articulo para Borrar', 'url', 'texto');"
        )
        # Insertar tag
        cur.execute(
            "INSERT INTO tags (id, name, slug) VALUES (55, 'Finanzas', 'finanzas') ON CONFLICT (id) DO NOTHING;"
        )
        # Asociar
        cur.execute(
            "INSERT INTO articulo_tags (articulo_id, tag_id) VALUES (1003, 55);"
        )

        # Confirmar asociación
        cur.execute("SELECT COUNT(*) FROM articulo_tags WHERE articulo_id = 1003;")
        assert cur.fetchone()[0] == 1

        # Borrado físico en articulos
        cur.execute("DELETE FROM articulos WHERE id = 1003;")

        # Comprobar que ON DELETE CASCADE limpió articulo_tags
        cur.execute("SELECT COUNT(*) FROM articulo_tags WHERE articulo_id = 1003;")
        assert cur.fetchone()[0] == 0


def test_upsert_articulos_real_en_postgres(db_conn):
    """Prueba la función real upsert_articulos contra PostgreSQL Docker."""
    art = {
        "id": 1004,
        "titulo": "Primer Título",
        "categoria_id": None,
        "url": "https://bc-dev.finneg.com/t/1004",
        "texto": "Texto inicial",
        "actualizado": datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc),
        "tags": [{"id": 99, "name": "Ventas", "slug": "ventas"}]
    }

    # 1. Inserción inicial
    resumen1 = upsert_articulos(db_conn, [art])
    assert resumen1.insertados == 1

    # 2. Re-ejecutar sin cambios -> sin_cambios
    resumen2 = upsert_articulos(db_conn, [art])
    assert resumen2.sin_cambios == 1

    # 3. Modificación con fecha posterior -> actualizados
    art_editado = dict(art)
    art_editado["titulo"] = "Título Actualizado"
    art_editado["actualizado"] = datetime(2026, 10, 14, 11, 0, 0, tzinfo=timezone.utc)
    resumen3 = upsert_articulos(db_conn, [art_editado])
    assert resumen3.actualizados == 1
