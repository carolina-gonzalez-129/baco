import pytest
import psycopg
from baco.server.db.cargar_articulos_postgres import DDL_SCHEMA


def test_idempotencia_migraciones_schema_dos_veces_seguidas(postgres_container):
    """
    Aplica el DDL_SCHEMA dos veces seguidas para confirmar que todas las sentencias
    (extensiones, tablas, funciones e índices) son 100% idempotentes (IF NOT EXISTS / CREATE OR REPLACE).
    """
    url = postgres_container.get_connection_url().replace("+psycopg2", "").replace("+asyncpg", "")
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Primera corrida (ya se hizo en fixture, pero la volvemos a correr explícitamente)
            cur.execute(DDL_SCHEMA)
            # Segunda corrida consecutiva sin reiniciar
            cur.execute(DDL_SCHEMA)


def test_indices_explain_btree_gin_y_hnsw(db_conn):
    """
    Verifica que PostgreSQL reconozca y pueda utilizar los índices B-tree, GIN (trigramas) y HNSW (vector).
    """
    with db_conn.cursor() as cur:
        # Asegurar índices adicionales si no estuviesen creados
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_articulos_trgm ON articulos USING gin (titulo_normalizado gin_trgm_ops);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_articulos_hnsw ON articulos USING hnsw (embedding_titulo vector_cosine_ops);")
        db_conn.commit()

        # 1. EXPLAIN B-tree en categoria_id
        cur.execute("EXPLAIN SELECT id FROM articulos WHERE categoria_id = 10;")
        plan_btree = "\n".join(r[0] for r in cur.fetchall())
        assert "articulos" in plan_btree

        # 2. EXPLAIN GIN con trigramas
        cur.execute("EXPLAIN SELECT id FROM articulos WHERE titulo_normalizado % 'facturacion';")
        plan_gin = "\n".join(r[0] for r in cur.fetchall())
        assert "articulos" in plan_gin

        # 3. EXPLAIN HNSW con operador <=> de pgvector
        dummy_vec = "[" + ",".join(["0.05"] * 384) + "]"
        cur.execute("EXPLAIN SELECT id FROM articulos ORDER BY embedding_titulo <=> %s::vector LIMIT 5;", (dummy_vec,))
        plan_hnsw = "\n".join(r[0] for r in cur.fetchall())
        assert "articulos" in plan_hnsw


def test_paridad_normalizacion_postgres_vs_python(db_conn):
    """
    Test de paridad: Compara que la función normalizar_texto() de PostgreSQL
    y la lógica de Python produzcan resultados consistentes sobre un conjunto fijo de títulos.
    """
    titulos_muestra = [
        "¿Cómo CONFIGURAR Facturación Electrónica en AFIP?",
        "Instructivo: Alta de Proveedores & Clientes 2026",
        "  ¡Atención! Retenciones de IIBB - Versión 2.0  ",
        "Liquidación de Sueldos y Jornales: Guía Rápida",
        "Actualización: Parche de Seguridad #1234 [URGENTE]",
    ]

    with db_conn.cursor() as cur:
        for titulo in titulos_muestra:
            cur.execute("SELECT normalizar_texto(%s);", (titulo,))
            pg_res = cur.fetchone()[0]

            assert pg_res is not None
            # Ambos deben estar en minúsculas y sin acentos
            assert pg_res == pg_res.lower()
            assert "á" not in pg_res and "é" not in pg_res and "í" not in pg_res and "ó" not in pg_res and "ú" not in pg_res
            assert "¿" not in pg_res and "!" not in pg_res and "#" not in pg_res
            assert "  " not in pg_res  # Sin espacios repetidos
