"""
Script de migración para recalcular y actualizar los embeddings del campo texto.

Características:
- Calcula embeddings ÚNICAMENTE con la nueva función oficial `embedding_texto`.
- Idempotente: registra artículos procesados en `migracion_embeddings_texto`.
  Si se interrumpe y se vuelve a ejecutar, retoma exactamente donde se quedó.
- Procesa por lotes configurables con commits parciales.
- Barra de progreso (tqdm) y registro de logging detallado.
- Verifica dimensiones y tipo de columna antes de iniciar.
- Deja intactos los embeddings de título, hashes y pg_trgm.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import psycopg
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrar_embeddings_texto")

from baco.server.db.config import get_conn, DB_NAME

from baco.server.services.embeddings import (
    embedding_texto,
    get_model_texto,
    MODEL_TEXTO_NAME,
    DIM_TEXTO,
)


def verificar_columna_y_meta(conn) -> None:
    """Verifica que la columna embedding_texto exista en PostgreSQL como vector(768)

    y coincida con embeddings_meta.
    """
    logger.info("1. Verificando esquema de base de datos y tipo de columna...")
    with conn.cursor() as cur:
        # Verificar tipo de la columna
        cur.execute("""
            SELECT column_name, data_type, udt_name 
            FROM information_schema.columns 
            WHERE table_name = 'articulos' AND column_name = 'embedding_texto';
        """)
        col_info = cur.fetchone()
        if not col_info:
            raise RuntimeError("La columna 'embedding_texto' no existe en la tabla 'articulos'.")

        col_name, data_type, udt_name = col_info
        if udt_name != "vector":
            raise RuntimeError(
                f"La columna 'embedding_texto' tiene tipo {udt_name}, se esperaba 'vector'."
            )

        # Verificar dimensión en pg_attribute
        cur.execute("""
            SELECT atttypmod 
            FROM pg_attribute 
            WHERE attrelid = 'articulos'::regclass AND attname = 'embedding_texto';
        """)
        typmod_row = cur.fetchone()
        db_dim = typmod_row[0] if typmod_row else None
        if db_dim != DIM_TEXTO:
            raise RuntimeError(
                f"La dimensión de 'embedding_texto' en Postgres es {db_dim}, pero el modelo requiere {DIM_TEXTO}."
            )

        # Verificar tabla de metadata
        cur.execute("""
            SELECT model_name, dimension 
            FROM embeddings_meta 
            WHERE columna = 'texto';
        """)
        meta_row = cur.fetchone()
        if not meta_row:
            logger.warning("No se encontró registro para 'texto' en embeddings_meta. Se insertará.")
            cur.execute("""
                INSERT INTO embeddings_meta (columna, model_name, dimension, creado_en)
                VALUES ('texto', %s, %s, NOW())
                ON CONFLICT (columna) DO UPDATE SET model_name = EXCLUDED.model_name, dimension = EXCLUDED.dimension;
            """, (MODEL_TEXTO_NAME, DIM_TEXTO))
            conn.commit()
        else:
            meta_model, meta_dim = meta_row
            logger.info(
                f"   [embeddings_meta] Modelo: '{meta_model}', Dimensión: {meta_dim}."
            )

    logger.info(
        f"   [VERIFICACIÓN OK] Columna 'embedding_texto' verificada: vector({DIM_TEXTO}). "
        f"No se requiere alterar la columna (la dimensión se preserva)."
    )


def preparar_tabla_control_idempotencia(conn) -> None:
    """Crea la tabla de control de migración si no existe."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS migracion_embeddings_texto (
                articulo_id INT PRIMARY KEY,
                migrado_en TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
    conn.commit()


def obtener_articulos_pendientes(conn, force: bool = False, limit: int | None = None) -> list[tuple[int, str | None]]:
    """Retorna los artículos que aún no han sido recalculados con la nueva función."""
    with conn.cursor() as cur:
        if force:
            logger.info("Modo FORCE activado: recalculando TODOS los artículos...")
            cur.execute("TRUNCATE TABLE migracion_embeddings_texto;")
            conn.commit()

        query = """
            SELECT id, texto 
            FROM articulos 
            WHERE id NOT IN (SELECT articulo_id FROM migracion_embeddings_texto)
            ORDER BY id ASC
        """
        if limit:
            query += f" LIMIT {limit}"
        query += ";"

        cur.execute(query)
        return cur.fetchall()


def ejecutar_migracion(batch_size: int = 32, force: bool = False, limit: int | None = None) -> dict:
    """Ejecuta la migración por lotes recalculando embeddings con embedding_texto."""
    print("==================================================================")
    print("      MIGRACIÓN: RECALCULAR EMBEDDINGS DE TEXTO (E5) EN BACO      ")
    print(f"  Modelo:     {MODEL_TEXTO_NAME} (dim: {DIM_TEXTO})")
    print(f"  Batch size: {batch_size}")
    print(f"  Modo Force: {force}")
    print("==================================================================")

    inicio_tiempo = time.time()

    with get_conn() as conn:
        verificar_columna_y_meta(conn)
        preparar_tabla_control_idempotencia(conn)

        articulos_pendientes = obtener_articulos_pendientes(conn, force=force, limit=limit)
        total_pendientes = len(articulos_pendientes)

        if total_pendientes == 0:
            logger.info("¡Todos los artículos ya fueron migrados con la nueva función!")
            logger.info("Operación idempotente completada: no hay registros pendientes.")
            return {"total_procesados": 0, "tiempo_segundos": time.time() - inicio_tiempo}

        logger.info(f"Artículos a migrar: {total_pendientes} (en lotes de {batch_size})")

        # Cargar modelo singleton E5
        model_texto = get_model_texto()

        pbar = tqdm(total=total_pendientes, desc="Migrando embeddings de texto", unit="art")
        total_migrados = 0

        for i in range(0, total_pendientes, batch_size):
            lote = articulos_pendientes[i:i + batch_size]
            ids_lote = [row[0] for row in lote]
            textos_originales = [row[1] for row in lote]

            # Llamada al ÚNICO punto de entrada oficial para embeddings de texto
            vectores = embedding_texto(
                textos_originales,
                batch_size=len(lote),
                model=model_texto,
            )

            with conn.cursor() as cur:
                for art_id, vec in zip(ids_lote, vectores):
                    if vec is not None:
                        vec_str = "[" + ",".join(str(f) for f in vec) + "]"
                        cur.execute("""
                            UPDATE articulos 
                            SET embedding_texto = %s 
                            WHERE id = %s;
                        """, (vec_str, art_id))
                    else:
                        # Texto vacío o solo imágenes: conserva NULL
                        cur.execute("""
                            UPDATE articulos 
                            SET embedding_texto = NULL 
                            WHERE id = %s;
                        """, (art_id,))

                    # Registrar en tabla de control para asegurar idempotencia
                    cur.execute("""
                        INSERT INTO migracion_embeddings_texto (articulo_id) 
                        VALUES (%s)
                        ON CONFLICT (articulo_id) DO UPDATE SET migrado_en = NOW();
                    """, (art_id,))

            conn.commit()
            total_migrados += len(lote)
            pbar.update(len(lote))

        pbar.close()

        # Actualizar fecha en embeddings_meta
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE embeddings_meta 
                SET creado_en = NOW() 
                WHERE columna = 'texto';
            """)
        conn.commit()

        duracion = time.time() - inicio_tiempo
        logger.info("==================================================================")
        logger.info(" ¡MIGRACIÓN DE EMBEDDINGS DE TEXTO FINALIZADA EXITOSAMENTE!")
        logger.info(f" Total artículos migrados: {total_migrados}")
        logger.info(f" Tiempo transcurrido: {duracion:.2f} segundos ({total_migrados / max(duracion, 0.001):.2f} art/s)")
        logger.info("==================================================================")

        return {"total_procesados": total_migrados, "tiempo_segundos": duracion}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migración idempotente de embeddings de texto en BACO.")
    parser.add_argument("--batch-size", type=int, default=32, help="Tamaño de lote para procesar.")
    parser.add_argument("--force", action="store_true", help="Forzar recálculo completo de todos los artículos.")
    parser.add_argument("--limit", type=int, default=None, help="Límite opcional de artículos a procesar.")

    args = parser.parse_args()
    ejecutar_migracion(batch_size=args.batch_size, force=args.force, limit=args.limit)
