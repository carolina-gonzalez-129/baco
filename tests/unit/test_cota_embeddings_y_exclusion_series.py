from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.app.dependencies import get_buscador_duplicados
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados, MIN_CARACTERES_EMBEDDINGS


def test_evaluar_texto_omite_embeddings_si_es_menor_a_400():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)

    # Texto de 100 caracteres (< 400)
    texto_corto = "Texto corto de prueba para verificar que no dispara embeddings bajo ningún punto de vista."
    assert len(texto_corto) < MIN_CARACTERES_EMBEDDINGS

    with patch.object(buscador, "buscar_por_texto", return_value=[]), \
         patch.object(buscador, "buscar_en_embeddings") as mock_emb:
        res = buscador.evaluar_texto(texto_corto, headers=True, titulo="Título de prueba")
        assert res is None
        mock_emb.assert_not_called()


def test_evaluar_texto_ejecuta_embeddings_si_es_mayor_o_igual_a_400():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)

    # Texto de más de 400 caracteres
    texto_largo = "Este es un texto explicativo completo y con suficiente extensión para garantizar que el modelo de embeddings cuente con contexto semántico adecuado. " * 5
    assert len(texto_largo) >= MIN_CARACTERES_EMBEDDINGS

    with patch.object(buscador, "buscar_por_texto", return_value=[]), \
         patch.object(buscador, "buscar_en_embeddings", return_value=[(77, "Artículo Duplicado", "https://bc.finneg.com/77", 0.92, 0.9, 0.91)]) as mock_emb:
        res = buscador.evaluar_texto(texto_largo, headers=True, titulo="Título de prueba")
        assert res is not None
        mock_emb.assert_called_once()
        assert res["link"] == "https://bc.finneg.com/77"


def test_filtrar_articulos_series_excluye_articulos_con_base_titulo():
    mock_cur = MagicMock()
    # Simular que en la DB el id 100 pertenece a una serie y el id 200 no
    mock_cur.fetchall.return_value = [(100,)]
    buscador = BuscadorDuplicados(mock_cur)

    candidatos = [
        {"id": 100, "titulo": "Novedades Impositivas 2024", "url": "https://bc.finneg.com/100"},
        {"id": 200, "titulo": "Guía de Facturación General", "url": "https://bc.finneg.com/200"},
    ]

    filtrados = buscador.filtrar_articulos_series(candidatos)
    assert len(filtrados) == 1
    assert filtrados[0]["id"] == 200


def test_evaluar_texto_con_excluir_series_filtra_candidato_serie():
    mock_cur = MagicMock()
    buscador = BuscadorDuplicados(mock_cur)

    texto_largo = "Explicación detallada de configuración impositiva con más de cuatrocientos caracteres requeridos para embeddings. " * 5

    # Mock buscar_en_embeddings devuelve coincidencia con id 100
    with patch.object(buscador, "buscar_por_texto", return_value=[]), \
         patch.object(buscador, "buscar_en_embeddings", return_value=[{"id": 100, "titulo": "Novedades 2024", "url": "https://bc.finneg.com/100"}]), \
         patch.object(buscador, "filtrar_articulos_series", return_value=[]):
        res = buscador.evaluar_texto(texto_largo, headers=True, titulo="Título", excluir_series=True)
        # Como era de serie y se excluyen series, debe dar None
        assert res is None


@pytest.fixture
def mock_buscador():
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.cur = MagicMock()
    buscador.obtener_articulo.return_value = None
    buscador.evaluar_titulo.return_value = None
    buscador.evaluar_texto.return_value = None
    return buscador


@pytest.fixture
def client(mock_buscador):
    def override_buscador():
        yield mock_buscador
    app.dependency_overrides[get_buscador_duplicados] = override_buscador
    with TestClient(app, headers={"X-API-Key": API_KEY}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_descartar_serie_activa_exclusion_en_evaluar_texto(client, mock_buscador):
    """Verifica que si el usuario descarta una sugerencia de serie en DECISION_TITULO,
    la bandera descarto_serie se activa y evaluar_texto se invoca con excluir_series=True."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "El título parece pertenecer a la serie 'Novedades Impositivas', ¿te gustaría actualizar la última entrada?",
        "link": "https://bc.finneg.com/t/9001",
        "coincidencias": [{"id": 9001, "titulo": "Novedades Impositivas 2025", "url": "https://bc.finneg.com/t/9001"}],
    }

    # 1. Enviar título que dispara coincidencia de serie
    r1 = client.post("/chat", json={"mensaje": "Novedades Impositivas 2026"}).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO
    sid = r1["session_id"]

    # 2. El usuario descarta la serie
    r2 = client.post("/chat", json={"session_id": sid, "accion": "descartar"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # 3. El usuario confirma su texto
    texto_propio = "Este es mi propio contenido independiente con suficiente longitud para superar el mínimo requerido sin problemas."
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_propio}).json()

    # Verificar que evaluar_texto fue llamado con excluir_series=True
    assert mock_buscador.evaluar_texto.called
    llamada = mock_buscador.evaluar_texto.call_args
    # excluir_series se pasa como 6to argumento posicional o keyword
    excluir_series_pasado = llamada.kwargs.get("excluir_series", llamada.args[4] if len(llamada.args) > 4 else False)
    assert excluir_series_pasado is True
