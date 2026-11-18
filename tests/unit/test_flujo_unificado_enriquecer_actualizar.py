from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.sesion import SESIONES

TEXTO_CON_IMAGEN = (
    "Pasos para resolver el error de ajuste por inflación:\n\n"
    "1. Ingresar a la cuenta contable de bienes de cambio.\n\n"
    "![captura_error](https://bc.finneg.com/uploads/default/original/2X/a/error.png)\n\n"
    "2. Desmarcar la casilla 'Genera ajuste por inflación' y guardar los cambios."
)


@pytest.fixture(autouse=True)
def limpiar():
    from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos
    SESIONES.clear()
    limpiar_cache_catalogos()
    yield
    SESIONES.clear()
    limpiar_cache_catalogos()


@pytest.fixture
def mock_buscador():
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.cur = MagicMock()
    buscador.obtener_articulo.return_value = None
    return buscador


@pytest.fixture
def client(mock_buscador):
    def override_buscador():
        yield mock_buscador

    app.dependency_overrides[get_buscador_duplicados] = override_buscador
    app.dependency_overrides[get_baco_agent] = lambda: MagicMock()
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
            yield c
    app.dependency_overrides.clear()


def _avanzar_hasta_metadatos(client, sid, tipo="instructivo"):
    """Troncal actual: ESPERANDO_PLANTILLA -> REVISION_TIPO -> (continuar) -> ESPERANDO_METADATOS."""
    r = client.post("/chat", json={"session_id": sid, "accion": tipo}).json()
    assert r["estado"] == EstadoFlujo.REVISION_TIPO
    return client.post("/chat", json={"session_id": sid, "accion": "continuar"}).json()


def test_decision_titulo_enriquecer_trae_imagenes_y_valida_bloqueante(client, mock_buscador):
    """En DECISION_TITULO, 'enriquecer' consulta GET en vivo con imágenes.

    Tras confirmar el texto converge en ESPERANDO_PLANTILLA y, al pasar el tipo,
    los metadatos del original se cargan en el panel (ESPERANDO_METADATOS) para revisarlos.
    """
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título encontrada",
        "link": "https://bc.finneg.com/t/2414",
        "coincidencias": [(2414, "Ajuste por Inflación en Bienes de Cambio", "https://bc.finneg.com/t/2414")],
    }

    # 1. Envía título que coincide
    r1 = client.post("/chat", json={"mensaje": "Ajuste por Inflación en Bienes de Cambio"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # 2. Clickea 'enriquecer' -> Trae texto con imágenes mediante GET a bc.finneg.com
    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_CON_IMAGEN, 12, ["instructivo", "contabilidad"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    # Pasa a ESPERANDO_TEXTO con el contenido cargado en el editor
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert "https://bc.finneg.com/uploads/default/original/2X/a/error.png" in r2["borrador"]["texto_alineado_discourse"]
    assert r2["borrador"]["articulo_original_id"] == 2414

    # 3. Confirma el texto: todos los flujos convergen en el paso de plantilla
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r2["borrador"]["texto_alineado_discourse"]}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert "https://bc.finneg.com/uploads/default/original/2X/a/error.png" in r3["borrador"]["texto_alineado_discourse"]

    # 4. Tras el tipo, los metadatos heredados quedan cargados en el panel para revisarlos
    r4 = _avanzar_hasta_metadatos(client, sid)
    assert r4["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r4["borrador"]["categoria_id"] == 12
    assert r4["borrador"]["tags"] == ["instructivo", "contabilidad"]


def test_decision_titulo_actualizar_adopta_nuevo_titulo(client, mock_buscador):
    """En DECISION_TITULO, 'actualizar' adopta el nuevo título ingresado por el usuario."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Serie detectada",
        "link": "https://bc.finneg.com/t/2414",
        "coincidencias": [(2414, "Ajuste por Inflación 2025", "https://bc.finneg.com/t/2414")],
    }

    nuevo_titulo = "Ajuste por Inflación 2026 - Guía Definitiva"
    r1 = client.post("/chat", json={"mensaje": nuevo_titulo}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_CON_IMAGEN, 15, ["instructivo", "contabilidad"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "actualizar"}).json()

    assert r2["borrador"]["titulo"] == nuevo_titulo
    assert "https://bc.finneg.com/uploads/default/original/2X/a/error.png" in r2["borrador"]["texto_alineado_discourse"]


def test_decision_texto_enriquecer_trae_imagenes_y_termina_duplicados(client, mock_buscador):
    """En DECISION_TEXTO, 'enriquecer' trae medios con GET y no evalúa duplicados de nuevo."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia semántica",
        "link": "https://bc.finneg.com/t/555",
        "coincidencias": [(555, "Artículo Semántico Existente", "https://bc.finneg.com/t/555")],
    }

    # 1. Envía título limpio
    r1 = client.post("/chat", json={"mensaje": "Resolución de error en Ajuste Inflacionario"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # 2. Envía texto que dispara duplicado en DECISION_TEXTO
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Texto breve de prueba para consulta."}).json()
    assert r2["estado"] == EstadoFlujo.DECISION_TEXTO

    # 3. Clickea 'enriquecer'
    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_CON_IMAGEN, 20, ["soluciones", "finanzas"])
        r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r3["borrador"]["articulo_original_id"] == 555
    assert "https://bc.finneg.com/uploads/default/original/2X/a/error.png" in r3["borrador"]["texto_alineado_discourse"]

    # 4. Confirmar no vuelve a buscar duplicados: pasa al paso de plantilla
    mock_buscador.evaluar_texto.reset_mock()
    r3_conf = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r3["borrador"]["texto_alineado_discourse"]}).json()
    assert r3_conf["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    mock_buscador.evaluar_texto.assert_not_called()

    r4 = _avanzar_hasta_metadatos(client, sid, "soluciones")
    assert r4["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r4["borrador"]["categoria_id"] == 20
    assert r4["borrador"]["tags"] == ["soluciones", "finanzas"]


def test_enriquecido_sin_plantilla_se_detiene_en_esperando_plantilla(client, mock_buscador):
    """Si el artículo recuperado no tiene tag de plantilla ('instructivo' ni 'soluciones'),

    no se aprueba automáticamente: se detiene en ESPERANDO_PLANTILLA.
    """
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia semántica",
        "link": "https://bc.finneg.com/t/888",
        "coincidencias": [(888, "Artículo sin plantilla", "https://bc.finneg.com/t/888")],
    }

    r1 = client.post("/chat", json={"mensaje": "Título Sin Plantilla"}).json()
    sid = r1["session_id"]

    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Texto de prueba para el flujo."})

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        # Devuelve tags SIN plantilla
        mock_bc.return_value = (TEXTO_CON_IMAGEN, 10, ["ventas", "afip"])
        r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r3["borrador"]["tipo_plantilla"] is None
    r3_conf = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r3["borrador"]["texto_alineado_discourse"]}).json()

    assert r3_conf["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert "instructivo" in r3_conf["opciones"]
    assert "soluciones" in r3_conf["opciones"]


def test_articulo_enriquecido_con_menos_de_2_tags_se_detiene_en_metadatos(client, mock_buscador):
    """Si el artículo recuperado tiene solo 1 tag (el de plantilla), se detiene en ESPERANDO_METADATOS."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia semántica",
        "link": "https://bc.finneg.com/t/666",
        "coincidencias": [(666, "Artículo con solo 1 tag", "https://bc.finneg.com/t/666")],
    }

    r1 = client.post("/chat", json={"mensaje": "Título Prueba 1 Tag"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Texto de prueba que supera el mínimo de veinte caracteres."})

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_CON_IMAGEN, 12, ["instructivo"])
        r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    r3_conf = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r3["borrador"]["texto_alineado_discourse"]}).json()
    assert r3_conf["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

    # Hereda la categoría pero no hay etiqueta temática: pide completarla en ESPERANDO_METADATOS
    r4 = _avanzar_hasta_metadatos(client, sid)
    assert r4["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r4["borrador"]["categoria_id"] == 12
    assert r4["borrador"]["tags"] == ["instructivo"]
    assert "volver" in r4["navegacion"]
