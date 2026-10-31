import pytest
from unittest.mock import MagicMock
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
    app.dependency_overrides[get_buscador_duplicados] = lambda: mock_buscador
    app.dependency_overrides[get_baco_agent] = lambda: MagicMock()
    with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
        yield c
    app.dependency_overrides.clear()


def test_etapa_no_retrocede_al_aceptar_metadatos_sin_plantilla(client, mock_buscador):
    """En camino enriquecer desde título, si el artículo previo no tenía plantilla, la etapa no salta 2 -> 4 -> 3."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/9010",
        "coincidencias": [(9010, "Configuración de Servidores", "https://bc.finneg.com/t/9010")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 9010,
        "titulo": "Configuración de Servidores",
        "url": "https://bc.finneg.com/t/9010",
        "texto": TEXTO_BASE_EXISTENTE,
        "categoria_id": 20,
        "tags": ["servidores"],
    }

    # Etapa 1: Decisión título
    r1 = client.post("/chat", json={"mensaje": "Configuración de Servidores"}).json()
    sid = r1["session_id"]
    assert r1["etapa"]["actual"] == 1

    # Decide enriquecer -> ESPERANDO_TEXTO (Etapa 2)
    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r2["etapa"]["actual"] == 2

    # Confirma texto -> REVISION_BORRADOR esperando aceptar/rechazar metadatos heredados
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_BASE_EXISTENTE}).json()
    assert r3["aviso_metadatos_heredados"] is not None
    assert r3["etapa"]["actual"] == 3
    assert r3["etapa"]["nombre"] == "Plantilla y etiquetas"

    # Usuario pulsa aceptar -> al no tener plantilla previa, pide plantilla (sigue en Etapa 3)
    r4 = client.post("/chat", json={"session_id": sid, "accion": "aceptar"}).json()
    assert r4["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r4["etapa"]["actual"] == 3
    assert r4["etapa"]["nombre"] == "Plantilla y etiquetas"

    # Elige plantilla -> borrador validado pasa a Etapa 4 (Revisión)
    r5 = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r5["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r5["etapa"]["actual"] == 4
    assert r5["etapa"]["nombre"] == "Revisión"

    # Nuevo flujo: 'continuar_revision' cierra la revisión intermedia; con metadatos completos
    # pasa directo a la revisión final (sigue en Etapa 4)
    r5b = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r5b["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r5b["etapa"]["actual"] == 4

    # Da conformidad -> Etapa 5 (Conformidad)
    r6 = client.post("/chat", json={"session_id": sid, "accion": "conforme"}).json()
    assert r6["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO
    assert r6["etapa"]["actual"] == 5


def test_etapa_no_retrocede_al_rechazar_metadatos_camino_contenido(client, mock_buscador):
    """En camino enriquecer desde contenido, al rechazar metadatos la etapa avanza monótonamente 1->5."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Contenido similar",
        "link": "https://bc.finneg.com/t/9011",
        "coincidencias": [(9011, "Procedimiento de Auditoría", "https://bc.finneg.com/t/9011")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 9011,
        "titulo": "Procedimiento de Auditoría",
        "url": "https://bc.finneg.com/t/9011",
        "texto": TEXTO_BASE_EXISTENTE,
        "categoria_id": 20,
        "tags": ["instructivo", "auditoria"],
    }

    # Título sin duplicado -> avanza directo a ESPERANDO_TEXTO (Etapa 2)
    r1 = client.post("/chat", json={"mensaje": "Auditoría General de Cuentas"}).json()
    sid = r1["session_id"]
    assert r1["etapa"]["actual"] == 2

    # Confirma texto -> coincide con contenido existente: DECISION_TEXTO (Etapa 2)
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_BASE_EXISTENTE}).json()
    assert r2["estado"] == EstadoFlujo.DECISION_TEXTO
    assert r2["etapa"]["actual"] == 2

    # Elige enriquecer -> ESPERANDO_TEXTO (Etapa 2)
    r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r3["etapa"]["actual"] == 2

    # Confirma texto post-enriquecer -> REVISION_BORRADOR esperando decisión de metadatos (Etapa 3)
    r4 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto"}).json()
    assert r4["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r4["aviso_metadatos_heredados"] is not None
    assert r4["etapa"]["actual"] == 3
    assert r4["etapa"]["nombre"] == "Plantilla y etiquetas"

    # Rechaza metadatos -> pide plantilla (Etapa 3)
    r5 = client.post("/chat", json={"session_id": sid, "accion": "rechazar"}).json()
    assert r5["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r5["etapa"]["actual"] == 3
    assert r5["etapa"]["nombre"] == "Plantilla y etiquetas"
