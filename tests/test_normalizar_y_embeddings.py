import importlib.util
import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from baco.server.db.config import get_conn

# Cargar generar_embeddings.py directamente
p_emb = PROJECT_ROOT / "baco" / "server" / "db" / "generar_embeddings.py"
spec_emb = importlib.util.spec_from_file_location("generar_embeddings_mod", p_emb)
emb_mod = importlib.util.module_from_spec(spec_emb)
spec_emb.loader.exec_module(emb_mod)
validar_contra_meta = emb_mod.validar_contra_meta
medir_articulos_truncados = emb_mod.medir_articulos_truncados
MODEL_TITULO_NAME = emb_mod.MODEL_TITULO_NAME
DIM_TITULO = emb_mod.DIM_TITULO
MODEL_TEXTO_NAME = emb_mod.MODEL_TEXTO_NAME
DIM_TEXTO = emb_mod.DIM_TEXTO
MAX_SEQ_LENGTH_TEXTO = emb_mod.MAX_SEQ_LENGTH_TEXTO


# ==============================================================================
# 1. Tests de Normalización y Hashing delegados en PostgreSQL (normalizar_texto)
# ==============================================================================

def test_hash_equivalencia_tildes_enie_mayusculas_espacios():
    """Tildes, ñ, mayúsculas y espacios de más deben producir exactamente el mismo hash en PostgreSQL."""
    variantes = [
        "Configuración del Año Fiscal en CABA",
        "configuracion del ano fiscal en caba",
        "  CONFIGURACIÓN   DEL   AÑO   FISCAL   EN   CABA  ",
        "Configuracion del Ano Fiscal en CABA",
        "configuración del año fiscal en caba\n\t",
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT array_agg(md5(normalizar_texto(v))) FROM unnest(%s::text[]) as v;", (variantes,))
            hashes = cur.fetchone()[0]

    assert all(h is not None and len(h) == 32 for h in hashes)
    assert len(set(hashes)) == 1


def test_hash_vacios_espacios_puntuacion_retorna_none():
    """Título vacío, solo espacios o solo puntuación dan None, sin falsos duplicados en PostgreSQL."""
    casos_vacios = [
        None,
        "",
        "   ",
        "\t\n  \r",
        ".,;:¡!¿?()-_—'\"[]{}/\\",
        "   ... --- !!! ???   ",
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            for caso in casos_vacios:
                cur.execute("SELECT normalizar_texto(%s);", (caso,))
                resultado = cur.fetchone()[0]
                assert resultado is None, f"Se esperaba None para '{caso}', pero se obtuvo {resultado}"


def test_normalizar_es_idempotente():
    """normalizar_texto(normalizar_texto(x)) == normalizar_texto(x) en PostgreSQL."""
    textos_prueba = [
        "¿Cómo configurar el Motor de Retenciones de IIBB (Versión 2026)?",
        "LH - Liquidación de Haberes: Fórmulas y Códigos de Descuento",
        "Wazuh no genera reportes - Limpiar índices en Elasticsearch",
        "¡¡¡Atención!!! Caracteres especiales: #$%&*+<=>@^`|~",
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            for txt in textos_prueba:
                cur.execute("SELECT normalizar_texto(%s), normalizar_texto(normalizar_texto(%s));", (txt, txt))
                una_vez, dos_veces = cur.fetchone()
                assert una_vez == dos_veces


def test_rellenado_persiste_exactamente_el_hash():
    """La función normalizar_texto y md5() en PostgreSQL generan un hash de 32 chars idéntico al estándar."""
    titulo = "Factura de Crédito Electrónica MiPyME (FCE)"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT normalizar_texto(%s), md5(normalizar_texto(%s));", (titulo, titulo))
            norm_db, hash_db = cur.fetchone()

    assert norm_db == "factura de credito electronica mipyme fce"
    assert hash_db is not None
    assert len(hash_db) == 32


# ==============================================================================
# 2. Tests de Embeddings y Metadatos
# ==============================================================================

def test_dimensiones_y_nombres_modelos_configurados():
    """embedding_titulo debe ser MiniLM (384) y embedding_texto debe ser e5-base (768)."""
    assert MODEL_TITULO_NAME == "paraphrase-multilingual-MiniLM-L12-v2"
    assert DIM_TITULO == 384
    assert MODEL_TEXTO_NAME == "intfloat/multilingual-e5-base"
    assert DIM_TEXTO == 768
    assert MAX_SEQ_LENGTH_TEXTO == 512


def test_embeddings_validacion_contra_meta_exitosa():
    """Validación exitosa cuando modelo, dimensión de BD y dimensión del modelo coinciden."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # Columna titulo
    mock_model_titulo = MagicMock()
    mock_model_titulo.get_sentence_embedding_dimension.return_value = 384
    mock_cursor.fetchone.return_value = (MODEL_TITULO_NAME, 384)
    validar_contra_meta(mock_conn, "titulo", mock_model_titulo, MODEL_TITULO_NAME, DIM_TITULO)

    # Columna texto
    mock_model_texto = MagicMock()
    mock_model_texto.get_sentence_embedding_dimension.return_value = 768
    mock_cursor.fetchone.return_value = (MODEL_TEXTO_NAME, 768)
    validar_contra_meta(mock_conn, "texto", mock_model_texto, MODEL_TEXTO_NAME, DIM_TEXTO)


def test_embeddings_validacion_falla_si_falta_registro_en_meta():
    """Si una columna no está en embeddings_meta, debe lanzar ValueError."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None

    mock_model = MagicMock()
    with pytest.raises(ValueError, match="No existe registro en 'embeddings_meta'"):
        validar_contra_meta(mock_conn, "otra_columna", mock_model, "modelo-x", 128)


def test_embeddings_validacion_falla_si_difiere_nombre_modelo():
    """Si el modelo en DB difiere del esperado en código, debe lanzar ValueError."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = ("modelo_antiguo", 768)

    mock_model = MagicMock()
    mock_model.get_sentence_embedding_dimension.return_value = 768

    with pytest.raises(ValueError, match="difiere del modelo esperado"):
        validar_contra_meta(mock_conn, "texto", mock_model, MODEL_TEXTO_NAME, 768)


def test_embeddings_validacion_falla_si_difiere_dimension():
    """Si la dimensión de BD o del modelo difiere, debe lanzar ValueError."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # Caso A: DB tiene dimensión incorrecta
    mock_cursor.fetchone.return_value = (MODEL_TEXTO_NAME, 384)
    mock_model = MagicMock()
    mock_model.get_sentence_embedding_dimension.return_value = 768
    with pytest.raises(ValueError, match="dimensión configurada .* difiere"):
        validar_contra_meta(mock_conn, "texto", mock_model, MODEL_TEXTO_NAME, DIM_TEXTO)

    # Caso B: El modelo genera una dimensión que no coincide con la esperada
    mock_cursor.fetchone.return_value = (MODEL_TEXTO_NAME, 768)
    mock_model_err = MagicMock()
    mock_model_err.get_sentence_embedding_dimension.return_value = 512
    with pytest.raises(ValueError, match="no coincide con la dimensión esperada"):
        validar_contra_meta(mock_conn, "texto", mock_model_err, MODEL_TEXTO_NAME, DIM_TEXTO)


def test_medicion_articulos_truncados():
    """medir_articulos_truncados cuenta correctamente textos que superan max_seq_length."""
    mock_tokenizer = MagicMock()
    # Simular que el primer texto tiene 600 tokens y el segundo 100 tokens
    mock_tokenizer.return_value = {
        "input_ids": [
            [1] * 600,
            [1] * 100,
        ]
    }

    articulos = [
        (1, "Titulo 1", "Texto largo que excede", "h1", "h2", "[vec]", None),
        (2, "Titulo 2", "Texto corto", "h3", "h4", "[vec]", None),
    ]

    truncados = medir_articulos_truncados(articulos, mock_tokenizer, max_seq_length=512)
    assert truncados == 1
