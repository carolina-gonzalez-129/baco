import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

from baco.server.services.normalizar import normalizar, calcular_hash
from baco.server.db.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, get_conn


def asegurar_columnas_e_indices(conn):
    """Asegura que existan las extensiones, columnas de hashes, embeddings, normalizados e índices."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS titulo_normalizado VARCHAR(500);")
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS texto_normalizado TEXT;")
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS hash_titulo CHAR(32);")
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS hash_texto CHAR(32);")
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS embedding_titulo vector(384);")
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS embedding_texto vector(768);")
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS texto_1000 text GENERATED ALWAYS AS (left(texto_normalizado, 1000)) STORED;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_articulos_hash_titulo ON articulos(hash_titulo);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto ON articulos(hash_texto);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_texto1000_trgm ON articulos USING gin (texto_1000 gin_trgm_ops);")
    conn.commit()


def procesar_normalizacion_y_hashes():
    """Rellena hashes y normalizados pendientes o desactualizados.

    - Solo escribe en la base de datos si el hash calculado difiere del guardado
      (o si estaba en NULL).
    - Cuando el hash de un título o texto cambia, deja en NULL el embedding correspondiente
      para forzar su regeneración.
    """
    print("==========================================================")
    print("      RELLENADO Y VERIFICACIÓN DE HASHES Y NORMALIZADOS   ")
    print("==========================================================")

    with get_conn() as conn:
        asegurar_columnas_e_indices(conn)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, titulo, texto, titulo_normalizado, texto_normalizado, hash_titulo, hash_texto 
                FROM articulos 
                ORDER BY id ASC;
            """)
            filas = cur.fetchall()

        total = len(filas)
        print(f" Analizando {total} artículos en la base de datos...")

        actualizaciones = []
        for art_id, tit, txt, tit_norm_db, txt_norm_db, hash_tit_db, hash_txt_db in tqdm(filas, desc="Analizando hashes"):
            # Hashes y normalizados calculados actuales
            nuevo_hash_tit = calcular_hash(tit)
            nuevo_hash_txt = calcular_hash(txt)
            nuevo_tit_norm = normalizar(tit or "")
            nuevo_txt_norm = normalizar(txt or "")

            hash_tit_actual = hash_tit_db.strip() if hash_tit_db else None
            hash_txt_actual = hash_txt_db.strip() if hash_txt_db else None

            cambio_tit = (nuevo_hash_tit != hash_tit_actual) or (tit_norm_db is None and nuevo_tit_norm != "")
            cambio_txt = (nuevo_hash_txt != hash_txt_actual) or (txt_norm_db is None and nuevo_txt_norm != "")

            if not cambio_tit and not cambio_txt:
                continue

            actualizaciones.append({
                "id": art_id,
                "cambio_tit": cambio_tit,
                "cambio_txt": cambio_txt,
                "titulo_norm": nuevo_tit_norm if cambio_tit else tit_norm_db,
                "hash_titulo": nuevo_hash_tit if cambio_tit else hash_tit_actual,
                "texto_norm": nuevo_txt_norm if cambio_txt else txt_norm_db,
                "hash_texto": nuevo_hash_txt if cambio_txt else hash_txt_actual,
            })

        if not actualizaciones:
            print("\n ¡Todos los hashes y normalizados están al día! Ningún cambio necesario.")
            return

        print(f"\n Se detectaron {len(actualizaciones)} artículos que requieren actualización...")

        with conn.cursor() as cur:
            for item in tqdm(actualizaciones, desc="Actualizando DB"):
                # Si cambió título, invalidamos embedding_titulo = NULL
                # Si cambió texto, invalidamos embedding_texto = NULL
                if item["cambio_tit"] and item["cambio_txt"]:
                    cur.execute("""
                        UPDATE articulos
                        SET titulo_normalizado = %s,
                            hash_titulo = %s,
                            embedding_titulo = NULL,
                            texto_normalizado = %s,
                            hash_texto = %s,
                            embedding_texto = NULL
                        WHERE id = %s;
                    """, (item["titulo_norm"], item["hash_titulo"], item["texto_norm"], item["hash_texto"], item["id"]))
                elif item["cambio_tit"]:
                    cur.execute("""
                        UPDATE articulos
                        SET titulo_normalizado = %s,
                            hash_titulo = %s,
                            embedding_titulo = NULL
                        WHERE id = %s;
                    """, (item["titulo_norm"], item["hash_titulo"], item["id"]))
                elif item["cambio_txt"]:
                    cur.execute("""
                        UPDATE articulos
                        SET texto_normalizado = %s,
                            hash_texto = %s,
                            embedding_texto = NULL
                        WHERE id = %s;
                    """, (item["texto_norm"], item["hash_texto"], item["id"]))

        conn.commit()
        print(f"\n ¡Completado! Se actualizaron {len(actualizaciones)} artículos con sus nuevos hashes.")


if __name__ == "__main__":
    procesar_normalizacion_y_hashes()
