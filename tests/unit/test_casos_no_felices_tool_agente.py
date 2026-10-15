import pytest
from unittest.mock import MagicMock
from baco.server.services.buscar_duplicados import BuscadorDuplicados


def test_tool_buscador_con_texto_none_solicita_texto_sin_romper():
    """
    Regla: Si la herramienta de búsqueda de duplicados es consultada sin contenido de texto (texto=None),
    tras descartar duplicados exactos de título, debe solicitar el texto al usuario de forma segura
    (requiere_texto=True, encontrado=False) sin lanzar excepciones por valor nulo.
    """
    mock_db = MagicMock()
    buscador = BuscadorDuplicados(mock_db)

    # Simulamos que no hay coincidencia exacta de título
    buscador.evaluar_titulo = MagicMock(return_value=None)

    resultado = buscador.evaluar_coincidencias(
        titulo="Configuración de Parámetros AFIP",
        headers=True,
        texto=None
    )

    assert resultado["encontrado"] is False
    assert resultado["requiere_texto"] is True
    assert "Indicá el texto para verificar el contenido" in resultado["mensaje"]


def test_tool_buscador_con_resultado_vacio_retorna_ofrecer_publicar():
    """
    Regla: Cuando la herramienta evalúa un artículo y no encuentra duplicados en ninguna de las capas
    (resultado completamente vacío), debe retornar encontrado=False, requiere_texto=False y el mensaje
    canónico que habilita la publicación del contenido.
    """
    mock_db = MagicMock()
    buscador = BuscadorDuplicados(mock_db)

    # Simulamos que ni título ni texto registran coincidencias
    buscador.evaluar_titulo = MagicMock(return_value=None)
    buscador.evaluar_texto = MagicMock(return_value=None)

    resultado = buscador.evaluar_coincidencias(
        titulo="Título totalmente original y novedoso",
        headers=True,
        texto="Texto con procedimiento original que no existe previamente en la base."
    )

    assert resultado["encontrado"] is False
    assert resultado["requiere_texto"] is False
    assert "No se encontraron duplicados, ofrecer publicar!" in resultado["mensaje"]


def test_tool_buscador_con_texto_compuesto_solo_de_espacios_requiere_texto():
    """
    Regla: Un texto compuesto exclusivamente de espacios en blanco debe tratarse como texto ausente (None),
    solicitando contenido válido antes de avanzar a la comparación semántica profunda.
    """
    mock_db = MagicMock()
    buscador = BuscadorDuplicados(mock_db)
    buscador.evaluar_titulo = MagicMock(return_value=None)

    resultado = buscador.evaluar_coincidencias(
        titulo="Título válido",
        headers=True,
        texto="      \t \n   "
    )

    assert resultado["encontrado"] is False
    assert resultado["requiere_texto"] is True
