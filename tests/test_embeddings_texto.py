import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from baco.server.services.embeddings import (
    limpiar_suave,
    truncar_1000,
    embedding_texto,
    FUNCIONES_LIMPIEZA_SUAVE,
    MODEL_TEXTO_NAME,
    DIM_TEXTO,
)


def test_limpiar_suave_elimina_restos_imagenes_discourse():
    texto = (
        "Consulta:\n"
        "Al intentar obtener COE aparece un aviso de error.\n"
        "image\n"
        "950×752 52.9 KB\n"
        "Respuesta:\n"
        "Esto sucede porque en la transacción hay un error.\n"
        "screenshot.png|565x89.63413579357058\n"
        "image\n"
        "1016×746 80.9 KB\n"
        "Luego se puede volver a intentar."
    )
    resultado = limpiar_suave(texto)

    # Verifica que no contenga los patrones de imágenes
    assert "950×752 52.9 KB" not in resultado
    assert "1016×746 80.9 KB" not in resultado
    assert "|565x89.63413579357058" not in resultado
    assert "image" not in resultado.lower().split()  # No debe haber palabra 'image' aislada

    # Verifica que el contenido textual de valor se mantenga
    assert "Al intentar obtener COE aparece un aviso de error." in resultado
    assert "Luego se puede volver a intentar." in resultado


def test_limpiar_suave_no_modifica_mayusculas_tildes_ni_puntuacion():
    texto_original = "¡ERROR CRÍTICO! ¿Está configurada la 'Dirección' del Año Fiscal (2026) en CABA: Sección 4?"
    resultado = limpiar_suave(texto_original)

    # Mayúsculas conservadas
    assert "ERROR CRÍTICO" in resultado
    assert "CABA" in resultado

    # Tildes y signos conservados
    assert "Dirección" in resultado
    assert "Año" in resultado
    assert "¡" in resultado and "!" in resultado
    assert "¿" in resultado and "?" in resultado
    assert ":" in resultado and "'" in resultado


def test_limpiar_suave_colapsa_espacios_repetidos():
    texto = "Este   es   un    texto\n\n\ncon múltiples     saltos\t\ty   espacios."
    resultado = limpiar_suave(texto)
    assert resultado == "Este es un texto con múltiples saltos y espacios."


def test_limpiar_suave_lista_funciones_extensible():
    # Verifica que FUNCIONES_LIMPIEZA_SUAVE sea una lista de funciones
    assert isinstance(FUNCIONES_LIMPIEZA_SUAVE, list)
    assert len(FUNCIONES_LIMPIEZA_SUAVE) >= 4
    for fn in FUNCIONES_LIMPIEZA_SUAVE:
        assert callable(fn)


def test_truncar_1000_textos_cortos_no_se_alteran():
    texto = "Texto corto menor a mil caracteres."
    assert truncar_1000(texto) == texto
    assert truncar_1000(None) == ""
    assert truncar_1000("") == ""


def test_truncar_1000_no_deja_palabras_partidas():
    # Creamos un texto largo con palabras bien definidas
    palabras = ["palabra" + str(i) for i in range(250)]
    texto_largo = " ".join(palabras)
    assert len(texto_largo) > 1000

    truncado = truncar_1000(texto_largo)
    assert len(truncado) <= 1000

    # No debe terminar con una palabra incompleta
    ultima_palabra = truncado.split()[-1]
    assert ultima_palabra in palabras


def test_truncar_1000_limite_personalizado_y_espacio_exacto():
    # Prueba con límite pequeño para validar bordes
    texto = "uno dos tres cuatro cinco"
    # Límite 7: "uno dos" tiene longitud 7
    assert truncar_1000(texto, limite=7) == "uno dos"
    # Límite 10: "uno dos tr" cortaría en "tr", debe cortar en "dos"
    assert truncar_1000(texto, limite=10) == "uno dos"


def test_truncar_1000_cadena_sin_espacios():
    # Si hay una cadena sin espacios que supera el límite, debe recortar al límite
    cadena_continua = "x" * 1200
    truncado = truncar_1000(cadena_continua, limite=1000)
    assert len(truncado) == 1000
    assert truncado == "x" * 1000


def test_embedding_texto_unitario_y_normalizado():
    texto = "Este es un artículo técnico sobre conciliación bancaria y facturación electrónica."
    emb = embedding_texto(texto)

    assert emb is not None
    assert isinstance(emb, list)
    assert len(emb) == DIM_TEXTO
    assert len(emb) == 768

    # Verificar que el embedding esté normalizado (norma L2 == 1.0)
    norma_cuadrada = sum(x * x for x in emb)
    assert math.isclose(norma_cuadrada, 1.0, rel_tol=1e-4)


def test_embedding_texto_vacio_devuelve_none():
    assert embedding_texto(None) is None
    assert embedding_texto("") is None
    assert embedding_texto("     ") is None
    assert embedding_texto("image\n548×368 22.5 KB") is None  # Tras limpiar suave queda vacío


def test_embedding_texto_batch():
    textos = [
        "Primer artículo sobre configuración de impuestos y percepciones.",
        "Segundo artículo sobre asientos contables automáticos.",
        "",  # Debe dar None para esta posición
    ]
    embs = embedding_texto(textos)

    assert isinstance(embs, list)
    assert len(embs) == 3
    assert len(embs[0]) == 768
    assert len(embs[1]) == 768
    assert embs[2] is None

    norma_0 = sum(x * x for x in embs[0])
    norma_1 = sum(x * x for x in embs[1])
    assert math.isclose(norma_0, 1.0, rel_tol=1e-4)
    assert math.isclose(norma_1, 1.0, rel_tol=1e-4)
