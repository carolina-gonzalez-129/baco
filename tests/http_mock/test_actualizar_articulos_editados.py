from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from baco.server.discourse.actualizar_articulos_editados import (
    obtener_articulos_existentes,
    actualizar_embeddings_articulo,
    descargar_articulo,
    sincronizar_articulos_editados,
    ErrorAPIDiscourse,
)
from baco.server.db.ingesta import ResumenIngesta


def _mock_conn_cur(cur_mock):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur_mock
    return conn


# ==============================================================================
# 1. Obtención de artículos existentes (id y fecha)
# ==============================================================================

def test_obtener_articulos_existentes_mapeo_correcto():
    cur = MagicMock()
    dt1 = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    dt2 = datetime(2026, 2, 2, 12, 0, tzinfo=timezone.utc)
    cur.fetchall.return_value = [(10, dt1), (20, dt2)]
    conn = _mock_conn_cur(cur)

    res = obtener_articulos_existentes(conn)
    assert res == {10: dt1, 20: dt2}
    cur.execute.assert_called_once_with("SELECT id, actualizado FROM articulos;")


# ==============================================================================
# 2. Descarga de artículo editado
# ==============================================================================

def test_descargar_articulo_detalle():
    http = MagicMock()
    detalle_fake = {
        "title": "Instructivo Modificado",
        "category_id": 8,
        "slug": "instructivo-modificado",
        "tags": [{"id": 5, "name": "instructivo", "slug": "instructivo"}],
        "post_stream": {
            "posts": [
                {
                    "post_number": 1,
                    "raw": "Texto nuevo y actualizado",
                    "cooked": "<p>Texto nuevo y actualizado</p>",
                    "updated_at": "2026-10-14T11:00:00Z",
                }
            ]
        },
    }

    with patch("baco.server.discourse.common.pedir", return_value=detalle_fake):
        art = descargar_articulo(http, tema_id=42)

    assert art is not None
    assert art["id"] == 42
    assert art["titulo"] == "Instructivo Modificado"
    assert art["texto"] == "Texto nuevo y actualizado"
    assert art["actualizado"] == datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc)


# ==============================================================================
# 3. Recálculo selectivo de embeddings para editados
# ==============================================================================

@patch("baco.server.discourse.common.embedding_titulo")
@patch("baco.server.discourse.common.embedding_texto")
def test_actualizar_embeddings_solo_recalcula_el_campo_modificado(mock_emb_txt, mock_emb_tit):
    cur = MagicMock()
    # Solo el texto fue invalidado a NULL
    cur.fetchone.return_value = (False, True)
    conn = _mock_conn_cur(cur)

    mock_emb_txt.return_value = [0.1, 0.2, 0.3]

    actualizar_embeddings_articulo(conn, art_id=42, titulo="Mismo título", texto="Cuerpo editado")

    # Verifica que el modelo de título no fue ejecutado
    mock_emb_tit.assert_not_called()
    # Verifica que el modelo de texto sí fue ejecutado
    mock_emb_txt.assert_called_once_with("Cuerpo editado")
    # Verifica que el UPDATE en Postgres solo modifique embedding_texto
    cur.execute.assert_called_with(
        "UPDATE articulos SET embedding_texto = %s WHERE id = %s;",
        ("[0.1,0.2,0.3]", 42),
    )


# ==============================================================================
# 4. Sincronización de stream de /posts.json
# ==============================================================================

@patch("baco.server.discourse.actualizar_articulos_editados.get_conn")
@patch("baco.server.discourse.actualizar_articulos_editados.pedir")
@patch("baco.server.discourse.actualizar_articulos_editados.descargar_articulo")
@patch("baco.server.discourse.actualizar_articulos_editados.upsert_articulos")
@patch("baco.server.discourse.actualizar_articulos_editados.actualizar_embeddings_articulo")
def test_sincronizar_articulos_editados_detecta_y_actualiza(
    mock_act_emb, mock_upsert, mock_descargar, mock_pedir, mock_get_conn
):
    conn = MagicMock()
    mock_get_conn.return_value = conn

    # En la base, el artículo 50 tiene fecha vieja
    fecha_base = datetime(2025, 5, 1, 10, 0, tzinfo=timezone.utc)
    with patch(
        "baco.server.discourse.actualizar_articulos_editados.obtener_articulos_existentes",
        return_value={50: fecha_base},
    ):
        # /posts.json devuelve un post con fecha más nueva para el tema 50
        fake_posts_json = {
            "latest_posts": [
                {
                    "id": 9001,
                    "topic_id": 50,
                    "post_number": 1,
                    "visible": True,
                    "topic_title": "Artículo 50 Actualizado",
                    "updated_at": "2026-10-14T09:00:00Z",
                },
                # Post 2 del mismo tema (respuesta) -> debe ignorarse
                {
                    "id": 9002,
                    "topic_id": 50,
                    "post_number": 2,
                    "visible": True,
                    "updated_at": "2026-10-14T09:05:00Z",
                },
            ]
        }
        mock_pedir.return_value = fake_posts_json
        mock_descargar.return_value = {
            "id": 50,
            "titulo": "Artículo 50 Actualizado",
            "texto": "Texto nuevo",
            "actualizado": datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc),
        }
        mock_upsert.return_value = ResumenIngesta(actualizados=1)

        rc = sincronizar_articulos_editados(max_paginas=1)

    assert rc == 0
    # Descarga e ingesta solo para el tema 50 (post_number == 1)
    mock_descargar.assert_called_once()
    mock_upsert.assert_called_once()
    # Verifica que se hayan recalculado los embeddings
    mock_act_emb.assert_called_once_with(conn, 50, "Artículo 50 Actualizado", "Texto nuevo")


@patch("baco.server.discourse.actualizar_articulos_editados.get_conn")
@patch("baco.server.discourse.actualizar_articulos_editados.pedir")
@patch("baco.server.discourse.actualizar_articulos_editados.descargar_articulo")
def test_sincronizar_articulos_editados_ignora_si_no_hay_cambios(
    mock_descargar, mock_pedir, mock_get_conn
):
    conn = MagicMock()
    mock_get_conn.return_value = conn

    # En la base, el artículo 50 ya tiene fecha igual o posterior
    fecha_base = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    with patch(
        "baco.server.discourse.actualizar_articulos_editados.obtener_articulos_existentes",
        return_value={50: fecha_base},
    ):
        fake_posts_json = {
            "latest_posts": [
                {
                    "id": 8000,
                    "topic_id": 50,
                    "post_number": 1,
                    "visible": True,
                    "updated_at": "2026-10-14T10:00:00Z",  # Es anterior a fecha_base
                }
            ]
        }
        mock_pedir.return_value = fake_posts_json

        rc = sincronizar_articulos_editados(max_paginas=1)

    assert rc == 0
    # No debe descargar nada porque el artículo no tiene cambios nuevos
    mock_descargar.assert_not_called()


@patch("baco.server.discourse.actualizar_articulos_editados.get_conn")
@patch("baco.server.discourse.actualizar_articulos_editados.pedir")
@patch("baco.server.discourse.actualizar_articulos_editados.descargar_articulo")
def test_sincronizar_articulos_editados_elimina_post_borrado(
    mock_descargar, mock_pedir, mock_get_conn
):
    cur = MagicMock()
    conn = _mock_conn_cur(cur)
    mock_get_conn.return_value = conn

    # En la base existen los temas 70 y 80
    with patch(
        "baco.server.discourse.actualizar_articulos_editados.obtener_articulos_existentes",
        return_value={70: datetime.now(timezone.utc), 80: datetime.now(timezone.utc)},
    ):
        fake_posts_json = {
            "latest_posts": [
                # Tema 70 borrado (deleted_at presente)
                {
                    "id": 9010,
                    "topic_id": 70,
                    "post_number": 1,
                    "visible": True,
                    "deleted_at": "2026-10-14T11:00:00Z",
                    "topic_title": "Artículo Eliminado",
                },
                # Tema 80 despublicado / oculto (visible=False)
                {
                    "id": 9011,
                    "topic_id": 80,
                    "post_number": 1,
                    "visible": False,
                    "topic_title": "Artículo Oculto",
                },
            ]
        }
        mock_pedir.return_value = fake_posts_json

        rc = sincronizar_articulos_editados(max_paginas=1)

    assert rc == 0
    # No debe llamar a descargar
    mock_descargar.assert_not_called()

    # Verifica que se hayan ejecutado los dos DELETE FROM articulos
    cur.execute.assert_any_call("DELETE FROM articulos WHERE id = %s;", (70,))
    cur.execute.assert_any_call("DELETE FROM articulos WHERE id = %s;", (80,))
    assert conn.commit.call_count >= 2
