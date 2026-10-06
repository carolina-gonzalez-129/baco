"""
Módulo de servicios de embeddings para BACO.

PUNTO DE ENTRADA ÚNICO OFICIAL para generar embeddings de TÍTULO y de TEXTO en BACO,
tanto para los artículos indexados en la base de datos (PostgreSQL / baco_db)
como para los artículos entrantes en la búsqueda de duplicados.

Configuración de Modelos:
- TÍTULO: 'paraphrase-multilingual-MiniLM-L12-v2' (Dimensión: 384)
- TEXTO:  'intfloat/multilingual-e5-base' (Dimensión: 768, prefijo: 'query: ')
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Configuración del modelo oficial para embeddings de título
MODEL_TITULO_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
DIM_TITULO = 384
_MODEL_TITULO_INSTANCE: SentenceTransformer | None = None

# Configuración del modelo oficial para embeddings de texto
MODEL_TEXTO_NAME = "intfloat/multilingual-e5-base"
DIM_TEXTO = 768
PREFIJO_E5_TEXTO = "query: "
MAX_CARACTERES_TEXTO = 1000

# Instancia singleton del modelo para evitar recargas costosas
_MODEL_TEXTO_INSTANCE: SentenceTransformer | None = None


def get_model_titulo() -> SentenceTransformer:
    """Retorna la instancia única (singleton) del modelo SentenceTransformer para títulos."""
    global _MODEL_TITULO_INSTANCE
    if _MODEL_TITULO_INSTANCE is None:
        import torch
        from sentence_transformers import SentenceTransformer

        logger.info(f"Cargando modelo de embeddings de título: {MODEL_TITULO_NAME}...")
        if not torch.cuda.is_available():
            torch.set_num_threads(min(4, torch.get_num_threads()))
        _MODEL_TITULO_INSTANCE = SentenceTransformer(MODEL_TITULO_NAME)
    return _MODEL_TITULO_INSTANCE


def get_model_texto() -> SentenceTransformer:
    """Retorna la instancia única (singleton) del modelo SentenceTransformer para texto."""
    global _MODEL_TEXTO_INSTANCE
    if _MODEL_TEXTO_INSTANCE is None:
        import torch
        from sentence_transformers import SentenceTransformer

        logger.info(f"Cargando modelo de embeddings de texto: {MODEL_TEXTO_NAME}...")
        # Optimizar uso de hilos en CPU
        if not torch.cuda.is_available():
            torch.set_num_threads(min(4, torch.get_num_threads()))
        _MODEL_TEXTO_INSTANCE = SentenceTransformer(MODEL_TEXTO_NAME)
    return _MODEL_TEXTO_INSTANCE


# ===========================================================================
# 1. Pipeline de funciones de limpieza suave (extensible)
# ===========================================================================

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
        r"(?mi)^\s*(\*\*)?(consulta|respuesta|soluci[oó]n|error|pasos a seguir|requiere app\s*builder|antes de empezar|modo de uso|¿?para qu[eé] sirve\??)(\*\*)?\s*:?\s*$",
        " ", texto
    )
    # Divisores de sección (* * *, ---, ___)
    texto = re.sub(r"(?m)^\s*(\*\s*\*\s*\*|-{3,}|_{3,})\s*$", " ", texto)
    # Enlaces de imágenes Markdown
    texto = re.sub(r"!?\[image[^\]]*\]\([^\)]+\)", " ", texto, flags=re.IGNORECASE)
    return texto


def colapsar_espacios(texto: str) -> str:
    """Colapsa espacios en blanco repetidos (espacios, saltos de línea, tabs) en un solo espacio."""
    return re.sub(r"\s+", " ", texto).strip()


# Lista ordenada de funciones de limpieza suave.
FUNCIONES_LIMPIEZA_SUAVE: list[Callable[[str], str]] = [
    limpiar_html_bs4,
    eliminar_headers_markdown_y_plantillas,
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


# ===========================================================================
# 2. Función de truncado inteligente
# ===========================================================================

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


# ===========================================================================
# 3. Punto de entrada único: embedding_titulo
# ===========================================================================

def embedding_titulo(
        titulo_original: str | Sequence[str] | None,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        model: SentenceTransformer | None = None,
) -> list[float] | list[list[float] | None] | None:
    """PUNTO DE ENTRADA ÚNICO para generar embeddings del campo TÍTULO en BACO.

    Aplica el pipeline oficial:
      1. Preserva el título original (con mayúsculas, tildes y signos).
      2. Colapsa espacios redundantes.
      3. Genera el embedding usando el modelo paraphrase-multilingual-MiniLM-L12-v2
         con normalize_embeddings=True (norma L2 = 1.0).

    Retorna:
        - Si titulo_original es str: list[float] con 384 flotantes normalizados.
          Si está vacío o es None, devuelve None.
        - Si titulo_original es Sequence[str]: list[list[float] | None] con un vector
          por cada elemento (o None si ese elemento estaba vacío).
        - Si titulo_original es None: None.
    """
    if titulo_original is None:
        return None

    sentence_model = model or get_model_titulo()

    # Caso 1: Un solo título (artículo entrante o unitario)
    if isinstance(titulo_original, str):
        titulo_limpio = colapsar_espacios(titulo_original)
        if not titulo_limpio:
            return None

        vector = sentence_model.encode(
            titulo_limpio,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vector.tolist()

    # Caso 2: Procesamiento por lote (batch)
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


# ===========================================================================
# 4. Punto de entrada único: embedding_texto
# ===========================================================================

def embedding_texto(
        texto_original: str | Sequence[str] | None,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        model: SentenceTransformer | None = None,
) -> list[float] | list[list[float] | None] | None:
    """PUNTO DE ENTRADA ÚNICO para generar embeddings del campo TEXTO en BACO.

    Aplica el pipeline oficial:
      1. limpiar_suave(texto_original): elimina residuos de Discourse y colapsa espacios.
         Preserva mayúsculas, tildes y puntuación.
      2. truncar_1000(texto_limpio): corta a un máximo de 1000 caracteres sin partir palabras.
      3. Antepone el prefijo oficial del modelo E5: 'query: '.
      4. Genera el embedding usando el modelo intfloat/multilingual-e5-base con normalize_embeddings=True.

    Retorna:
        - Si texto_original es str: list[float] con 768 flotantes normalizados (norma L2 = 1.0).
          Si el texto resultante es vacío o None, devuelve None.
        - Si texto_original es Sequence[str]: list[list[float] | None] con un vector por cada
          elemento de entrada (o None si ese elemento estaba vacío).
        - Si texto_original es None: None.
    """
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
        vector = sentence_model.encode(
            texto_con_prefijo,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vector.tolist()

    # Caso 2: Procesamiento por lote (para migración masiva o múltiples artículos)
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