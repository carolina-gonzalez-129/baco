import math
import pytest
from baco.server.services.embeddings import (
    embedding_titulo,
    embedding_texto,
    DIM_TITULO,
    DIM_TEXTO,
)


def norma_l2(v):
    return math.sqrt(sum(x * x for x in v))


def test_embedding_titulo_dimension_y_norma_unitaria():
    """Verifica que embedding_titulo genere exactamente DIM_TITULO y su norma L2 sea 1.0."""
    texto = "Instructivo para Facturación y Emisión Electrónica"
    vec = embedding_titulo(texto)
    assert vec is not None
    assert len(vec) == DIM_TITULO
    # Normalización unitaria euclidiana
    norma = norma_l2(vec)
    assert math.isclose(norma, 1.0, rel_tol=1e-4)


def test_embedding_texto_dimension_y_norma_unitaria():
    """Verifica que embedding_texto genere exactamente DIM_TEXTO y su norma L2 sea 1.0."""
    texto = "Este instructivo detalla el proceso para emitir facturas electrónicas vía web service."
    vec = embedding_texto(texto)
    assert vec is not None
    assert len(vec) == DIM_TEXTO
    norma = norma_l2(vec)
    assert math.isclose(norma, 1.0, rel_tol=1e-4)


def test_embedding_robustez_con_emojis_y_caracteres_raros():
    """Comprueba que caracteres Unicode especiales y emojis se procesen limpiamente sin error."""
    texto = "🚀 Guía de inicio rápido: ¡Atención! #Facturación electrónica 2026 ñandú & más..."
    vec_tit = embedding_titulo(texto)
    vec_txt = embedding_texto(texto)
    assert vec_tit is not None and len(vec_tit) == DIM_TITULO
    assert vec_txt is not None and len(vec_txt) == DIM_TEXTO


def test_embedding_textos_vacios_retornan_none():
    """Textos vacíos o solo espacios no deben computar embeddings."""
    assert embedding_titulo("") is None
    assert embedding_titulo("   \n\t  ") is None
    assert embedding_texto("") is None
    assert embedding_texto("     ") is None
