import pytest
from unittest.mock import MagicMock, patch
from baco.server.services.buscar_duplicados import (
    BuscadorDuplicados,
)


# ==============================================================================
# 1. Tests del Helper _extraer_url
# ==============================================================================

def test_extraer_url():
    assert BuscadorDuplicados._extraer_url(None) is None
    assert BuscadorDuplicados._extraer_url([]) is None
    # Desde Diccionario
    assert BuscadorDuplicados._extraer_url({"url": "https://bc.finneg.com/1"}) == "https://bc.finneg.com/1"
    # Desde Tupla (id, titulo, url, ...)
    assert BuscadorDuplicados._extraer_url((101, "Título", "https://bc.finneg.com/2")) == "https://bc.finneg.com/2"


# ==============================================================================
# 2. Tests de Búsquedas Básicas y Manejo de Errores
# ==============================================================================

def test_buscar_exacto_valor_vacio_retorna_lista_vacia():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)
    
    assert buscador.buscar_exacto("titulo", "") == []
    assert buscador.buscar_exacto("titulo", "   ") == []
    mock_cur.execute.assert_not_called()


def test_buscar_exacto_campo_no_permitido_lanza_error():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)
    
    with pytest.raises(ValueError, match="Campo no permitido"):
        buscador.buscar_exacto("campo_invalido", "test")


def test_buscar_exacto_ejecuta_query_correcta():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [(1, "Articulo 1", "https://url.com/1")]
    buscador = BuscadorDuplicados(mock_cur)

    res = buscador.buscar_exacto("titulo", "Factura", limite=3)
    assert res == [(1, "Articulo 1", "https://url.com/1")]
    mock_cur.execute.assert_called_once()
    query_ejecutada = mock_cur.execute.call_args[0][0]
    assert "hash_titulo" in query_ejecutada
    assert mock_cur.execute.call_args[0][1] == ("Factura", 3)


def test_buscar_por_titulo_y_texto():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    buscador = BuscadorDuplicados(mock_cur)

    buscador.buscar_por_titulo("Título Test", limite=2)
    assert "hash_titulo" in mock_cur.execute.call_args[0][0]

    buscador.buscar_por_texto("Texto Test", limite=1)
    assert "hash_texto" in mock_cur.execute.call_args[0][0]


def test_buscar_por_serie_vacio_y_con_valor():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)

    # Vacío
    assert buscador.buscar_por_serie("") == []
    mock_cur.execute.assert_not_called()

    # Con valor
    mock_cur.fetchall.return_value = [(2, "Serie Mayo 2026", "https://url/2", "Serie")]
    res = buscador.buscar_por_serie("Serie Junio 2026", limite=5)
    assert len(res) == 1
    assert "titulo_base" in mock_cur.execute.call_args[0][0]


def test_buscar_por_titulo_trigrama():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)

    assert buscador.buscar_por_titulo_trigrama("") == []
    mock_cur.execute.assert_not_called()

    mock_cur.fetchall.return_value = [(3, "Título Similar", "https://url/3", 0.85)]
    res = buscador.buscar_por_titulo_trigrama("Titulo Similar", threshold=0.75, limite=5)
    assert len(res) == 1
    # Debe haber ejecutado set_config y la query
    assert mock_cur.execute.call_count == 2
    assert "pg_trgm.similarity_threshold" in mock_cur.execute.call_args_list[0][0][0]


def test_buscar_por_texto_sin_headers():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [(4, "Texto", "https://url/4")]
    buscador = BuscadorDuplicados(mock_cur)

    assert buscador.buscar_por_texto_sin_headers("") == []
    res = buscador.buscar_por_texto_sin_headers("Contenido de prueba")
    assert len(res) == 1
    assert "hash_texto_sin_headers" in mock_cur.execute.call_args[0][0]


# ==============================================================================
# 3. Tests de Evaluación de Títulos y Textos (Lógica de Negocio y Link)
# ==============================================================================

def test_evaluar_titulo_exacto_incluye_link():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)
    
    with patch.object(buscador, "buscar_por_titulo", return_value=[(10, "Factura A", "https://bc.finneg.com/10")]):
        res = buscador.evaluar_titulo("Factura A")
        assert res is not None
        assert res["link"] == "https://bc.finneg.com/10"
        assert "exactamente este título" in res["mensaje"]
        assert "https://bc.finneg.com/10" in res["mensaje"]


def test_evaluar_titulo_serie_incluye_link():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)
    
    with patch.object(buscador, "buscar_por_titulo", return_value=[]), \
         patch.object(buscador, "buscar_por_serie", return_value=[(20, "Novedades Mayo", "https://bc.finneg.com/20", "Novedades")]):
        res = buscador.evaluar_titulo("Novedades Junio")
        assert res is not None
        assert res["link"] == "https://bc.finneg.com/20"
        assert "Novedades" in res["mensaje"]


def test_evaluar_titulo_trigrama_incluye_link():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)
    
    with patch.object(buscador, "buscar_por_titulo", return_value=[]), \
         patch.object(buscador, "buscar_por_serie", return_value=[]), \
         patch.object(buscador, "buscar_por_titulo_trigrama", return_value=[(30, "Configuración CAE", "https://bc.finneg.com/30", 0.9)]):
        res = buscador.evaluar_titulo("Configurar CAE")
        assert res is not None
        assert res["link"] == "https://bc.finneg.com/30"
        assert "muy parecidos" in res["mensaje"]


def test_evaluar_titulo_sin_coincidencias_retorna_none():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)
    
    with patch.object(buscador, "buscar_por_titulo", return_value=[]), \
         patch.object(buscador, "buscar_por_serie", return_value=[]), \
         patch.object(buscador, "buscar_por_titulo_trigrama", return_value=[]):
        assert buscador.evaluar_titulo("Título Completamente Nuevo") is None


def test_evaluar_texto_exacto_y_embeddings():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)

    # Coincidencia exacta
    with patch.object(buscador, "buscar_por_texto", return_value=[(40, "Texto 40", "https://bc.finneg.com/40")]):
        res = buscador.evaluar_texto("Texto repetido", headers=True, titulo="Titulo")
        assert res is not None
        assert res["link"] == "https://bc.finneg.com/40"

    # Coincidencia por embeddings
    with patch.object(buscador, "buscar_por_texto", return_value=[]), \
         patch.object(buscador, "buscar_en_embeddings", return_value=[(50, "Similar 50", "https://bc.finneg.com/50", 0.85, 0.9, 0.88)]):
        res = buscador.evaluar_texto("Texto similar", headers=True, titulo="Titulo")
        assert res is not None
        assert "similares" in res["mensaje"]


# ==============================================================================
# 4. Tests del Orquestador evaluar_coincidencias
# ==============================================================================

def test_evaluar_coincidencias_prioriza_titulo():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)

    with patch.object(buscador, "evaluar_titulo", return_value={"mensaje": "Título duplicado", "coincidencias": []}), \
         patch.object(buscador, "evaluar_texto") as mock_eval_texto:
        res = buscador.evaluar_coincidencias("Título", headers=True, texto="Texto")
        assert res == {"mensaje": "Título duplicado", "coincidencias": []}
        mock_eval_texto.assert_not_called()


def test_evaluar_coincidencias_evalua_texto_si_titulo_no_coincide():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)

    with patch.object(buscador, "evaluar_titulo", return_value=None), \
         patch.object(buscador, "evaluar_texto", return_value={"mensaje": "Texto duplicado", "coincidencias": []}):
        res = buscador.evaluar_coincidencias("Título Libre", headers=True, texto="Texto Duplicado")
        assert res == {"mensaje": "Texto duplicado", "coincidencias": []}


# ==============================================================================
# 5. Tests de la Inyección de Dependencias get_buscador_duplicados
# ==============================================================================

def test_get_buscador_duplicados_injects_db():
    from baco.server.app.main import get_buscador_duplicados
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("baco.server.app.main.get_conn") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        gen = get_buscador_duplicados()
        buscador = next(gen)
        assert isinstance(buscador, BuscadorDuplicados)
        assert buscador.cur is mock_cur
