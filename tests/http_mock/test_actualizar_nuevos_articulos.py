from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from baco.server.discourse.actualizar_nuevos_articulos import (
    obtener_ids_existentes,
    descargar_articulo,
    actualizar_embeddings_articulo,
    sincronizar_articulos,
    listar_temas,
)
from baco.server.db.ingesta import ResumenIngesta


def _mock_conn_cur(cur_mock):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur_mock
    return conn


# ==============================================================================
# 1. Obtención de IDs existentes
# ==============================================================================

def test_obtener_ids_existentes():
    cur = MagicMock()
    cur.fetchall.return_value = [(101,), (102,), (103,)]
    conn = _mock_conn_cur(cur)

    ids = obtener_ids_existentes(conn)
    assert ids == {101, 102, 103}
    cur.execute.assert_called_once_with("SELECT id FROM articulos;")


# ==============================================================================
# 2. Descarga de artículo
# ==============================================================================

def test_descargar_articulo_normaliza_correctamente():
    http = MagicMock()
    tema = {"id": 500, "title": "Listado de Stock", "slug": "listado-de-stock", "category_id": 4}

    detalle_fake = {
        "title": "Listado de Stock",
        "category_id": 4,
        "slug": "listado-de-stock",
        "tags": [{"id": 1, "name": "instructivo", "slug": "instructivo"}],
        "post_stream": {
            "posts": [
                {
                    "post_number": 1,
                    "raw": "Paso 1: Ir a inventario",
                    "cooked": "<p>Paso 1: Ir a inventario</p>",
                    "updated_at": "2026-10-14T10:00:00Z",
                }
            ]
        },
    }

    with patch("baco.server.discourse.actualizar_nuevos_articulos.pedir", return_value=detalle_fake):
        art = descargar_articulo(http, tema)

    assert art is not None
    assert art["id"] == 500
    assert art["titulo"] == "Listado de Stock"
    assert art["texto"] == "Paso 1: Ir a inventario"
    assert art["actualizado"] == datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)


def test_descargar_articulo_sin_posts_retorna_none():
    http = MagicMock()
    tema = {"id": 999}
    with patch("baco.server.discourse.actualizar_nuevos_articulos.pedir", return_value={"post_stream": {"posts": []}}):
        art = descargar_articulo(http, tema)
    assert art is None


# ==============================================================================
# 3. Recálculo selectivo de Embeddings (Solo el campo necesario)
# ==============================================================================

@patch("baco.server.discourse.actualizar_nuevos_articulos.embedding_titulo")
@patch("baco.server.discourse.actualizar_nuevos_articulos.embedding_texto")
def test_actualizar_embeddings_solo_titulo_si_texto_no_es_null(mock_emb_txt, mock_emb_tit):
    cur = MagicMock()
    # embedding_titulo es NULL (True), embedding_texto NO es NULL (False)
    cur.fetchone.return_value = (True, False)
    conn = _mock_conn_cur(cur)

    mock_emb_tit.return_value = [0.1, 0.2, 0.3]

    res = actualizar_embeddings_articulo(conn, art_id=1, titulo="Nuevo Título", texto="Texto viejo")

    assert res is True
    # Solo se invoca el modelo de título
    mock_emb_tit.assert_called_once_with("Nuevo Título")
    mock_emb_txt.assert_not_called()

    # Verifica que el UPDATE solo toque embedding_titulo
    cur.execute.assert_called_with(
        "UPDATE articulos SET embedding_titulo = %s WHERE id = %s;",
        ("[0.1,0.2,0.3]", 1),
    )
    conn.commit.assert_called_once()


@patch("baco.server.discourse.actualizar_nuevos_articulos.embedding_titulo")
@patch("baco.server.discourse.actualizar_nuevos_articulos.embedding_texto")
def test_actualizar_embeddings_solo_texto_si_titulo_no_es_null(mock_emb_txt, mock_emb_tit):
    cur = MagicMock()
    # embedding_titulo NO es NULL (False), embedding_texto es NULL (True)
    cur.fetchone.return_value = (False, True)
    conn = _mock_conn_cur(cur)

    mock_emb_txt.return_value = [0.8, 0.9]

    res = actualizar_embeddings_articulo(conn, art_id=2, titulo="Título sin cambios", texto="Nuevo texto explicativo")

    assert res is True
    mock_emb_tit.assert_not_called()
    mock_emb_txt.assert_called_once_with("Nuevo texto explicativo")

    cur.execute.assert_called_with(
        "UPDATE articulos SET embedding_texto = %s WHERE id = %s;",
        ("[0.8,0.9]", 2),
    )
    conn.commit.assert_called_once()


@patch("baco.server.discourse.actualizar_nuevos_articulos.embedding_titulo")
@patch("baco.server.discourse.actualizar_nuevos_articulos.embedding_texto")
def test_actualizar_embeddings_omite_si_ninguno_es_null(mock_emb_txt, mock_emb_tit):
    cur = MagicMock()
    # Ninguno es NULL
    cur.fetchone.return_value = (False, False)
    conn = _mock_conn_cur(cur)

    res = actualizar_embeddings_articulo(conn, art_id=3, titulo="Título", texto="Texto")

    assert res is False
    mock_emb_tit.assert_not_called()
    mock_emb_txt.assert_not_called()
    conn.commit.assert_not_called()


# ==============================================================================
# 4. Flujo de sincronización de nuevos artículos y corte por consecutivos
# ==============================================================================

@patch("baco.server.discourse.actualizar_nuevos_articulos.get_conn")
@patch("baco.server.discourse.actualizar_nuevos_articulos.listar_temas")
@patch("baco.server.discourse.actualizar_nuevos_articulos.descargar_articulo")
@patch("baco.server.discourse.actualizar_nuevos_articulos.upsert_articulos")
@patch("baco.server.discourse.actualizar_nuevos_articulos.actualizar_embeddings_articulo")
def test_sincronizar_articulos_corta_en_15_consecutivos(
    mock_act_emb, mock_upsert, mock_descargar, mock_listar, mock_get_conn
):
    conn = MagicMock()
    mock_get_conn.return_value = conn

    # Base ya tiene los temas 1 a 20
    ids_en_base = set(range(1, 25))
    with patch("baco.server.discourse.actualizar_nuevos_articulos.obtener_ids_existentes", return_value=ids_en_base):
        # El generador emite 20 temas que ya están en la base
        mock_listar.return_value = iter([{"id": i, "visible": True} for i in range(1, 21)])

        rc = sincronizar_articulos(completo=False)

    assert rc == 0
    # No descargó ningún tema porque todos ya existían y cortó al llegar a 15 consecutivos
    mock_descargar.assert_not_called()
    mock_upsert.assert_not_called()


@patch("baco.server.discourse.actualizar_nuevos_articulos.get_conn")
@patch("baco.server.discourse.actualizar_nuevos_articulos.listar_temas")
@patch("baco.server.discourse.actualizar_nuevos_articulos.descargar_articulo")
@patch("baco.server.discourse.actualizar_nuevos_articulos.upsert_articulos")
@patch("baco.server.discourse.actualizar_nuevos_articulos.actualizar_embeddings_articulo")
def test_sincronizar_articulos_inserta_nuevo_y_recalcula_embeddings(
    mock_act_emb, mock_upsert, mock_descargar, mock_listar, mock_get_conn
):
    conn = MagicMock()
    mock_get_conn.return_value = conn

    # Base vacía
    with patch("baco.server.discourse.actualizar_nuevos_articulos.obtener_ids_existentes", return_value=set()):
        mock_listar.return_value = iter([{"id": 999, "visible": True}])
        mock_descargar.return_value = {
            "id": 999,
            "titulo": "Nuevo Artículo",
            "texto": "Contenido",
            "actualizado": datetime.now(timezone.utc),
        }
        resumen_parcial = ResumenIngesta(insertados=1)
        mock_upsert.return_value = resumen_parcial

        rc = sincronizar_articulos(completo=False)

    assert rc == 0
    mock_descargar.assert_called_once()
    mock_upsert.assert_called_once()
    mock_act_emb.assert_called_once_with(conn, 999, "Nuevo Artículo", "Contenido")


@patch("baco.server.discourse.actualizar_nuevos_articulos.get_conn")
@patch("baco.server.discourse.actualizar_nuevos_articulos.listar_temas")
@patch("baco.server.discourse.actualizar_nuevos_articulos.descargar_articulo")
@patch("baco.server.discourse.actualizar_nuevos_articulos.upsert_articulos")
def test_sincronizar_articulos_completo_con_purgar_elimina_huerfanos(
    mock_upsert, mock_descargar, mock_listar, mock_get_conn
):
    cur = MagicMock()
    conn = _mock_conn_cur(cur)
    mock_get_conn.return_value = conn

    # En la base existen los temas 1, 2 y 3
    ids_en_base = {1, 2, 3}
    with patch("baco.server.discourse.actualizar_nuevos_articulos.obtener_ids_existentes", return_value=ids_en_base):
        # En Discourse solo existen los temas 1 y 2 (el 3 fue borrado)
        mock_listar.return_value = iter([{"id": 1, "visible": True}, {"id": 2, "visible": True}])
        mock_descargar.return_value = None  # Sin cambios

        rc = sincronizar_articulos(completo=True, purgar=True)

    assert rc == 0
    # Verifica que se haya ejecutado el DELETE para el tema 3
    cur.execute.assert_called_with("DELETE FROM articulos WHERE id = ANY(%s);", ([3],))
    conn.commit.assert_called()


@patch("baco.server.discourse.actualizar_nuevos_articulos.get_conn")
@patch("baco.server.discourse.actualizar_nuevos_articulos.listar_temas")
@patch("baco.server.discourse.actualizar_nuevos_articulos.descargar_articulo")
@patch("baco.server.discourse.actualizar_nuevos_articulos.upsert_articulos")
def test_sincronizar_articulos_completo_sin_purgar_no_elimina(
    mock_upsert, mock_descargar, mock_listar, mock_get_conn
):
    cur = MagicMock()
    conn = _mock_conn_cur(cur)
    mock_get_conn.return_value = conn

    # En la base existen los temas 1 y 2
    ids_en_base = {1, 2}
    with patch("baco.server.discourse.actualizar_nuevos_articulos.obtener_ids_existentes", return_value=ids_en_base):
        # En Discourse solo existe el tema 1 (el 2 es huérfano)
        mock_listar.return_value = iter([{"id": 1, "visible": True}])
        mock_descargar.return_value = None

        # purgar=False (por defecto sin flag)
        rc = sincronizar_articulos(completo=True, purgar=False)

    assert rc == 0
    # No debe ejecutar ningún DELETE
    for call_args in cur.execute.call_args_list:
        assert "DELETE" not in str(call_args)
