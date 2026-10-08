from datetime import datetime, timezone
from unittest.mock import MagicMock

from baco.server.db.ingesta import (
    SQL_UPSERT_ARTICULO,
    normalizar_articulo,
    parsear_fecha,
    tag_id_sintetico,
    upsert_articulos,
)


# ==============================================================================
# 1. Normalización de formatos
# ==============================================================================

def test_normalizar_formato_json_propio():
    item = {
        "id": 10,
        "titulo": "  Configurar ARBA  ",
        "categoria_id": 7,
        "tags": [{"id": 1, "name": "instructivo", "slug": "instructivo"}],
        "url": "https://bc.finneg.com/t/configurar-arba/10",
        "texto": "Pasos...",
        "actualizado": "2026-05-01T10:00:00.000Z",
    }
    art = normalizar_articulo(item)
    assert art["id"] == 10
    assert art["titulo"] == "Configurar ARBA"
    assert art["categoria_id"] == 7
    assert art["url"] == "https://bc.finneg.com/t/configurar-arba/10"
    assert art["actualizado"] == datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    assert art["tags"] == [{"id": 1, "name": "instructivo", "slug": "instructivo"}]


def test_normalizar_formato_discourse():
    item = {
        "id": 20,
        "title": "Emitir factura",
        "category_id": 3,
        "slug": "emitir-factura",
        "cooked": "<h1>Consulta</h1><p>Hola <b>mundo</b></p>",
        "updated_at": "2026-05-02T00:00:00Z",
        "tags": ["Soluciones"],
    }
    art = normalizar_articulo(item, base_url="https://kb.test")
    assert art["titulo"] == "Emitir factura"
    assert art["categoria_id"] == 3
    assert art["url"] == "https://kb.test/t/emitir-factura/20"
    assert "Hola" in art["texto"] and "<p>" not in art["texto"]
    assert art["tags"] == [{"id": None, "name": "Soluciones", "slug": "soluciones"}]


def test_normalizar_sin_clave_tags_no_toca_relaciones():
    art = normalizar_articulo({"id": 1, "titulo": "X", "texto": "Y"}, base_url="https://kb.test")
    assert art["tags"] is None
    assert art["url"] == "https://kb.test/t/1"


def test_normalizar_sin_id_devuelve_none():
    assert normalizar_articulo({"titulo": "X"}) is None


def test_normalizar_titulo_vacio_usa_placeholder():
    assert normalizar_articulo({"id": 1, "titulo": "   "}, base_url="https://kb.test")["titulo"] == "Sin título"


def test_parsear_fecha_naive_se_asume_utc():
    assert parsear_fecha("2026-01-01T00:00:00").tzinfo == timezone.utc
    assert parsear_fecha(None) is None
    assert parsear_fecha("no-es-fecha") is None


def test_tag_id_sintetico_determinista_negativo_e_int32():
    a = tag_id_sintetico("facturacion")
    assert a == tag_id_sintetico("facturacion")
    assert a < 0
    assert a > -(2 ** 31)
    assert a != tag_id_sintetico("compras")


# ==============================================================================
# 2. Upsert
# ==============================================================================

def test_sql_upsert_actualiza_categoria_e_invalida_embeddings():
    sql = SQL_UPSERT_ARTICULO
    assert "categoria_id = EXCLUDED.categoria_id" in sql
    assert "embedding_titulo = CASE WHEN articulos.titulo IS DISTINCT FROM EXCLUDED.titulo" in sql
    assert "embedding_texto  = CASE WHEN articulos.texto IS DISTINCT FROM EXCLUDED.texto" in sql
    assert "EXCLUDED.actualizado >= articulos.actualizado" in sql


def _conn_con_cursor(cur):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


def test_upsert_no_pisa_con_version_mas_vieja():
    cur = MagicMock()
    cur.fetchall.return_value = [(1, datetime(2026, 6, 1, tzinfo=timezone.utc))]
    art = normalizar_articulo(
        {"id": 1, "titulo": "Viejo", "texto": "t", "actualizado": "2026-01-01T00:00:00Z", "url": "u"}
    )
    resumen = upsert_articulos(_conn_con_cursor(cur), [art])

    assert resumen.omitidos_por_antiguedad == 1
    assert resumen.ids_omitidos == [1]
    ejecutadas = [c.args[0] for c in cur.execute.call_args_list]
    assert SQL_UPSERT_ARTICULO not in ejecutadas


def test_upsert_cuenta_insertados_actualizados_y_sin_cambios():
    cur = MagicMock()
    cur.fetchall.return_value = []  # ninguno existe en la base todavía
    cur.fetchone.side_effect = [(True,), (False,), None]
    arts = [
        normalizar_articulo({"id": i, "titulo": f"T{i}", "texto": "x", "url": "u",
                             "actualizado": "2026-01-01T00:00:00Z"})
        for i in (1, 2, 3)
    ]
    resumen = upsert_articulos(_conn_con_cursor(cur), arts)
    assert (resumen.insertados, resumen.actualizados, resumen.sin_cambios) == (1, 1, 1)


def test_upsert_sincroniza_relaciones_de_tags():
    cur = MagicMock()
    cur.fetchall.return_value = []
    cur.fetchone.return_value = (True,)
    art = normalizar_articulo({"id": 5, "titulo": "T", "texto": "x", "url": "u",
                               "tags": [{"id": 9, "name": "a", "slug": "a"}]})
    upsert_articulos(_conn_con_cursor(cur), [art])

    deletes = [c for c in cur.execute.call_args_list if c.args[0].startswith("DELETE FROM articulo_tags")]
    assert len(deletes) == 1
    assert deletes[0].args[1] == (5, [9])


def test_upsert_lista_vacia():
    conn = MagicMock()
    resumen = upsert_articulos(conn, [])
    assert resumen.insertados == 0
    conn.cursor.assert_not_called()
