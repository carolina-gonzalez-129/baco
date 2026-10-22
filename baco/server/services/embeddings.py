from __future__ import annotations

import os
import logging
import re
from functools import lru_cache
from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

ONNX_INTRA_OP_THREADS = int(os.getenv("ONNX_INTRA_OP_THREADS", "2"))

def _crear_session_options():
    if ONNX_INTRA_OP_THREADS > 0:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = ONNX_INTRA_OP_THREADS
        opts.inter_op_num_threads = 1
        return opts
    return None


MODEL_TITULO_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
DIM_TITULO = 384
_MODEL_TITULO_INSTANCE: SentenceTransformer | None = None

MODEL_TEXTO_NAME = "intfloat/multilingual-e5-base"
DIM_TEXTO = 768
PREFIJO_E5_TEXTO = "query: "
MAX_CARACTERES_TEXTO = 1000

_MODEL_TEXTO_INSTANCE: SentenceTransformer | None = None

CACHE_EMBEDDINGS_SIZE = 1024
@lru_cache(maxsize=CACHE_EMBEDDINGS_SIZE)
def _encode_titulo_cached(titulo_normalizado: str) -> tuple[float, ...]:
    sentence_model = get_model_titulo()
    vector = sentence_model.encode(
        titulo_normalizado,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return tuple(vector.tolist())


@lru_cache(maxsize=CACHE_EMBEDDINGS_SIZE)
def _encode_texto_cached(texto_con_prefijo: str) -> tuple[float, ...]:
    sentence_model = get_model_texto()
    vector = sentence_model.encode(
        texto_con_prefijo,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return tuple(vector.tolist())


def info_cache_embeddings() -> dict:
    return {
        "titulo": _encode_titulo_cached.cache_info()._asdict(),
        "texto": _encode_texto_cached.cache_info()._asdict(),
    }


def get_model_titulo() -> SentenceTransformer:
    """Retorna la instancia única (singleton) del modelo SentenceTransformer para títulos con aceleración ONNX INT8."""
    global _MODEL_TITULO_INSTANCE
    if _MODEL_TITULO_INSTANCE is None:
        from sentence_transformers import SentenceTransformer

        logger.info(f"Cargando modelo de embeddings de título ONNX INT8: {MODEL_TITULO_NAME} (intra_threads={ONNX_INTRA_OP_THREADS})...")
        kwargs = {"file_name": "onnx/model_quint8_avx2.onnx"}
        opts = _crear_session_options()
        if opts is not None:
            kwargs["session_options"] = opts

        _MODEL_TITULO_INSTANCE = SentenceTransformer(
            MODEL_TITULO_NAME,
            backend="onnx",
            model_kwargs=kwargs,
        )
    return _MODEL_TITULO_INSTANCE


def get_model_texto() -> SentenceTransformer:
    """Retorna la instancia única (singleton) del modelo SentenceTransformer para texto con aceleración ONNX INT8."""
    global _MODEL_TEXTO_INSTANCE
    if _MODEL_TEXTO_INSTANCE is None:
        from sentence_transformers import SentenceTransformer

        logger.info(f"Cargando modelo de embeddings de texto ONNX INT8: {MODEL_TEXTO_NAME} (intra_threads={ONNX_INTRA_OP_THREADS})...")
        kwargs = {"file_name": "onnx/model_qint8_avx512_vnni.onnx"}
        opts = _crear_session_options()
        if opts is not None:
            kwargs["session_options"] = opts

        _MODEL_TEXTO_INSTANCE = SentenceTransformer(
            MODEL_TEXTO_NAME,
            backend="onnx",
            model_kwargs=kwargs,
        )
    return _MODEL_TEXTO_INSTANCE


def limpiar_html_bs4(texto: str) -> str:
    """Extrae texto plano eliminando etiquetas HTML con BeautifulSoup si existen."""
    if not texto:
        return ""
    if "<" in texto and ">" in texto:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(texto, "html.parser")
        lineas = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
        return " ".join(lineas)
    return texto


def eliminar_lineas_image(texto: str) -> str:
    """Elimina líneas que dicen solo 'image' (regex multilínea ^image$, insensible a mayúsculas)."""
    return re.sub(r"(?mi)^\s*image\s*$", " ", texto)


def eliminar_dimensiones_peso_discourse(texto: str) -> str:
    """Elimina restos de imágenes tipo '548×368 22.5 KB' de Discourse."""
    return re.sub(r"\d+[×x]\d+\s+[\d.]+\s*[KM]B", " ", texto, flags=re.IGNORECASE)


def eliminar_pipes_dimensiones_discourse(texto: str) -> str:
    """Elimina restos de dimensiones de subida tipo '|565x89.63413579357058' de Discourse."""
    return re.sub(r"\|\d+(?:\.\d+)?[x×]\d+(?:\.\d+)?", " ", texto, flags=re.IGNORECASE)


def eliminar_headers_markdown_y_plantillas(texto: str) -> str:
    """Elimina headers Markdown, etiquetas de sección y divisores de plantilla."""
    if not texto:
        return ""
    # Headers markdown (#, ##, ###)
    texto = re.sub(r"(?m)^\s*#{1,6}\s+.*$", " ", texto)
    # Secciones con negrita o texto plano
    texto = re.sub(
        r"(?mi)^\s*(\*\*)?(consulta|respuesta|pasos a seguir|requiere app\s*builder|antes de empezar|modo de uso|¿?para qu[eé] sirve\??)(\*\*)?\s*:?\s*$",
        " ", texto
    )
    # Divisores de sección (* * *, ---, ___)
    texto = re.sub(r"(?m)^\s*(\*\s*\*\s*\*|-{3,}|_{3,})\s*$", " ", texto)
    # Enlaces de imágenes Markdown
    texto = re.sub(r"!?\[image[^]]*]\([^)]+\)", " ", texto, flags=re.IGNORECASE)
    return texto


def colapsar_espacios(texto: str) -> str:
    """Colapsa espacios en blanco repetidos (espacios, saltos de línea, tabs) en un solo espacio."""
    return re.sub(r"\s+", " ", texto).strip()


# Lista ordenada de funciones de limpieza suave.
FUNCIONES_LIMPIEZA_SUAVE: list[Callable[[str], str]] = [
    eliminar_headers_markdown_y_plantillas,
    limpiar_html_bs4,
    eliminar_lineas_image,
    eliminar_dimensiones_peso_discourse,
    eliminar_pipes_dimensiones_discourse,
    colapsar_espacios,
]


def limpiar_suave(texto: str | None) -> str:
    """Limpia suavemente el texto eliminando residuos de Discourse y normalizando espacios.

    Reglas:
    - Elimina restos de imágenes de Discourse.
    - NO pasa a minúsculas.
    - NO elimina tildes, signos de puntuación ni caracteres especiales.
    - Colapsa espacios en blanco repetidos.
    - Ejecuta en orden secuencial cada función registrada en FUNCIONES_LIMPIEZA_SUAVE.
    """
    if not texto:
        return ""
    resultado = texto
    for funcion in FUNCIONES_LIMPIEZA_SUAVE:
        resultado = funcion(resultado)
    return resultado


def truncar_1000(texto: str | None, limite: int = MAX_CARACTERES_TEXTO) -> str:
    """Corta el texto a 1000 caracteres como máximo (o el límite indicado).

    Prioriza cortar en el último espacio en blanco antes del límite para no dejar
    palabras partidas. Si no hay espacios antes del límite (ej. token largo continuo),
    corta rígidamente al límite establecido.
    """
    if not texto or len(texto) <= limite:
        return texto or ""

    if texto[limite] == " ":
        return texto[:limite].rstrip()

    candidato = texto[:limite]
    ultimo_espacio = candidato.rfind(" ")
    if ultimo_espacio > 0:
        return candidato[:ultimo_espacio].rstrip()

    return candidato.rstrip()


def embedding_titulo(
        titulo_original: str | Sequence[str] | None,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        model: SentenceTransformer | None = None,
) -> list[float] | list[list[float] | None] | None:

    if titulo_original is None:
        return None

    sentence_model = model or get_model_titulo()

    if isinstance(titulo_original, str):
        titulo_limpio = colapsar_espacios(titulo_original)
        if not titulo_limpio:
            return None
        return list(_encode_titulo_cached(titulo_limpio))


    titulos_a_codificar: list[str] = []
    indices_a_codificar: list[int] = []

    for idx, tit in enumerate(titulo_original):
        if tit is None or not tit.strip():
            continue
        limpio = colapsar_espacios(tit)
        if not limpio:
            continue
        titulos_a_codificar.append(limpio)
        indices_a_codificar.append(idx)

    if not titulos_a_codificar:
        return [None] * len(titulo_original)

    vectores = sentence_model.encode(
        titulos_a_codificar,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=show_progress_bar,
    )

    resultados: list[list[float] | None] = [None] * len(titulo_original)
    for pos_vector, idx_original in enumerate(indices_a_codificar):
        resultados[idx_original] = vectores[pos_vector].tolist()

    return resultados


def contar_tokens_texto(texto: str | None) -> int:
    """Retorna la cantidad exacta de tokens del texto usando el tokenizer del modelo de texto."""
    if not texto:
        return 0
    sentence_model = get_model_texto()
    if hasattr(sentence_model, "tokenizer") and sentence_model.tokenizer:
        texto_limpio = limpiar_suave(texto)
        texto_truncado = truncar_1000(texto_limpio)
        texto_con_prefijo = f"{PREFIJO_E5_TEXTO}{texto_truncado}"
        return len(sentence_model.tokenizer.encode(texto_con_prefijo))
    return len(texto.split())


# ===========================================================================
# 4. Punto de entrada único: embedding_texto
# ===========================================================================

def embedding_texto(
        texto_original: str | Sequence[str] | None,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        model: SentenceTransformer | None = None,
) -> list[float] | list[list[float] | None] | None:

    if texto_original is None:
        return None

    sentence_model = model or get_model_texto()

    # Caso 1: Un solo texto (artículo entrante o unitario)
    if isinstance(texto_original, str):
        if not texto_original.strip():
            return None

        texto_limpio = limpiar_suave(texto_original)
        if not texto_limpio:
            return None

        texto_truncado = truncar_1000(texto_limpio)
        if not texto_truncado:
            return None

        texto_con_prefijo = f"{PREFIJO_E5_TEXTO}{texto_truncado}"
        return list(_encode_texto_cached(texto_con_prefijo))

    textos_a_codificar: list[str] = []
    indices_a_codificar: list[int] = []

    for idx, txt in enumerate(texto_original):
        if txt is None or not txt.strip():
            continue

        limpio = limpiar_suave(txt)
        if not limpio:
            continue

        truncado = truncar_1000(limpio)
        if not truncado:
            continue

        textos_a_codificar.append(f"{PREFIJO_E5_TEXTO}{truncado}")
        indices_a_codificar.append(idx)

    if not textos_a_codificar:
        return [None] * len(texto_original)

    vectores = sentence_model.encode(
        textos_a_codificar,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=show_progress_bar,
    )

    resultados: list[list[float] | None] = [None] * len(texto_original)
    for pos_vector, idx_original in enumerate(indices_a_codificar):
        resultados[idx_original] = vectores[pos_vector].tolist()

    return resultados