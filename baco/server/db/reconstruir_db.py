import sys
import time
import argparse
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import json
import os
from baco.server.db.config import get_conn, DB_NAME
from baco.server.db.ingesta import normalizar_articulo, upsert_articulos

RUTA_JSON = Path(os.getenv("RUTA_ARTICULOS_JSON", PROJECT_ROOT / "data" / "articulos.json"))


def leer_articulos_json(ruta: Path = RUTA_JSON) -> list[dict]:
    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [a for a in (normalizar_articulo(item) for item in data) if a]

from baco.server.services.embeddings import (
    embedding_titulo,
    embedding_texto,
    get_model_titulo,
    get_model_texto,
    DIM_TITULO,
    DIM_TEXTO,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reconstruir_db")

SCHEMA_FILE = Path(__file__).resolve().parent / "schema_completo.sql"


def aplicar_esquema_ddl(conn, reset: bool = False):
    print("\n" + "=" * 75)
    print(" PASO 1: APLICACIÓN DE ESQUEMA DDL COMPLETO E IDEMPOTENTE")
    print("=" * 75)
    if reset:
        print("[!] ATENCIÓN: Reiniciando esquema 'public' completo (DROP SCHEMA CASCADE)...")
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        conn.commit()
        print("[+] Esquema public reiniciado en blanco.")

    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"No se encontró el archivo de esquema {SCHEMA_FILE}")

    print(f"[+] Ejecutando {SCHEMA_FILE.name}...")
    ddl_sql = SCHEMA_FILE.read_text(encoding="utf-8")

    with conn.cursor() as cur:
        cur.execute(ddl_sql)
    conn.commit()
    print("[+] Extensiones, funciones, tablas, columnas calculadas, triggers e índices HNSW aplicados con éxito.")


def sincronizar_articulos(conn, forzar_actualizacion: bool = False):
    print("\n" + "=" * 75)
    print(" PASO 2: INGESTA Y SINCRONIZACIÓN DE ARTÍCULOS DESDE JSON")
    print("=" * 75)
    if not RUTA_JSON.exists():
        print(f"[-] Archivo {RUTA_JSON.name} no encontrado en la ruta esperada. Omitiendo ingesta.")
        return 0
    print(f"[+] Leyendo artículos desde {RUTA_JSON.name}...")
    articulos = leer_articulos_json(RUTA_JSON)
    print(f"[+] Total artículos leídos del archivo: {len(articulos)}")
    print("[+] Ejecutando upsert determinista en PostgreSQL...")
    resumen = upsert_articulos(conn, articulos)
    conn.commit()
    print(f"[+] Ingesta completada con éxito: {resumen}")

    if forzar_actualizacion:
        print("[+] Sincronizando columnas STORED...")
        with conn.cursor() as cur:
            cur.execute("UPDATE articulos SET titulo = titulo, texto = texto;")
        conn.commit()

    return len(articulos)


def recalcular_embeddings(conn, batch_size: int = 64, solo_pendientes: bool = True):
    print("\n" + "=" * 75)
    print(" PASO 3: CÁLCULO DE EMBEDDINGS VECTORIALES (MODELOS OFICIALES ONNX INT8)")
    print(f"  > Modelo Título: paraphrase-multilingual-MiniLM-L12-v2 ({DIM_TITULO} dim)")
    print(f"  > Modelo Texto : intfloat/multilingual-e5-base ({DIM_TEXTO} dim)")
    print(f"  > Batch Size   : {batch_size}")
    print(f"  > Modo         : {'Solo registros sin embeddings' if solo_pendientes else 'Recálculo 100% total'}")
    print("=" * 75)

    condicion = "WHERE embedding_titulo IS NULL OR embedding_texto IS NULL" if solo_pendientes else ""

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT id, titulo, texto_sin_headers
            FROM articulos
            {condicion}
            ORDER BY id;
        """)
        articulos = cur.fetchall()

    total = len(articulos)
    print(f"[+] Artículos a procesar: {total}")

    if total == 0:
        print("[+] No hay artículos pendientes de embeddings.")
        return

    print("[+] Cargando modelos ONNX INT8 en memoria...")
    t0 = time.perf_counter()
    model_tit = get_model_titulo()
    model_txt = get_model_texto()
    print(f"[+] Modelos listos en {(time.perf_counter() - t0):.2f} segundos.")

    from tqdm import tqdm
    pbar = tqdm(total=total, desc="Generando Embeddings", unit="art")
    t_inicio = time.perf_counter()

    for i in range(0, total, batch_size):
        lote = articulos[i:i + batch_size]
        ids_lote = [row[0] for row in lote]
        titulos_lote = [row[1] if (row[1] and row[1].strip()) else "" for row in lote]
        textos_lote = [row[2] if (row[2] and row[2].strip()) else "" for row in lote]

        vectores_tit = embedding_titulo(titulos_lote, model=model_tit)
        vectores_txt = embedding_texto(textos_lote, model=model_txt)

        params_update = []
        for idx, art_id in enumerate(ids_lote):
            vec_t = vectores_tit[idx] if vectores_tit else None
            vec_x = vectores_txt[idx] if vectores_txt else None

            str_vec_tit = ("[" + ",".join(str(f) for f in vec_t) + "]") if vec_t else None
            str_vec_txt = ("[" + ",".join(str(f) for f in vec_x) + "]") if vec_x else None
            params_update.append((str_vec_tit, str_vec_txt, art_id))

        with conn.cursor() as cur:
            cur.executemany("""
                UPDATE articulos
                SET embedding_titulo = %s,
                    embedding_texto = %s
                WHERE id = %s;
            """, params_update)
        conn.commit()
        pbar.update(len(lote))

    pbar.close()
    t_total = time.perf_counter() - t_inicio
    print(f"\n[+] Embeddings generados y persistidos en {t_total:.2f} s ({(total / max(t_total, 0.01)):.1f} art/s).")


def auditar_base_de_datos(conn):
    print("\n" + "=" * 75)
    print(" PASO 4: AUDITORÍA DE INTEGRIDAD FINAL")
    print("=" * 75)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(titulo_normalizado) as con_titulo_norm,
                COUNT(texto_normalizado) as con_texto_norm,
                COUNT(base_titulo) as con_base_titulo,
                COUNT(texto_sin_headers) as con_texto_sin_headers,
                COUNT(hash_titulo) as con_hash_titulo,
                COUNT(hash_texto_sin_headers) as con_hash_sin_headers,
                COUNT(embedding_titulo) as con_emb_titulo,
                COUNT(embedding_texto) as con_emb_texto
            FROM articulos;
        """)
        row = cur.fetchone()

        cur.execute("SELECT columna, model_name, dimension FROM embeddings_meta ORDER BY columna;")
        meta_rows = cur.fetchall()

    (total, c_tn, c_xn, c_bt, c_tsh, c_ht, c_hxsh, c_et, c_ex) = row

    print(f" • Artículos totales en BD         : {total}")
    print(f" • Títulos normalizados            : {c_tn} / {total}")
    print(f" • Series base detectadas          : {c_bt} / {total}")
    print(f" • Textos sin headers limpios      : {c_tsh} / {total}")
    print(f" • Hashes MD5 título               : {c_ht} / {total}")
    print(f" • Hashes MD5 texto sin headers    : {c_hxsh} / {total}")
    print(f" • Embeddings de Título (384 dim)  : {c_et} / {total}")
    print(f" • Embeddings de Texto  (768 dim)  : {c_ex} / {total}")
    print(" • Metadatos de embeddings registrados:")
    for col, m_name, dim in meta_rows:
        print(f"    - {col}: {m_name} ({dim} dim)")

    print("\n" + "=" * 75)
    print(" RECONSTRUCCIÓN Y AUDITORÍA FINALIZADA CON ÉXITO")
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Reconstrucción y sincronización integral de la base de datos de BACO."
    )
    parser.add_argument("--solo-schema", action="store_true", help="Aplica únicamente el DDL y tablas sin cargar datos.")
    parser.add_argument("--cargar-json", action="store_true", help="Ingesta y sincroniza los artículos desde articulos.json.")
    parser.add_argument("--con-embeddings", action="store_true", help="Calcula los embeddings vectoriales ONNX INT8.")
    parser.add_argument("--todo-embeddings", action="store_true", help="Fuerza el recálculo al 100% de embeddings (incluso los ya calculados).")
    parser.add_argument("--batch-size", type=int, default=64, help="Tamaño de lote para cálculo de embeddings (default 64).")
    parser.add_argument("--reset", action="store_true", help="Reinicia el esquema public completo desde cero (DROP SCHEMA public CASCADE).")
    parser.add_argument("--forzar", action="store_true", help="Confirma el reinicio destructivo (--reset).")

    args = parser.parse_args()

    if args.reset and not args.forzar:
        print("[-] Para ejecutar --reset debe incluir también la bandera --forzar.")
        sys.exit(1)

    with get_conn(autocommit=False) as conn:
        aplicar_esquema_ddl(conn, reset=args.reset)

        if not args.solo_schema:
            if args.cargar_json or args.reset:
                sincronizar_articulos(conn, forzar_actualizacion=True)

            if args.con_embeddings or args.todo_embeddings:
                recalcular_embeddings(
                    conn,
                    batch_size=args.batch_size,
                    solo_pendientes=not args.todo_embeddings
                )

        auditar_base_de_datos(conn)


if __name__ == "__main__":
    main()
