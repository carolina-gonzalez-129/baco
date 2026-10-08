"""
Pipeline Maestro de Migración, Ingesta y Recálculo Integral para BACO.

Este script:
1. Sincroniza y valida el esquema DDL en PostgreSQL (Extensiones, Funciones SQL, Columnas STORED e Índices HNSW).
2. Fuerza la re-generación de todas las columnas calculadas (normalizados, títulos base, texto limpio y hashes MD5).
3. Ingesta / actualiza artículos desde el JSON de Discourse si existen nuevos registros.
4. Recalcula al 100% todos los embeddings de título y texto con los modelos oficiales ONNX INT8 en lotes.
5. Emite un informe de auditoría y verificación final de la base de datos.
"""

import sys
import time
import json
import logging
from pathlib import Path
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrar_y_sincronizar_todo")

from baco.server.db.config import DB_NAME, get_conn
from baco.server.db.cargar_articulos_postgres import RUTA_JSON
from baco.server.services.embeddings import (
    embedding_titulo,
    embedding_texto,
    get_model_titulo,
    get_model_texto,
    DIM_TITULO,
    DIM_TEXTO,
)

BATCH_SIZE_EMBEDDINGS = 64


def sincronizar_esquema_ddl(conn):
    print("\n" + "=" * 75)
    print(" PASO 1: SINCRONIZACIÓN DE ESQUEMA DDL, FUNCIONES E ÍNDICES HNSW")
    print("=" * 75)

    ddl_script = r"""
    CREATE EXTENSION IF NOT EXISTS unaccent;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE OR REPLACE FUNCTION public.normalizar_texto(t text)
    RETURNS text AS $$
        SELECT NULLIF(
            trim(
                regexp_replace(
                    regexp_replace(
                        lower(public.unaccent('public.unaccent', coalesce(t, ''))),
                        '[^\w\s]|_', ' ', 'g'
                    ),
                    '\s+', ' ', 'g'
                )
            ),
            ''
        );
    $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

    CREATE OR REPLACE FUNCTION public.titulo_base(t text)
    RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT btrim(regexp_replace(
            regexp_replace(t,
                           '\\m(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\\M|\\d+',
                           '', 'g'),
            '\\s+', ' ', 'g'));
    $$;

    CREATE OR REPLACE FUNCTION public.limpiar_headers(t text)
    RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
               WHEN t IS NULL OR t = '' THEN t
               ELSE btrim(
                       regexp_replace(
                               regexp_replace(
                                       regexp_replace(
                                               regexp_replace(
                                                       regexp_replace(t, '(?n)^\\s*#{1,6}\\s+.*$', '', 'g'),
                                                       '(?n)^\\s*(\\*\\*)?(consulta|respuesta|pasos a seguir|requiere app\\s*builder|antes de empezar|modo de uso|¿?para qu[eé] sirve\\??)(\\*\\*)?\\s*:?\\s*$',
                                                       '', 'gi'
                                               ),
                                               '(?n)^\\s*(\\*\\s*\\*\\s*\\*|-{3,}|_{3,})\\s*$', '', 'g'
                                       ),
                                       '!?\\[image[^\\]]*\\]\\([^\\)]+\\)', '', 'gi'
                               ),
                               '\\n\\s*\\n+', E'\\n\\n', 'g'
                       )
                    )
               END;
    $$;

    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='articulos' AND column_name='texto_sin_headers'
        ) THEN
            ALTER TABLE articulos
            ADD COLUMN texto_sin_headers text GENERATED ALWAYS AS (limpiar_headers(texto)) STORED;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='articulos' AND column_name='base_titulo'
        ) THEN
            ALTER TABLE articulos
            ADD COLUMN base_titulo text GENERATED ALWAYS AS (titulo_base(normalizar_texto(titulo))) STORED;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='articulos' AND column_name='hash_texto_sin_headers'
        ) THEN
            ALTER TABLE articulos
            ADD COLUMN hash_texto_sin_headers text GENERATED ALWAYS AS (
                CASE
                    WHEN ((texto IS NOT NULL) AND (btrim(texto) <> '')) 
                    THEN md5(normalizar_texto(limpiar_headers(texto)))
                    ELSE NULL
                END
            ) STORED;
        END IF;
    END $$;

    CREATE INDEX IF NOT EXISTS idx_articulos_categoria ON articulos(categoria_id);
    CREATE INDEX IF NOT EXISTS idx_articulos_actualizado ON articulos(actualizado);
    CREATE INDEX IF NOT EXISTS idx_articulos_hash_titulo ON articulos(hash_titulo);
    CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto ON articulos(hash_texto);
    CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto_sin_headers ON articulos(hash_texto_sin_headers);
    CREATE INDEX IF NOT EXISTS idx_articulos_base_titulo ON articulos(base_titulo);
    CREATE INDEX IF NOT EXISTS idx_articulos_titulo_trgm ON articulos USING gin (titulo_normalizado gin_trgm_ops);
    CREATE INDEX IF NOT EXISTS idx_articulos_embedding_texto ON articulos USING hnsw (embedding_texto vector_cosine_ops);
    CREATE INDEX IF NOT EXISTS idx_articulos_embedding_titulo ON articulos USING hnsw (embedding_titulo vector_cosine_ops);
    """

    with conn.cursor() as cur:
        cur.execute(ddl_script)
    conn.commit()
    print("[+] Esquema DDL, funciones e índices HNSW verificados correctamente.")

    print("\n[+] Forzando re-generación de columnas calculadas STORED en PostgreSQL...")
    with conn.cursor() as cur:
        cur.execute("UPDATE articulos SET titulo = titulo, texto = texto;")
    conn.commit()
    print("[+] Columnas generadas (normalizados, series, texto limpio, hashes MD5) recalculadas al 100%.")


def sincronizar_articulos_json(conn):
    print("\n" + "=" * 75)
    print(" PASO 2: VERIFICACIÓN E INGESTA DE ARTÍCULOS DESDE JSON")
    print("=" * 75)

    if not RUTA_JSON.exists():
        print(f"[-] Archivo {RUTA_JSON.name} no encontrado. Omitiendo ingesta JSON.")
        return

    print(f"[+] Leyendo artículos desde {RUTA_JSON.name}...")
    with open(RUTA_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"[+] Artículos en JSON: {len(data)}. Sincronizando categorías y tags...")

    categorias_dict = {}
    tags_dict = {}

    for item in data:
        cat_id = item.get("category_id")
        if cat_id and cat_id not in categorias_dict:
            categorias_dict[cat_id] = f"Categoría {cat_id}"
        for tag in item.get("tags", []):
            if isinstance(tag, dict) and "name" in tag:
                t_id = tag.get("id") or hash(tag["name"]) % 1000000
                tags_dict[t_id] = (tag["name"], tag.get("slug") or tag["name"].lower())
            elif isinstance(tag, str):
                t_id = abs(hash(tag)) % 1000000
                tags_dict[t_id] = (tag, tag.lower())

    with conn.cursor() as cur:
        # Inserción de categorías
        cat_params = [(cid, cnom) for cid, cnom in categorias_dict.items()]
        cur.executemany("""
            INSERT INTO categorias (id, nombre) VALUES (%s, %s)
            ON CONFLICT (id) DO NOTHING;
        """, cat_params)

        # Inserción de tags
        tag_params = [(tid, name, slug) for tid, (name, slug) in tags_dict.items()]
        cur.executemany("""
            INSERT INTO tags (id, name, slug) VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING;
        """, tag_params)
        art_params = []
        for item in data:
            art_id = item.get("id")
            titulo = item.get("title") or item.get("titulo") or "Sin título"
            categoria_id = item.get("category_id")
            url = f"https://bc-dev.finneg.com/t/{item.get('slug', 'tema')}/{art_id}"
            texto = item.get("raw") or item.get("cooked") or item.get("texto") or ""
            actualizado = item.get("updated_at") or item.get("created_at") or None
            art_params.append((art_id, titulo, categoria_id, url, texto, actualizado))

        cur.executemany("""
            INSERT INTO articulos (id, titulo, categoria_id, url, texto, actualizado)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                titulo = EXCLUDED.titulo,
                categoria_id = EXCLUDED.categoria_id,
                url = EXCLUDED.url,
                texto = EXCLUDED.texto,
                actualizado = EXCLUDED.actualizado;
        """, art_params)

    conn.commit()
    print("[+] Sincronización de artículos, categorías y tags completada.")

def recalcular_embeddings_completos(conn):
    print("\n" + "=" * 75)
    print(" PASO 3: RECÁLCULO INTEGRAL DE EMBEDDINGS (ONNX INT8)")
    print(f"  > Modelo Título: paraphrase-multilingual-MiniLM-L12-v2 ({DIM_TITULO} dim) [AVX2]")
    print(f"  > Modelo Texto : intfloat/multilingual-e5-base ({DIM_TEXTO} dim) [AVX512/VNNI]")
    print(f"  > Batch Size   : {BATCH_SIZE_EMBEDDINGS}")
    print("=" * 75)

    print("\n[+] Inicializando modelos ONNX INT8...")
    t0 = time.perf_counter()
    model_tit = get_model_titulo()
    model_txt = get_model_texto()
    print(f"[+] Modelos ONNX listos en {(time.perf_counter() - t0):.2f} segundos.")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, titulo, texto_sin_headers
            FROM articulos
            ORDER BY id;
        """)
        articulos = cur.fetchall()

    total = len(articulos)
    print(f"[+] Total de artículos a procesar: {total}")

    if total == 0:
        print("[!] No se encontraron artículos.")
        return

    t_inicio = time.perf_counter()
    pbar = tqdm(total=total, desc="Calculando Embeddings ONNX", unit="art")

    for i in range(0, total, BATCH_SIZE_EMBEDDINGS):
        lote = articulos[i:i + BATCH_SIZE_EMBEDDINGS]

        ids_lote = []
        titulos_lote = []
        textos_lote = []

        for row in lote:
            art_id, tit, txt = row
            ids_lote.append(art_id)
            titulos_lote.append(tit if (tit and tit.strip()) else "")
            textos_lote.append(txt if (txt and txt.strip()) else "")

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
    print(f"\n[+] Embeddings calculados y persistidos en {t_total:.2f} s ({t_total/60:.2f} min).")
    print(f"[+] Velocidad promedio: {(total / t_total):.2f} artículos/segundo.")

def emitir_auditoria_final(conn):
    print("\n" + "=" * 75)
    print(" PASO 4: AUDITORÍA Y VERIFICACIÓN FINAL DE LA BASE DE DATOS")
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
                COUNT(hash_texto) as con_hash_texto,
                COUNT(hash_texto_sin_headers) as con_hash_sin_headers,
                COUNT(embedding_titulo) as con_emb_titulo,
                COUNT(embedding_texto) as con_emb_texto
            FROM articulos;
        """)
        row = cur.fetchone()

        cur.execute("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'articulos' AND indexname LIKE '%embedding%';
        """)
        indices_vectoriales = cur.fetchall()

    (total, c_tn, c_xn, c_bt, c_tsh, c_ht, c_hx, c_hxsh, c_et, c_ex) = row

    print(f" • Total de artículos en base de datos : {total}")
    print(f" • Títulos normalizados               : {c_tn} / {total}")
    print(f" • Títulos base (Series)              : {c_bt} / {total}")
    print(f" • Texto sin headers                  : {c_tsh} / {total}")
    print(f" • Hash MD5 título                    : {c_ht} / {total}")
    print(f" • Hash MD5 texto sin headers         : {c_hxsh} / {total}")
    print(f" • Embeddings de Título (384 dim)     : {c_et} / {total}")
    print(f" • Embeddings de Texto  (768 dim)     : {c_ex} / {total}")
    print("\n • Índices Vectoriales HNSW:")
    for idx_name, idx_def in indices_vectoriales:
        print(f"    - {idx_name}: {idx_def}")

    print("\n" + "=" * 75)
    print(" ¡MIGRACIÓN, INGESTA Y SINCRONIZACIÓN FINALIZADA CON ÉXITO!")
    print("=" * 75 + "\n")


def ejecutar_migracion_maestra():
    with get_conn(autocommit=False) as conn:
        sincronizar_esquema_ddl(conn)
        sincronizar_articulos_json(conn)
        recalcular_embeddings_completos(conn)
        emitir_auditoria_final(conn)

if __name__ == "__main__":
    ejecutar_migracion_maestra()
