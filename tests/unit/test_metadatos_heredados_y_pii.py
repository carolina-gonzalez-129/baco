"""Tests unitarios para la coexistencia de aviso_privacidad y aviso_metadatos_heredados.

Cubre:
1. Enriquecer/actualizar con PII en el texto de aporte: la respuesta contiene
   tanto aviso_privacidad como aviso_metadatos_heredados, con opciones aceptar y rechazar.
2. Enriquecer/actualizar sin PII: aviso_metadatos_heredados presente y aviso_privacidad=None.
3. Tras una edición manual que dispara sanitización mientras los metadatos siguen pendientes,
   aviso_metadatos_heredados se conserva automáticamente en la respuesta.
4. Aceptar metadatos heredados conserva categoria_id y tags y marca metadatos_heredados_revisados=True.
5. Rechazar metadatos heredados limpia categoria_id y tags y avanza a solicitar nuevos metadatos.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados, get_baco_agent
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos
from baco.server.services.orquestador.sesion import SESIONES


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


def test_enriquecer_con_pii_devuelve_ambos_avisos(client, mock_buscador):
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

    # Debe estar en REVISION_BORRADOR
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    # Debe tener aviso_privacidad porque hubo PII
    assert r3["aviso_privacidad"] is not None
    assert "anonimizaron" in r3["aviso_privacidad"].lower() or "personal" in r3["aviso_privacidad"].lower()
    # Debe tener aviso_metadatos_heredados porque los metadatos siguen pendientes de decisión
    assert r3["aviso_metadatos_heredados"] is not None
    assert "versión anterior" in r3["aviso_metadatos_heredados"].lower()
    # Las opciones deben incluir aceptar y rechazar
    assert "aceptar" in r3["opciones"]
    assert "rechazar" in r3["opciones"]
    assert r3["borrador"]["metadatos_heredados_revisados"] is False


def test_enriquecer_sin_pii_devuelve_solo_aviso_metadatos(client, mock_buscador):
    """Al enriquecer sin PII, la respuesta trae aviso_metadatos_heredados y aviso_privacidad es None."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título encontrada",
        "link": "https://bc.finneg.com/t/9002",
        "coincidencias": [(9002, "Configuración de Compras y Proveedores", "https://bc.finneg.com/t/9002")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 9002,
        "titulo": "Configuración de Compras y Proveedores",
        "url": "https://bc.finneg.com/t/9002",
        "texto": TEXTO_BASE_EXISTENTE,
        "categoria_id": 24,
        "tags": ["instructivo", "compras", "proveedores"],
    }

    r1 = client.post("/chat", json={"mensaje": "Configuración de Compras y Proveedores"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})

    texto_total_limpio = TEXTO_BASE_EXISTENTE + "\n\n" + TEXTO_APORTE_SIN_PII
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_total_limpio}).json()

    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3["aviso_privacidad"] is None
    assert r3["aviso_metadatos_heredados"] is not None
    assert "aceptar" in r3["opciones"]
    assert "rechazar" in r3["opciones"]
    assert r3["borrador"]["metadatos_heredados_revisados"] is False


@pytest.mark.parametrize("edicion_con_pii", [True, False])
def test_edicion_manual_conserva_aviso_metadatos_heredados_automaticamente(client, mock_buscador, edicion_con_pii):
    """Cualquier mutación manual que ocurra mientras los metadatos estén pendientes debe conservar aviso_metadatos_heredados."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/9003",
        "coincidencias": [(9003, "Guía de Ventas y Facturación", "https://bc.finneg.com/t/9003")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 9003,
        "titulo": "Guía de Ventas y Facturación",
        "url": "https://bc.finneg.com/t/9003",
        "texto": TEXTO_BASE_EXISTENTE,
        "categoria_id": 20,
        "tags": ["instructivo", "ventas"],
    }

    r1 = client.post("/chat", json={"mensaje": "Guía de Ventas y Facturación"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_BASE_EXISTENTE})

    # Ahora el usuario edita el texto en REVISION_BORRADOR
    nuevo_texto = TEXTO_BASE_EXISTENTE + ("\n\nContacto: juan.perez@gmail.com CUIT 20-30405060-9" if edicion_con_pii else "\n\nPasos adicionales verificados.")
    r_edit = client.post("/chat", json={"session_id": sid, "accion": "editar", "texto": nuevo_texto}).json()

    assert r_edit["estado"] == EstadoFlujo.REVISION_BORRADOR
    # aviso_metadatos_heredados debe conservarse automáticamente
    assert r_edit["aviso_metadatos_heredados"] is not None
    assert "aceptar" in r_edit["opciones"]
    assert "rechazar" in r_edit["opciones"]
    assert r_edit["borrador"]["metadatos_heredados_revisados"] is False

    if edicion_con_pii:
        assert r_edit["aviso_privacidad"] is not None
    else:
        assert r_edit["aviso_privacidad"] is None


def test_aceptar_metadatos_heredados_conserva_datos_y_marca_revisado(client, mock_buscador):
    """Pulsar 'aceptar' confirma los metadatos heredados y habilita la conformidad."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/9004",
        "coincidencias": [(9004, "Guía de Tesorería", "https://bc.finneg.com/t/9004")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 9004,
        "titulo": "Guía de Tesorería",
        "url": "https://bc.finneg.com/t/9004",
        "texto": TEXTO_BASE_EXISTENTE,
        "categoria_id": 20,
        "tags": ["instructivo", "tesoreria", "bancos"],
    }

    r1 = client.post("/chat", json={"mensaje": "Guía de Tesorería"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_BASE_EXISTENTE})

    # Aceptar metadatos
    r_acep = client.post("/chat", json={"session_id": sid, "accion": "aceptar"}).json()
    assert r_acep["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_acep["borrador"]["metadatos_heredados_revisados"] is True
    assert r_acep["borrador"]["categoria_id"] == 20
    assert "tesoreria" in r_acep["borrador"]["tags"]
    assert r_acep["aviso_metadatos_heredados"] is None


def test_rechazar_metadatos_heredados_limpia_y_solicita_nuevos(client, mock_buscador):
    """Pulsar 'rechazar' limpia categoria_id y tags y solicita definirlos desde cero."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/9005",
        "coincidencias": [(9005, "Guía de Contabilidad General", "https://bc.finneg.com/t/9005")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 9005,
        "titulo": "Guía de Contabilidad General",
        "url": "https://bc.finneg.com/t/9005",
        "texto": TEXTO_BASE_EXISTENTE,
        "categoria_id": 20,
        "tags": ["instructivo", "contabilidad"],
    }

    r1 = client.post("/chat", json={"mensaje": "Guía de Contabilidad General"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_BASE_EXISTENTE})

    # Rechazar metadatos heredados
    r_rech = client.post("/chat", json={"session_id": sid, "accion": "rechazar_metadatos"}).json()
    assert r_rech["borrador"]["metadatos_heredados_revisados"] is True
    assert r_rech["borrador"]["categoria_id"] is None
    assert r_rech["borrador"]["tags"] == []
    # Al estar vacíos los metadatos, pasa a pedir plantilla
    assert r_rech["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
