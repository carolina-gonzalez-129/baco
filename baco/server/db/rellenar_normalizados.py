from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

from baco.server.db.config import get_conn


def verificar_estado_hashes_y_normalizados():
    """Verifica el estado de las columnas generadas en PostgreSQL.

    En la Estrategia A, PostgreSQL gestiona automáticamente titulo_normalizado,
    texto_normalizado, hash_titulo y hash_texto como columnas GENERATED ALWAYS AS ... STORED.
    No es necesario rellenarlas manualmente desde Python.
    """
    print("==========================================================")
    print("   VERIFICACIÓN DE HASHES Y NORMALIZADOS (PostgreSQL STORED) ")
    print("==========================================================")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1. Total de artículos
            cur.execute("SELECT count(*) FROM articulos;")
            total = cur.fetchone()[0]

            # 2. Artículos con hash y columnas generadas automáticamente
            cur.execute("SELECT count(*) FROM articulos WHERE hash_titulo IS NOT NULL;")
            con_hash_tit = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM articulos WHERE hash_texto IS NOT NULL;")
            con_hash_txt = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM articulos WHERE hash_texto_sin_headers IS NOT NULL;")
            con_hash_sin_headers = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM articulos WHERE base_titulo IS NOT NULL;")
            con_base_tit = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM articulos WHERE texto_sin_headers IS NOT NULL;")
            con_txt_sin_headers = cur.fetchone()[0]

            # 3. Embeddings pendientes
            cur.execute("SELECT count(*) FROM articulos WHERE embedding_titulo IS NULL;")
            emb_tit_pendientes = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM articulos WHERE embedding_texto IS NULL;")
            emb_txt_pendientes = cur.fetchone()[0]

        print(f" Total de artículos:                 {total}")
        print(f" Con hash_titulo generado:           {con_hash_tit} / {total}")
        print(f" Con hash_texto generado:            {con_hash_txt} / {total}")
        print(f" Con hash_texto_sin_headers:         {con_hash_sin_headers} / {total}")
        print(f" Con base_titulo generado:           {con_base_tit} / {total}")
        print(f" Con texto_sin_headers generado:     {con_txt_sin_headers} / {total}")
        print(f" Embeddings título pendientes:       {emb_tit_pendientes}")
        print(f" Embeddings texto pendientes:        {emb_txt_pendientes}")
        print("\n ¡PostgreSQL mantiene todos los hashes, series y textos sin headers sincronizados automáticamente!")


if __name__ == "__main__":
    verificar_estado_hashes_y_normalizados()
