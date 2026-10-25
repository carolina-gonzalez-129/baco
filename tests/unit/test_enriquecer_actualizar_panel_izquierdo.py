"""Tests para la carga automática del texto en el panel izquierdo y la exclusión

de 'confirmar_texto' en flujos de enriquecimiento y actualización.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.api import get_buscador_duplicados, get_baco_agent
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.sesion import SESIONES


TEXTO_EXISTENTE = """Este es el contenido original del artículo existente en la base de conocimiento.

Tiene suficientes caracteres para superar el mínimo requerido de texto.
Incluye pasos detallados para resolver el problema."""


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
    buscador.evaluar_titulo.return_value = None
    buscador.evaluar_texto.return_value = None
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


def test_enriquecer_vuelca_texto_en_editor_y_permite_modificar_y_confirmar(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título encontrada",
        "link": "https://bc.finneg.com/t/3001",
        "coincidencias": [(3001, "Configuración de Impuestos en Ventas", "https://bc.finneg.com/t/3001")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 3001,
        "titulo": "Configuración de Impuestos en Ventas",
        "url": "https://bc.finneg.com/t/3001",
        "texto": TEXTO_EXISTENTE,
        "categoria_id": 1,
        "tags": ["instructivo", "impuestos", "ventas"],
    }

    # 1. Envía título que coincide
    r1 = client.post("/chat", json={"mensaje": "Configuración de Impuestos en Ventas"}).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO
    sid = r1["session_id"]

    # 2. Clickea 'enriquecer' -> pasa a ESPERANDO_TEXTO con el texto existente volcado en el editor
    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert "confirmar_texto" in r2["opciones"]
    assert r2["borrador"] is not None
    assert r2["borrador"]["texto_limpio"].strip() == TEXTO_EXISTENTE.strip()
    assert r2["borrador"]["modo"] == "enriquecimiento"
    assert r2["borrador"]["articulo_original_id"] == 3001

    # 3. Usuario agrega o modifica texto y confirma
    texto_modificado = TEXTO_EXISTENTE + "\n\nSe agrega apartado sobre alícuotas especiales 2026."
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_modificado}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "conforme" in r3["opciones"]
    assert "alícuotas especiales 2026" in r3["borrador"]["texto_limpio"]


def test_actualizar_vuelca_texto_en_editor_y_permite_modificar_y_confirmar(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Serie detectada",
        "link": "https://bc.finneg.com/t/3002",
        "coincidencias": [(3002, "Novedades Impositivas 2025", "https://bc.finneg.com/t/3002")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 3002,
        "titulo": "Novedades Impositivas 2025",
        "url": "https://bc.finneg.com/t/3002",
        "texto": TEXTO_EXISTENTE,
        "categoria_id": 2,
        "tags": ["soluciones", "impositivas"],
    }

    # 1. Envía título nuevo de la serie
    r1 = client.post("/chat", json={"mensaje": "Novedades Impositivas 2026"}).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO
    sid = r1["session_id"]

    # 2. Clickea 'actualizar' -> pasa a ESPERANDO_TEXTO con el nuevo título y el texto base en el editor
    r2 = client.post("/chat", json={"session_id": sid, "accion": "actualizar"}).json()

    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert "confirmar_texto" in r2["opciones"]
    assert r2["borrador"] is not None
    assert r2["borrador"]["titulo"] == "Novedades Impositivas 2026"
    assert r2["borrador"]["texto_limpio"].strip() == TEXTO_EXISTENTE.strip()

    # 3. Usuario agrega o modifica texto y confirma
    texto_modificado = TEXTO_EXISTENTE + "\n\nActualización de resoluciones vigentes para el período 2026."
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_modificado}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3["borrador"]["titulo"] == "Novedades Impositivas 2026"
    assert "resoluciones vigentes para el período 2026" in r3["borrador"]["texto_limpio"]


def test_confirmar_texto_solo_se_exige_al_redactar_articulo_nuevo(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None

    # 1. Envía título sin coincidencias
    r1 = client.post("/chat", json={"mensaje": "Nuevo Procedimiento de Cierre Mensual"}).json()
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    # Acá SI se pide confirmar_texto porque la persona está redactando
    assert "confirmar_texto" in r1["opciones"]


def test_esperando_texto_acumula_fragmentos_y_confirma(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    # 1. Iniciar esperando texto
    r1 = client.post("/chat", json={"mensaje": "Nuevo Procedimiento de Cierre Mensual"}).json()
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    sid = r1["session_id"]

    # 2. Envío de fragmento 1 por chat (mensaje libre)
    frag1 = "Primer paso del procedimiento: abrir el módulo de tesorería y verificar los comprobantes pendientes."
    r2 = client.post("/chat", json={"session_id": sid, "mensaje": frag1, "texto": frag1}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert SESIONES[sid].texto_en_edicion == frag1

    # 3. Envío de fragmento 2 por chat (acumulado en texto)
    frag2 = "Segundo paso del procedimiento: conciliar todas las cuentas bancarias asociadas al período contable."
    acumulado = f"{frag1}\n\n{frag2}"
    r3 = client.post("/chat", json={"session_id": sid, "mensaje": frag2, "texto": acumulado}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert SESIONES[sid].texto_en_edicion == acumulado

    # 4. Confirmar texto mediante la acción del panel izquierdo
    r4 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": acumulado}).json()
    # Pasa a la siguiente etapa (metadatos o revisión)
    assert r4["estado"] != EstadoFlujo.ESPERANDO_TEXTO
    assert r4["borrador"] is not None
    assert r4["borrador"]["texto_limpio"].strip() == acumulado.strip()

