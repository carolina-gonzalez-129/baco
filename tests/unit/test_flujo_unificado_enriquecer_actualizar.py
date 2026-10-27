import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados, get_baco_agent
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


def test_decision_titulo_enriquecer_trae_imagenes_y_valida_bloqueante(client, mock_buscador):
    """En DECISION_TITULO, 'enriquecer' consulta GET en vivo con imágenes.

    Si no tiene categoría o tiene hallazgo bloqueante, no se puede aprobar.
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

    # 3. Envía el texto para validar
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r2["borrador"]["texto_alineado_discourse"]}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "https://bc.finneg.com/uploads/default/original/2X/a/error.png" in r3["borrador"]["texto_alineado_discourse"]
    # Al tener tags >= 2 y plantilla 'instructivo', llega a REVISION_BORRADOR y se puede dar conformidad
    assert "conforme" in r3["opciones"]


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

    r3_conf = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r3["borrador"]["texto_alineado_discourse"]}).json()
    assert r3_conf["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "conforme" in r3_conf["opciones"]


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
    r3_conf = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r3["borrador"]["texto_alineado_discourse"]}).json()

    # Primero pide confirmación de metadatos heredados
    assert r3_conf["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3_conf["aviso_metadatos_heredados"] is not None
    assert "aceptar" in r3_conf["opciones"]

    # Al aceptar, como no tenía tag de plantilla ('instructivo' ni 'soluciones'),
    # se detiene en ESPERANDO_PLANTILLA
    r4 = client.post("/chat", json={"session_id": sid, "accion": "aceptar"}).json()
    assert r4["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert "instructivo" in r4["opciones"]
    assert "soluciones" in r4["opciones"]


def test_decision_texto_actualizar_adopta_nuevo_titulo(client, mock_buscador):
    """En DECISION_TEXTO, 'actualizar' adopta el nuevo título ingresado por el usuario."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia semántica",
        "link": "https://bc.finneg.com/t/777",
        "coincidencias": [(777, "Artículo Base Antiguo", "https://bc.finneg.com/t/777")],
    }

    nuevo_titulo = "Mi Nuevo Título para el Módulo 2026"
    r1 = client.post("/chat", json={"mensaje": nuevo_titulo}).json()
    sid = r1["session_id"]

    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Aporte complementario para la actualización."})

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_CON_IMAGEN, 15, ["instructivo", "contabilidad"])
        r3 = client.post("/chat", json={"session_id": sid, "accion": "actualizar"}).json()

    assert r3["borrador"]["titulo"] == nuevo_titulo
    assert "https://bc.finneg.com/uploads/default/original/2X/a/error.png" in r3["borrador"]["texto_alineado_discourse"]


def test_articulo_enriquecido_con_menos_de_2_tags_se_detiene_en_metadatos(client, mock_buscador):
    """Si el artículo recuperado tiene solo 1 tag, se detiene en ESPERANDO_METADATOS."""
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

    # Primero pide confirmación de metadatos heredados
    assert r3_conf["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3_conf["aviso_metadatos_heredados"] is not None
    assert "aceptar" in r3_conf["opciones"]

    # Al aceptar, como tiene 1 tag y requiere mínimo 2 -> se detiene en ESPERANDO_METADATOS
    r4 = client.post("/chat", json={"session_id": sid, "accion": "aceptar"}).json()
    assert r4["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "volver" in r4["opciones"]

