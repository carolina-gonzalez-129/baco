import logging
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


from baco.server.db.config import get_conn

from baco.server.services.embeddings import (
    embedding_titulo,
    embedding_texto,
    get_model_titulo,
    get_model_texto,
    MODEL_TITULO_NAME,
    DIM_TITULO,
    MODEL_TEXTO_NAME,
    DIM_TEXTO,
)

MAX_SEQ_LENGTH_TEXTO = 512

BATCH_SIZE = 8




def validar_contra_meta(conn, columna: str, model, expected_model_name: str, expected_dim: int):
    """Valida que el modelo cargado y su dimensión coincidan estrictamente con embeddings_meta.

    Si el registro no existe o los valores difieren, aborta con ValueError.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT model_name, dimension FROM embeddings_meta WHERE columna = %s;",
            (columna,)
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(
                f"[ERROR DE VALIDACIÓN] No existe registro en 'embeddings_meta' para la columna '{columna}'."
            )
        db_model, db_dim = row
        if db_model != expected_model_name:
            raise ValueError(
                f"[ERROR DE VALIDACIÓN] Columna '{columna}': modelo en base de datos ('{db_model}') "
                f"difiere del modelo esperado ('{expected_model_name}')."
            )
        if db_dim != expected_dim:
            raise ValueError(
                f"[ERROR DE VALIDACIÓN] Columna '{columna}': dimensión configurada ({db_dim}) "
                f"difiere de la esperada ({expected_dim})."
            )

        real_dim = model.get_sentence_embedding_dimension()
        if real_dim != expected_dim:
            raise ValueError(
                f"[ERROR DE VALIDACIÓN] Columna '{columna}': la dimensión generada por el modelo ({real_dim}) "
                f"no coincide con la dimensión esperada ({expected_dim})."
            )

    logger.info(f"Validación exitosa contra embeddings_meta para '{columna}': {expected_model_name} (dim: {expected_dim})")


def obtener_articulos_pendientes(conn):
    """Obtiene artículos que requieran generar embedding de título o de texto.

    Filtra con precisión: solo aquellos donde el embedding sea NULL pero el contenido
    tenga hash válido (no vacío ni nulo). De este modo se evita re-procesar artículos vacíos.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, titulo, texto_sin_headers, hash_titulo, hash_texto, embedding_titulo, embedding_texto 
            FROM articulos 
            WHERE (embedding_titulo IS NULL AND hash_titulo IS NOT NULL)
               OR (embedding_texto IS NULL AND hash_texto IS NOT NULL)
            ORDER BY id;
        """)
        return cur.fetchall()


def medir_articulos_truncados(articulos, tokenizer, max_seq_length: int = MAX_SEQ_LENGTH_TEXTO) -> int:
    """Mide e imprime cuántos artículos pendientes de texto superan la ventana de 512 tokens."""
    textos_a_evaluar = []
    for row in articulos:
        _id, _tit, txt_orig, _htit, htxt, _etit, etxt = row
        if etxt is None and htxt is not None and txt_orig and txt_orig.strip():
            textos_a_evaluar.append(f"passage: {txt_orig}")

    total_textos = len(textos_a_evaluar)
    if total_textos == 0:
        logger.info("[INFO TOKENS] No hay artículos de texto pendientes para evaluar tokens.")
        return 0

    truncados = 0
    # Evaluamos longitudes en lotes usando el tokenizer de HuggingFace
    batch_size_eval = 256
    for b in range(0, total_textos, batch_size_eval):
        lote = textos_a_evaluar[b:b + batch_size_eval]
        encoded = tokenizer(lote, truncation=False, padding=False)["input_ids"]
        for tokens in encoded:
            if len(tokens) > max_seq_length:
                truncados += 1

    pct = (truncados / total_textos) * 100
    print(f"\n[INFO TOKENS] De {total_textos} artículos de texto a procesar con multilingual-e5-base:")
    print(f"  -> {truncados} artículos ({pct:.2f}%) superan la ventana de {max_seq_length} tokens y serán truncados al inicio.")
    print(f"  -> {total_textos - truncados} artículos ({100 - pct:.2f}%) entran completos dentro del contexto.\n")
    return truncados


def generar_embeddings():
    print("==========================================================")
    print("      GENERACIÓN DE EMBEDDINGS LOCALES (sentence-transformers) ")
    print(f"  Título: {MODEL_TITULO_NAME} ({DIM_TITULO} dim)")
    print(f"  Texto:  {MODEL_TEXTO_NAME} ({DIM_TEXTO} dim, max_seq: {MAX_SEQ_LENGTH_TEXTO})")
    print("==========================================================")

    with get_conn() as conn:
        # 1. Consultar pendientes
        pendientes = obtener_articulos_pendientes(conn)
        total = len(pendientes)
        if total == 0:
            print("\n ¡Todos los artículos ya tienen sus embeddings completos! Nada que hacer.")
            return

        print(f"\n Se encontraron {total} artículos con embeddings pendientes.")

        # Identificar si hay pendientes para cada columna
        hay_pendientes_titulo = any(r[5] is None and r[3] is not None for r in pendientes)
        hay_pendientes_texto = any(r[6] is None and r[4] is not None for r in pendientes)

        # 2. Cargar y validar modelo de título si se necesita
        model_titulo = None
        if hay_pendientes_titulo:
            print(f" Cargando modelo para títulos: {MODEL_TITULO_NAME}...")
            model_titulo = get_model_titulo()
            validar_contra_meta(conn, "titulo", model_titulo, MODEL_TITULO_NAME, DIM_TITULO)
        else:
            print(" Embeddings de título: todos completos (no se requiere cargar MiniLM).")

        # 3. Cargar y validar modelo de texto si se necesita
        model_texto = None
        if hay_pendientes_texto:
            print(f" Cargando modelo para textos: {MODEL_TEXTO_NAME}...")
            model_texto = get_model_texto()
            model_texto.max_seq_length = MAX_SEQ_LENGTH_TEXTO
            validar_contra_meta(conn, "texto", model_texto, MODEL_TEXTO_NAME, DIM_TEXTO)

            # 4. Medir e informar tokens antes de procesar
            medir_articulos_truncados(pendientes, model_texto.tokenizer, MAX_SEQ_LENGTH_TEXTO)
        else:
            print(" Embeddings de texto: todos completos (no se requiere cargar e5).")

        print(f" Procesando en lotes de {BATCH_SIZE} artículos con commits parciales...\n")
        pbar = tqdm(total=total, desc="Generando embeddings")

        for i in range(0, total, BATCH_SIZE):
            lote = pendientes[i:i + BATCH_SIZE]

            titulos_a_calcular = []
            textos_a_calcular = []
            info_lote = []

            for row in lote:
                art_id, tit_orig, txt_orig, hash_tit, hash_txt, emb_tit, emb_txt = row

                necesita_tit = (emb_tit is None) and (hash_tit is not None)
                necesita_txt = (emb_txt is None) and (hash_txt is not None)

                # Seguridad: no usar placeholders si el texto original es nulo/vacío
                if necesita_tit and not (tit_orig and tit_orig.strip()):
                    logger.warning(f"Artículo ID {art_id}: título vacío sin placeholder, se conserva embedding_titulo = NULL")
                    necesita_tit = False

                if necesita_txt and not (txt_orig and txt_orig.strip()):
                    logger.warning(f"Artículo ID {art_id}: texto vacío sin placeholder, se conserva embedding_texto = NULL")
                    necesita_txt = False

                tit_idx = len(titulos_a_calcular) if necesita_tit else None
                if necesita_tit:
                    # Título: texto original sin prefijo
                    titulos_a_calcular.append(tit_orig)

                txt_idx = len(textos_a_calcular) if necesita_txt else None
                if necesita_txt:
                    # Texto original sin normalizar ni hashear; embedding_texto aplicará limpiar_suave, truncar_1000 y prefijo query:
                    textos_a_calcular.append(txt_orig)

                info_lote.append({
                    "id": art_id,
                    "necesita_tit": necesita_tit,
                    "necesita_txt": necesita_txt,
                    "tit_idx": tit_idx,
                    "txt_idx": txt_idx,
                })

            # Generar vectores normalizados
            vectores_tit = (
                embedding_titulo(titulos_a_calcular, model=model_titulo)
                if (titulos_a_calcular and model_titulo) else []
            )
            # embedding_texto es el punto único de entrada para embeddings de texto
            vectores_txt = (
                embedding_texto(textos_a_calcular, model=model_texto)
                if (textos_a_calcular and model_texto) else []
            )

            # Escribir en base de datos
            with conn.cursor() as cur:
                for item in info_lote:
                    vec_tit_str = (
                        "[" + ",".join(str(f) for f in vectores_tit[item["tit_idx"]]) + "]"
                        if item["necesita_tit"] else None
                    )
                    vec_txt_str = (
                        "[" + ",".join(str(f) for f in vectores_txt[item["txt_idx"]]) + "]"
                        if (item["necesita_txt"] and vectores_txt and vectores_txt[item["txt_idx"]] is not None) else None
                    )

                    if vec_tit_str is not None and vec_txt_str is not None:
                        cur.execute("""
                            UPDATE articulos 
                            SET embedding_titulo = %s,
                                embedding_texto = %s
                            WHERE id = %s;
                        """, (vec_tit_str, vec_txt_str, item["id"]))
                    elif vec_tit_str is not None:
                        cur.execute("""
                            UPDATE articulos 
                            SET embedding_titulo = %s
                            WHERE id = %s;
                        """, (vec_tit_str, item["id"]))
                    elif vec_txt_str is not None:
                        cur.execute("""
                            UPDATE articulos 
                            SET embedding_texto = %s
                            WHERE id = %s;
                        """, (vec_txt_str, item["id"]))

            conn.commit()
            pbar.update(len(lote))

        pbar.close()

    print("\n==========================================================")
    print(" ¡PROCESO DE EMBEDDINGS FINALIZADO EXITOSAMENTE!")
    print(f" Se calcularon y almacenaron los vectores para {total} artículos.")
    print("==========================================================")


if __name__ == "__main__":
    generar_embeddings()
