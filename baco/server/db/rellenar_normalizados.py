import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from baco.server.services.normalizar import normalizar

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "baco_db")


def asegurar_columnas_e_indices(conn):
    """Asegura que existan las columnas e índices para búsquedas normalizadas."""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS titulo_normalizado VARCHAR(500);")
        cur.execute("ALTER TABLE articulos ADD COLUMN IF NOT EXISTS texto_normalizado TEXT;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_articulos_titulo_norm ON articulos(titulo_normalizado);")
    conn.commit()


def rellenar_campos_normalizados():
    print("==========================================================")
    print("   RELLENANDO TITULO_NORMALIZADO Y TEXTO_NORMALIZADO      ")
    print("==========================================================")

    with psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME
    ) as conn:
        asegurar_columnas_e_indices(conn)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, titulo, texto 
                FROM articulos 
                WHERE titulo_normalizado IS NULL OR texto_normalizado IS NULL;
            """)
            pendientes = cur.fetchall()

        total = len(pendientes)
        if total == 0:
            print("\n ¡Todos los artículos ya tienen sus campos normalizados! Nada que hacer.")
            return

        print(f"\n Se encontraron {total} artículos pendientes de normalizar.")
        print(" Procesando y actualizando en la base de datos...\n")

        actualizaciones = []
        for art_id, tit, txt in tqdm(pendientes, desc="Normalizando"):
            tit_norm = normalizar(tit or "")
            txt_norm = normalizar(txt or "")
            actualizaciones.append((tit_norm, txt_norm, art_id))

        with conn.cursor() as cur:
            cur.executemany("""
                UPDATE articulos 
                SET titulo_normalizado = %s,
                    texto_normalizado = %s 
                WHERE id = %s;
            """, actualizaciones)
        conn.commit()

    print(f"\n ¡Listo! Se normalizaron y guardaron exitosamente {total} artículos.")


if __name__ == "__main__":
    rellenar_campos_normalizados()
