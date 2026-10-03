import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import psycopg
from tqdm import tqdm
from google import genai
from google.genai import types
from google.genai.errors import APIError

# Configuración de rutas del proyecto
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

# Configuración de base de datos
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "baco_db")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
BATCH_SIZE = 25  # Artículos por llamada a la API de Gemini
MAX_TEXT_CHARS = 3500  # Límite seguro para abarcar el 90%+ del contenido sin saturar tokens


def preparar_texto_para_embedding(titulo: str, texto: str) -> str:
    """Concatena título y texto limpiamente para capturar la semántica completa."""
    tit = (titulo or "").strip()
    txt = (texto or "").strip()
    cuerpo = txt[:MAX_TEXT_CHARS] if len(txt) > MAX_TEXT_CHARS else txt
    return f"Título: {tit}\n\nContenido:\n{cuerpo}"


def asegurar_columna_vector(conn):
    """Crea la extensión vector, la columna embedding y el índice HNSW si no existen."""
    print(" Verificando extensión y columna 'embedding' en Postgres...")
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"ALTER TABLE articulos ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIM});")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_articulos_embedding 
            ON articulos USING hnsw (embedding vector_cosine_ops);
        """)
    conn.commit()
    print(" Columna e índice HNSW listos.")


def obtener_articulos_pendientes(conn):
    """Retorna los artículos que aún no tienen embedding generado (idempotente)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, titulo, texto 
            FROM articulos 
            WHERE embedding IS NULL 
            ORDER BY id ASC;
        """)
        return cur.fetchall()


def generar_embeddings_batch(client, textos, reintentos=5):
    """Envía un lote de textos a Gemini con reintentos y backoff ante rate limits (429)."""
    espera = 5
    for intento in range(reintentos):
        try:
            resp = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=textos,
                config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM)
            )
            return [e.values for e in resp.embeddings]
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                print(f"\n[Rate Limit 429] Esperando {espera}s antes de reintentar (intento {intento + 1}/{reintentos})...")
                time.sleep(espera)
                espera *= 2
            else:
                print(f"\n[Error API] {e}")
                time.sleep(3)
    raise RuntimeError(f"No se pudo generar embedding tras {reintentos} intentos.")


def guardar_embeddings_batch(conn, lote_actualizaciones):
    """Guarda en lote los vectores calculados en la base de datos."""
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE articulos SET embedding = %s WHERE id = %s;",
            lote_actualizaciones
        )
    conn.commit()


def main():
    if not GEMINI_API_KEY:
        print("[ERROR] No se encontró GEMINI_API_KEY en el archivo .env")
        return

    print("==========================================================")
    print("      GENERADOR DE EMBEDDINGS COMBINADOS (BACO)           ")
    print(f"  Modelo: {EMBEDDING_MODEL} (Dimensión: {EMBEDDING_DIM})  ")
    print("==========================================================")

    ai_client = genai.Client(api_key=GEMINI_API_KEY)

    with psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME
    ) as conn:
        asegurar_columna_vector(conn)

        pendientes = obtener_articulos_pendientes(conn)
        total = len(pendientes)
        if total == 0:
            print("\n ¡Todos los artículos ya tienen sus embeddings generados! Nada que hacer.")
            return

        print(f"\n Se encontraron {total} artículos pendientes de vectorizar.")
        print(f" Procesando en lotes de {BATCH_SIZE} artículos...\n")

        pbar = tqdm(total=total, desc="Vectorizando", unit="art")

        for i in range(0, total, BATCH_SIZE):
            lote = pendientes[i:i + BATCH_SIZE]
            ids_lote = [row[0] for row in lote]
            textos_lote = [preparar_texto_para_embedding(row[1], row[2]) for row in lote]

            vectores = generar_embeddings_batch(ai_client, textos_lote)

            # Preparar tuplas (vector_str, id)
            actualizaciones = []
            for art_id, vec in zip(ids_lote, vectores):
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                actualizaciones.append((vec_str, art_id))

            guardar_embeddings_batch(conn, actualizaciones)
            pbar.update(len(lote))
            time.sleep(0.2)  # Pausa leve para cuidar la cuota de la API

        pbar.close()

    print("\n==========================================================")
    print(" ¡PROCESO FINALIZADO CON ÉXITO!")
    print(f" Se generaron y guardaron los embeddings para {total} artículos.")
    print("==========================================================")


if __name__ == "__main__":
    main()
