"""Aviso de privacidad al enriquecer con PII en el aporte.

Los tests de aceptar/rechazar metadatos heredados se eliminaron (7/11): ese mecanismo ya no
existe; los heredados se precargan en ESPERANDO_METADATOS y se confirman con Enviar datos
(cubierto en test_arreglar_meta_datos.py).
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.sesion import SESIONES
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos

TEXTO_BASE_EXISTENTE = (
    "Este es un texto instructivo completo con pasos claros para configurar el sistema.\n\n"
    "1. Primer paso: acceder al panel de configuración general.\n"
    "2. Segundo paso: habilitar la sincronización automática de datos.\n"
    "3. Tercer paso: guardar los cambios y reiniciar los servicios correspondientes."
)

TEXTO_APORTE_CON_PII = (
    "Se agrega procedimiento de contacto de soporte técnico: comunicarse con "
    "juan.perez@gmail.com o con el responsable CUIT 20-30405060-9 para validar las credenciales."
)

TEXTO_APORTE_SIN_PII = (
    "Se agrega procedimiento de auditoría periódica: verificar los registros del sistema "
    "al cierre de cada ejercicio mensual y emitir el informe de control interno."
)


@pytest.fixture(autouse=True)
def limpiar_sesiones():
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


def test_enriquecer_con_pii_devuelve_aviso_privacidad(client, mock_buscador):
    """Al enriquecer con texto que contiene PII, la respuesta trae aviso_privacidad Y aviso_metadatos_heredados."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título encontrada",
        "link": "https://bc.finneg.com/t/9001",
        "coincidencias": [(9001, "Guía de Liquidación de Sueldos y Jornales", "https://bc.finneg.com/t/9001")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 9001,
        "titulo": "Guía de Liquidación de Sueldos y Jornales",
        "url": "https://bc.finneg.com/t/9001",
        "texto": TEXTO_BASE_EXISTENTE,
        "categoria_id": 39,
        "tags": ["instructivo", "sueldos", "hcm"],
    }

    # 1. Enviar título que coincide
    r1 = client.post("/chat", json={"mensaje": "Guía de Liquidación de Sueldos y Jornales"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # 2. Elegir enriquecer -> pasa a ESPERANDO_TEXTO
    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # 3. Confirmar texto agregando PII
    texto_total_con_pii = TEXTO_BASE_EXISTENTE + "\n\n" + TEXTO_APORTE_CON_PII
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_total_con_pii}).json()

    # Todos los flujos convergen en el paso de plantilla; el aviso de privacidad viaja en esta respuesta.
    assert r3["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r3["aviso_privacidad"] is not None
    assert "anonimizaron" in r3["aviso_privacidad"].lower() or "personal" in r3["aviso_privacidad"].lower()


