import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from baco.server.db import generar_embeddings as generar
from baco.server.db import reconstruir_db

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _conn(cur):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = None
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


def test_leer_articulos_json_filtra_items_sin_id(tmp_path):
    archivo = tmp_path / "articulos.json"
    archivo.write_text(
        '[{"id": 1, "title": "Uno"}, {"title": "Sin id"}, {"id": 2, "title": "Dos"}]',
        encoding="utf-8",
    )

    resultado = reconstruir_db.leer_articulos_json(archivo)

    assert [art["id"] for art in resultado] == [1, 2]


def test_cargar_y_validar_json_aborta_si_el_archivo_no_existe(tmp_path):
    # La validación del JSON ocurre antes de tocar la base: si falta, aborta con exit 1.
    with pytest.raises(SystemExit) as exc:
        reconstruir_db.cargar_y_validar_json(tmp_path / "no-existe.json")
    assert exc.value.code == 1


def test_cargar_y_validar_json_aborta_si_no_hay_articulos_validos(tmp_path):
    archivo = tmp_path / "articulos.json"
    archivo.write_text('[{"title": "Sin id"}]', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        reconstruir_db.cargar_y_validar_json(archivo)
    assert exc.value.code == 1


def test_sincronizar_articulos_ingesta_sin_commit():
    # El commit lo hace main junto con el DDL; sincronizar_articulos solo hace el upsert.
    articulos = [{"id": 1, "title": "Uno"}]
    conn = _conn(MagicMock())

    with patch.object(reconstruir_db, "upsert_articulos", return_value=MagicMock()) as upsert:
        total = reconstruir_db.sincronizar_articulos(conn, articulos)

    assert total == 1
    upsert.assert_called_once_with(conn, articulos)
    conn.commit.assert_not_called()



def test_validar_contra_meta_rechaza_modelo_con_dimension_incorrecta():
    cur = MagicMock()
    cur.fetchone.return_value = (generar.MODEL_TEXTO_NAME, generar.DIM_TEXTO)
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = 384

    with pytest.raises(ValueError, match="no coincide con la dimensión esperada"):
        generar.validar_contra_meta(
            _conn(cur), "texto", model, generar.MODEL_TEXTO_NAME, generar.DIM_TEXTO
        )


def test_obtener_articulos_pendientes_ejecuta_consulta():
    cur = MagicMock()
    cur.fetchall.return_value = [(1, "Título", "Texto", "ht", "hx", None, None)]

    resultado = generar.obtener_articulos_pendientes(_conn(cur))

    assert resultado[0][0] == 1
    assert "embedding_titulo IS NULL" in cur.execute.call_args.args[0]


def test_generar_embeddings_actualiza_titulo_y_texto():
    cur = MagicMock()
    pendientes = [(1, "Título", "Texto", "ht", "hx", None, None)]
    conn = _conn(cur)
    model_titulo = MagicMock()
    model_texto = MagicMock(tokenizer=MagicMock())

    with patch.object(generar, "obtener_articulos_pendientes", return_value=pendientes), \
         patch.object(generar, "get_model_titulo", return_value=model_titulo), \
         patch.object(generar, "get_model_texto", return_value=model_texto), \
         patch.object(generar, "validar_contra_meta"), \
         patch.object(generar, "medir_articulos_truncados"), \
         patch.object(generar, "embedding_titulo", return_value=[[0.1]]), \
         patch.object(generar, "embedding_texto", return_value=[[0.2]]), \
         patch.object(generar, "tqdm", return_value=MagicMock()):
        with patch.object(generar, "get_conn", return_value=conn):
            generar.generar_embeddings()

    assert any(
        "embedding_titulo = %s" in call.args[0]
        and "embedding_texto = %s" in call.args[0]
        for call in cur.execute.call_args_list
    )
    conn.commit.assert_called_once()


def test_reconstruir_db_recalcular_embeddings_sin_articulos():
    cur = MagicMock()
    cur.fetchall.return_value = []
    conn = _conn(cur)
    with patch.object(reconstruir_db, 'get_model_titulo'),          patch.object(reconstruir_db, 'get_model_texto'):
        reconstruir_db.recalcular_embeddings(conn)
    cur.executemany.assert_not_called()


def test_reconstruir_db_recalcular_embeddings_con_articulos():
    cur = MagicMock()
    cur.fetchall.return_value = [(1, 'Titulo', 'Texto')]
    conn = _conn(cur)
    with patch.object(reconstruir_db, 'get_model_titulo', return_value=MagicMock()),          patch.object(reconstruir_db, 'get_model_texto', return_value=MagicMock()),          patch.object(reconstruir_db, 'embedding_titulo', return_value=[[0.1]]),          patch.object(reconstruir_db, 'embedding_texto', return_value=[[0.2]]):
        reconstruir_db.recalcular_embeddings(conn, batch_size=10, solo_pendientes=False)
    cur.executemany.assert_called_once()
    assert cur.executemany.call_args.args[1] == [('[0.1]', '[0.2]', 1)]
    conn.commit.assert_called_once()


def test_schema_completo_sql_valida_embeddings_meta():
    from pathlib import Path
    from baco.server.services.embeddings import MODEL_TITULO_NAME, DIM_TITULO, MODEL_TEXTO_NAME, DIM_TEXTO
    sql_path = Path(__file__).resolve().parents[2] / 'baco' / 'server' / 'db' / 'schema_completo.sql'
    assert sql_path.exists()
    sql_content = sql_path.read_text(encoding='utf-8')
    assert 'CREATE TABLE IF NOT EXISTS embeddings_meta' in sql_content
    assert MODEL_TITULO_NAME in sql_content
    assert str(DIM_TITULO) in sql_content
    assert MODEL_TEXTO_NAME in sql_content
    assert str(DIM_TEXTO) in sql_content


def test_equivalencia_schema_completo_con_duplicados_schema_y_sin_password_hardcodeada():
    """schema_completo.sql debe incluir íntegramente duplicados_schema.sql y no tener contraseñas fijas."""
    ruta_completo = PROJECT_ROOT / "baco" / "server" / "db" / "schema_completo.sql"
    ruta_duplicados = PROJECT_ROOT / "baco" / "server" / "db" / "duplicados_schema.sql"

    sql_completo = ruta_completo.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    sql_duplicados = ruta_duplicados.read_text(encoding="utf-8").replace("\r\n", "\n").strip()

    assert sql_duplicados in sql_completo, (
        "El bloque del schema duplicados en schema_completo.sql no coincide exactamente con duplicados_schema.sql"
    )
    assert "current_setting('baco.ro_password'" in sql_completo
    assert not re.search(
        r"CREATE\s+ROLE\s+baco_readonly\s+WITH\s+LOGIN\s+PASSWORD\s+'[^']+'",
        sql_completo,
        re.IGNORECASE,
    ), "No debe haber contraseña literal hardcodeada para baco_readonly en schema_completo.sql"
