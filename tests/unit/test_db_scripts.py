from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from baco.server.db import cargar_articulos_postgres as cargar
from baco.server.db import generar_embeddings as generar
from baco.server.db import migrar_embeddings_texto as migrar_texto
from baco.server.db import migrar_y_sincronizar_todo as maestro
from baco.server.db import recalcular_embeddings_onnx as recalcular
from baco.server.db import rellenar_normalizados as normalizados


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

    resultado = cargar.leer_articulos_json(archivo)

    assert [art["id"] for art in resultado] == [1, 2]


def test_asegurar_base_de_datos_crea_base_si_no_existe():
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn = _conn(cur)

    with patch.object(cargar, "get_conn", return_value=conn):
        cargar.asegurar_base_de_datos()

    assert 'CREATE DATABASE "baco_db";' in cur.execute.call_args.args[0]


def test_asegurar_base_de_datos_no_crea_base_existente():
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    conn = _conn(cur)

    with patch.object(cargar, "get_conn", return_value=conn):
        cargar.asegurar_base_de_datos()

    assert cur.execute.call_count == 1


def test_importar_articulos_hace_rollback_en_dry_run(tmp_path):
    cargar_file = tmp_path / "articulos.json"
    cargar_file.write_text('[{"id": 1, "title": "Uno"}]', encoding="utf-8")
    conn = _conn(MagicMock())
    resumen = MagicMock()

    with patch.object(cargar, "RUTA_JSON", cargar_file), \
         patch.object(cargar, "get_conn", return_value=conn), \
         patch.object(cargar, "upsert_articulos", return_value=resumen):
        cargar.importar_articulos(dry_run=True)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_importar_articulos_omite_archivo_inexistente(tmp_path):
    with patch.object(cargar, "RUTA_JSON", tmp_path / "no-existe.json"):
        assert cargar.importar_articulos() is None


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


def test_verificar_columna_y_meta_inserta_metadata_faltante():
    cur = MagicMock()
    cur.fetchone.side_effect = [("embedding_texto", "USER-DEFINED", "vector"), (768,), None]
    conn = _conn(cur)

    migrar_texto.verificar_columna_y_meta(conn)

    assert any("INSERT INTO embeddings_meta" in call.args[0] for call in cur.execute.call_args_list)
    conn.commit.assert_called_once()


def test_verificar_columna_y_meta_rechaza_tipo_incorrecto():
    cur = MagicMock()
    cur.fetchone.return_value = ("embedding_texto", "USER-DEFINED", "float8")

    with pytest.raises(RuntimeError, match="se esperaba 'vector'"):
        migrar_texto.verificar_columna_y_meta(_conn(cur))


def test_obtener_articulos_pendientes_force_trunca_y_aplica_limite():
    cur = MagicMock()
    cur.fetchall.return_value = [(1, "Texto")]
    conn = _conn(cur)

    resultado = migrar_texto.obtener_articulos_pendientes(conn, force=True, limit=1)

    assert resultado == [(1, "Texto")]
    assert any("TRUNCATE TABLE" in call.args[0] for call in cur.execute.call_args_list)
    assert "LIMIT 1" in cur.execute.call_args_list[-1].args[0]
    conn.commit.assert_called_once()


def test_ejecutar_migracion_procesa_vectores_y_textos_vacios():
    cur = MagicMock()
    conn = _conn(cur)
    pendientes = [(1, "Texto"), (2, None)]

    with patch.object(migrar_texto, "get_conn", return_value=conn), \
         patch.object(migrar_texto, "verificar_columna_y_meta"), \
         patch.object(migrar_texto, "preparar_tabla_control_idempotencia"), \
         patch.object(migrar_texto, "obtener_articulos_pendientes", return_value=pendientes), \
         patch.object(migrar_texto, "get_model_texto", return_value=MagicMock()), \
         patch.object(migrar_texto, "embedding_texto", return_value=[[0.3], None]), \
         patch.object(migrar_texto, "tqdm", return_value=MagicMock()):
        resultado = migrar_texto.ejecutar_migracion(batch_size=2)

    assert resultado["total_procesados"] == 2
    assert any("embedding_texto = %s" in call.args[0] for call in cur.execute.call_args_list)
    assert any("embedding_texto = NULL" in call.args[0] for call in cur.execute.call_args_list)


def test_recalcular_todos_los_embeddings_sin_articulos_termina():
    cur = MagicMock()
    cur.fetchall.return_value = []
    conn = _conn(cur)

    with patch.object(recalcular, "get_conn", return_value=conn), \
         patch.object(recalcular, "get_model_titulo"), \
         patch.object(recalcular, "get_model_texto"):
        assert recalcular.recalcular_todos_los_embeddings() is None


def test_recalcular_todos_los_embeddings_actualiza_lote():
    cur = MagicMock()
    cur.fetchall.return_value = [(1, "Título", "Texto")]
    conn = _conn(cur)

    with patch.object(recalcular, "get_conn", return_value=conn), \
         patch.object(recalcular, "get_model_titulo", return_value=MagicMock()), \
         patch.object(recalcular, "get_model_texto", return_value=MagicMock()), \
         patch.object(recalcular, "embedding_titulo", return_value=[[0.1]]), \
         patch.object(recalcular, "embedding_texto", return_value=[[0.2]]), \
         patch.object(recalcular, "tqdm", return_value=MagicMock()):
        recalcular.recalcular_todos_los_embeddings()

    cur.executemany.assert_called_once()
    assert cur.executemany.call_args.args[1] == [("[0.1]", "[0.2]", 1)]
    conn.commit.assert_called_once()


def test_sincronizar_esquema_ddl_ejecuta_script_y_recalcula_columnas():
    cur = MagicMock()
    conn = _conn(cur)

    maestro.sincronizar_esquema_ddl(conn)

    assert "CREATE EXTENSION IF NOT EXISTS vector" in cur.execute.call_args_list[0].args[0]
    assert "UPDATE articulos SET titulo = titulo" in cur.execute.call_args_list[1].args[0]
    assert conn.commit.call_count == 2


def test_sincronizar_articulos_json_omite_si_no_hay_archivo(tmp_path):
    with patch.object(maestro, "RUTA_JSON", tmp_path / "missing.json"):
        maestro.sincronizar_articulos_json(MagicMock())


def test_recalcular_embeddings_completos_no_hace_nada_sin_articulos():
    cur = MagicMock()
    cur.fetchall.return_value = []
    conn = _conn(cur)

    with patch.object(maestro, "get_model_titulo"), \
         patch.object(maestro, "get_model_texto"):
        maestro.recalcular_embeddings_completos(conn)

    cur.executemany.assert_not_called()


def test_emitir_auditoria_final_muestra_indices():
    cur = MagicMock()
    cur.fetchone.return_value = (1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    cur.fetchall.return_value = [("idx_embedding", "CREATE INDEX ...")]

    maestro.emitir_auditoria_final(_conn(cur))

    assert cur.execute.call_count == 2


def test_verificar_estado_hashes_y_normalizados_consulta_todos_los_contadores():
    cur = MagicMock()
    cur.fetchone.side_effect = [(10,), (9,), (8,), (7,), (6,), (5,), (4,), (3,)]

    with patch.object(normalizados, "get_conn", return_value=_conn(cur)):
        normalizados.verificar_estado_hashes_y_normalizados()

    assert cur.execute.call_count == 8


def test_migracion_008_embeddings_meta_seed_coincide_con_constantes():
    from pathlib import Path
    from baco.server.services.embeddings import (
        MODEL_TITULO_NAME,
        DIM_TITULO,
        MODEL_TEXTO_NAME,
        DIM_TEXTO,
    )

    sql_path = Path(__file__).resolve().parents[2] / "baco" / "server" / "db" / "migraciones" / "008_embeddings_meta.sql"
    assert sql_path.exists(), f"El archivo {sql_path} debe existir."

    sql_content = sql_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS embeddings_meta" in sql_content
    assert "('titulo', 'paraphrase-multilingual-MiniLM-L12-v2', 384)" in sql_content or \
           f"('titulo', '{MODEL_TITULO_NAME}', {DIM_TITULO})" in sql_content
    assert "('texto', 'intfloat/multilingual-e5-base', 768)" in sql_content or \
           f"('texto', '{MODEL_TEXTO_NAME}', {DIM_TEXTO})" in sql_content

    # Verificación estricta de presencia de cada constante exacta en el script
    assert MODEL_TITULO_NAME in sql_content
    assert str(DIM_TITULO) in sql_content
    assert MODEL_TEXTO_NAME in sql_content
    assert str(DIM_TEXTO) in sql_content
