"""
Script para recalcular y sincronizar al 100% todos los embeddings de título y texto
en la base de datos PostgreSQL utilizando los modelos optimizados ONNX INT8.

Modelos utilizados:
- TÍTULO: paraphrase-multilingual-MiniLM-L12-v2 (dim: 384) [ONNX INT8 AVX2]
- TEXTO:  intfloat/multilingual-e5-base (dim: 768)          [ONNX INT8 AVX512/VNNI]
"""

import sys
import time
import logging
from pathlib import Path
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("recalcular_embeddings_onnx")

from baco.server.db.config import get_conn
from baco.server.services.embeddings import (
    embedding_titulo,
    embedding_texto,
    get_model_titulo,
    get_model_texto,
    DIM_TITULO,
    DIM_TEXTO,
)

BATCH_SIZE = 32


def recalcular_todos_los_embeddings():
    print("\n" + "=" * 70)
    print(" RECALCULANDO EMBEDDINGS EN POSTGRESQL CON ONNX INT8")
    print(f"  > Modelo Título : paraphrase-multilingual-MiniLM-L12-v2 ({DIM_TITULO} dim)")
    print(f"  > Modelo Texto  : intfloat/multilingual-e5-base ({DIM_TEXTO} dim)")
    print(f"  > Batch Size    : {BATCH_SIZE}")
    print("=" * 70)

    # 1. Precargar los modelos ONNX
    print("\n[+] Inicializando modelos ONNX INT8 en memoria...")
    t0_carga = time.perf_counter()
    model_tit = get_model_titulo()
    model_txt = get_model_texto()
    print(f"[+] Modelos listos en {(time.perf_counter() - t0_carga):.2f} segundos.")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, titulo, texto_sin_headers
                FROM articulos
                ORDER BY id;
            """)
            articulos = cur.fetchall()

        total = len(articulos)
        print(f"\n[+] Total de artículos a recalcular: {total}")

        if total == 0:
            print("[!] No se encontraron artículos en la base de datos.")
            return

        t_inicio = time.perf_counter()
        actualizados = 0

        pbar = tqdm(total=total, desc="Sincronizando ONNX INT8", unit="art")

        for i in range(0, total, BATCH_SIZE):
            lote = articulos[i:i + BATCH_SIZE]

            ids_lote = []
            titulos_lote = []
            textos_lote = []

            for row in lote:
                art_id, tit_orig, txt_orig = row
                ids_lote.append(art_id)
                titulos_lote.append(tit_orig if (tit_orig and tit_orig.strip()) else "")
                textos_lote.append(txt_orig if (txt_orig and txt_orig.strip()) else "")

            # Calcular embeddings en lote con ONNX INT8
            vectores_tit = embedding_titulo(titulos_lote, model=model_tit)
            vectores_txt = embedding_texto(textos_lote, model=model_txt)

            # Preparar parámetros para el UPDATE
            params_update = []
            for idx, art_id in enumerate(ids_lote):
                vec_t = vectores_tit[idx] if vectores_tit else None
                vec_x = vectores_txt[idx] if vectores_txt else None

                str_vec_tit = ("[" + ",".join(str(f) for f in vec_t) + "]") if vec_t else None
                str_vec_txt = ("[" + ",".join(str(f) for f in vec_x) + "]") if vec_x else None

                params_update.append((str_vec_tit, str_vec_txt, art_id))

            # Ejecutar actualización en lote
            with conn.cursor() as cur:
                cur.executemany("""
                    UPDATE articulos
                    SET embedding_titulo = %s,
                        embedding_texto = %s
                    WHERE id = %s;
                """, params_update)

            conn.commit()
            actualizados += len(lote)
            pbar.update(len(lote))

        pbar.close()
        t_total = time.perf_counter() - t_inicio

        print("\n" + "=" * 70)
        print(" ¡RECALCULO COMPLETADO CON ÉXITO!")
        print(f"  > Artículos actualizados : {actualizados} / {total}")
        print(f"  > Tiempo total           : {t_total:.2f} s ({t_total/60:.2f} min)")
        print(f"  > Velocidad promedio     : {(actualizados / t_total):.2f} artículos/segundo")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    recalcular_todos_los_embeddings()
