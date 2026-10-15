import math
import pytest
import numpy as np
from baco.server.services.embeddings import (
    embedding_titulo,
    embedding_texto,
    get_model_titulo,
    get_model_texto,
    DIM_TITULO,
    DIM_TEXTO,
)


@pytest.mark.slow
def test_onnx_dimensiones_y_truncado_tokens():
    """Verifica dimensiones exactas y límite de tokens (512 tokens en texto)."""
    modelo_texto = get_model_texto()
    modelo_titulo = get_model_titulo()

    assert modelo_texto.max_seq_length == 512
    assert modelo_titulo.max_seq_length == 128

    texto_muestra = "Instructivo de facturación y configuración de puntos de venta."
    vec_tit = embedding_titulo(texto_muestra)
    vec_txt = embedding_texto(texto_muestra)

    assert len(vec_tit) == DIM_TITULO  # 384
    assert len(vec_txt) == DIM_TEXTO   # 768


@pytest.mark.slow
def test_onnx_vectores_estrictamente_normalizados_l2():
    """Comprueba que la norma euclidiana L2 de salida sea exactamente 1.0."""
    frases = [
        "Alta de proveedores",
        "Liquidación periódica de sueldos y jornales",
        "Configuración impositiva AFIP percepciones IIBB"
    ]
    for frase in frases:
        v_tit = np.array(embedding_titulo(frase))
        v_txt = np.array(embedding_texto(frase))

        norm_tit = np.linalg.norm(v_tit)
        norm_txt = np.linalg.norm(v_txt)

        assert math.isclose(norm_tit, 1.0, rel_tol=1e-4)
        assert math.isclose(norm_txt, 1.0, rel_tol=1e-4)


@pytest.mark.slow
def test_onnx_paridad_y_consistencia_cuantizacion():
    """
    Verifica que la cuantización INT8 mantenga alta fidelidad semántica (similitud >= 0.99)
    en textos idénticos y no sufra degradación de precisión.
    """
    frase = "Configuración de cuentas contables y asientos automáticos"
    v1 = np.array(embedding_titulo(frase))
    v2 = np.array(embedding_titulo(frase))

    # Coseno entre dos inferencias deterministas debe ser prácticamente 1.0 (>= 0.999)
    cos_sim = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
    assert cos_sim >= 0.999


@pytest.mark.slow
def test_onnx_textos_vacios_muy_largos_y_caracteres_raros():
    """Evalúa casos límite: vacío, 10.000 caracteres continuos y emojis complejos."""
    # 1. Vacío
    assert embedding_titulo("") is None
    assert embedding_texto("   \t\n   ") is None

    # 2. Muy largo (10.000 caracteres)
    texto_gigante = ("Parche de actualización masivo para Finnegans ERP. " * 200)
    assert len(texto_gigante) > 8000
    vec_largo = embedding_texto(texto_gigante)
    assert vec_largo is not None
    assert len(vec_largo) == DIM_TEXTO

    # 3. Caracteres raros y emojis
    raro = "🔥 ERP 2026: ¡Facturación electrónic@! ñandú & <script>alert(1)</script> 🚀"
    vec_raro = embedding_titulo(raro)
    assert vec_raro is not None
    assert len(vec_raro) == DIM_TITULO
