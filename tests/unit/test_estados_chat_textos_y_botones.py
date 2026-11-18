from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.mensajes import (
    MSG_CATEGORIA_TAGS_COMPLETOS,
    MSG_OPCION_NO_DISPONIBLE,
    MSG_PLANTILLA_VALIDADA,
)

TEXTO_VALIDO = """
### Pasos de Configuración

1. Abrir el menú principal y seleccionar Facturación.
2. Ingresar los datos correspondientes en el formulario de ventas.
3. Guardar los cambios y verificar que se reflejen en el sistema.

### Consideraciones

El proceso debe realizarse con permisos de administrador activo.
""".strip()

RESULTADO_PLANTILLA_MOCK = """
### Pasos de Configuración

1. Abrir el menú principal y seleccionar Facturación.
2. Ingresar los datos correspondientes en el formulario de ventas.
3. Guardar los cambios y verificar que se reflejen en el sistema Finnegans.

### Consideraciones

El proceso debe realizarse con permisos de administrador activo.
""".strip()

RESULTADO_AUDITOR_MOCK = """
### Dictamen editorial

Se corrigió la redacción y formato del artículo.

<<<VERSION_CORREGIDA>>>
### Pasos de Configuración Editados

1. Abrir el menú principal y seleccionar Facturación.
2. Ingresar los datos correspondientes en el formulario de ventas.
3. Guardar los cambios en el sistema.

### Consideraciones

El proceso debe realizarse con permisos de administrador activo.
<<<FIN_VERSION>>>
""".strip()


@pytest.fixture
def mock_buscador():
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.evaluar_titulo.return_value = None
    buscador.evaluar_texto.return_value = None
    return buscador


@pytest.fixture
def client(mock_buscador):
    def override_buscador():
        yield mock_buscador

    app.dependency_overrides[get_buscador_duplicados] = override_buscador
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as test_client:
            yield test_client
    app.dependency_overrides.clear()


def _botones(r):
    return [(b["label"], b["accion"]) for b in r.get("botones") or []]


def test_estado_plantilla_validada_texto_y_botones(client, mock_buscador):
    """REVISION_TIPO (plantilla elegida):
    - Mensaje MSG_PLANTILLA_VALIDADA + aviso del tipo; botones Aplicar plantilla | Continuar, sin Volver.
    - Sin agente: error amable, sin tocar Editor ni Vista previa.
    - Con agente: el resultado queda en la Vista previa, el original en el Editor; solo queda Continuar.
    - Continuar pasa a ESPERANDO_METADATOS sin Volver (el tipo queda fijo tras aplicar la skill).
    """
    r1 = client.post("/chat", json={"mensaje": "Cómo Configurar Facturación en Ventas"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

    r3 = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_TIPO
    assert r3["mensaje"].startswith(MSG_PLANTILLA_VALIDADA)
    assert "Se va a aplicar la plantilla **Instructivo**" in r3["mensaje"]
    assert _botones(r3) == [("Aplicar plantilla", "aplicar_plantilla"), ("Continuar", "continuar")]
    assert r3["navegacion"] == []

    # Sin agente: mensaje amable, Vista previa y flags intactos
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=None):
        r_err = client.post("/chat", json={"session_id": sid, "accion": "aplicar_plantilla"}).json()
    assert r_err["estado"] == EstadoFlujo.REVISION_TIPO
    assert "No pudimos **aplicar la plantilla** en este momento" in r_err["mensaje"]
    assert _botones(r_err) == [("Aplicar plantilla", "aplicar_plantilla"), ("Continuar", "continuar")]
    assert r_err["borrador"]["bloques_texto"] == [TEXTO_VALIDO]
    assert r_err["borrador"]["resultado_skill_pendiente"] is False

    # Con agente: resultado en Vista previa, original en el Editor
    mock_baco = MagicMock(return_value=RESULTADO_PLANTILLA_MOCK)
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=mock_baco):
        r_skill = client.post("/chat", json={"session_id": sid, "accion": "aplicar_plantilla"}).json()
    assert r_skill["estado"] == EstadoFlujo.REVISION_TIPO
    assert "Apliqué la plantilla **Instructivo**" in r_skill["mensaje"]
    assert _botones(r_skill) == [("Continuar", "continuar")]
    assert r_skill["borrador"]["texto_editor"] == TEXTO_VALIDO
    assert r_skill["borrador"]["texto_base_limpio"] == TEXTO_VALIDO
    assert "Finnegans" in r_skill["borrador"]["bloques_texto"][0]
    assert r_skill["borrador"]["resultado_skill_pendiente"] is True
    assert r_skill["borrador"]["skill_pendiente"] == "plantilla"

    # Continuar avanza a metadatos; con la plantilla aplicada no se ofrece Volver
    r_cont = client.post("/chat", json={"session_id": sid, "accion": "continuar"}).json()
    assert r_cont["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r_cont["navegacion"] == []
    r_volver = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r_volver["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r_volver["mensaje"] == MSG_OPCION_NO_DISPONIBLE


def test_estado_categoria_y_tags_completos_texto_y_botones(client, mock_buscador):
    """REVISION_METADATOS (categoría y tags completos):
    - Mensaje MSG_CATEGORIA_TAGS_COMPLETOS; botones Auditar | Continuar.
    - Sin agente: error amable, sin tocar Editor ni Vista previa.
    - Con agente: resultado en la Vista previa, original en el Editor; solo queda Continuar.
    - Continuar lleva a EDICION_FINAL y Finalizar registra el borrador.
    """
    r1 = client.post("/chat", json={"mensaje": "Cómo Configurar Facturación en Ventas"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})
    client.post("/chat", json={"session_id": sid, "accion": "continuar"})

    r_meta = client.post(
        "/chat",
        json={"session_id": sid, "accion": "enviar_datos", "categoria_id": 5, "tags": ["instructivo", "ventas"]},
    ).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_METADATOS
    assert r_meta["mensaje"] == MSG_CATEGORIA_TAGS_COMPLETOS
    assert _botones(r_meta) == [("Auditar", "auditar"), ("Continuar", "continuar")]

    with patch("baco.server.app.dependencies.get_baco_agent", return_value=None):
        r_err = client.post("/chat", json={"session_id": sid, "accion": "auditar"}).json()
    assert r_err["estado"] == EstadoFlujo.REVISION_METADATOS
    assert "No pudimos **auditar el artículo** en este momento" in r_err["mensaje"]
    assert _botones(r_err) == [("Auditar", "auditar"), ("Continuar", "continuar")]
    assert r_err["borrador"]["bloques_texto"] == [TEXTO_VALIDO]
    assert r_err["borrador"]["resultado_skill_pendiente"] is False

    mock_baco = MagicMock(return_value=RESULTADO_AUDITOR_MOCK)
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=mock_baco):
        r_aud = client.post("/chat", json={"session_id": sid, "accion": "auditar"}).json()
    assert r_aud["estado"] == EstadoFlujo.REVISION_METADATOS
    assert "Revisé el texto" in r_aud["mensaje"]
    assert _botones(r_aud) == [("Continuar", "continuar")]
    assert r_aud["borrador"]["texto_editor"] == TEXTO_VALIDO
    assert r_aud["borrador"]["texto_base_limpio"] == TEXTO_VALIDO
    assert "Pasos de Configuración Editados" in r_aud["borrador"]["bloques_texto"][0]
    assert r_aud["borrador"]["resultado_skill_pendiente"] is True
    assert r_aud["borrador"]["skill_pendiente"] == "auditor"

    r_ed = client.post("/chat", json={"session_id": sid, "accion": "continuar"}).json()
    assert r_ed["estado"] == EstadoFlujo.EDICION_FINAL
    assert _botones(r_ed) == [("Finalizar", "finalizar")]
    r_fin = client.post("/chat", json={"session_id": sid, "accion": "finalizar"}).json()
    assert r_fin["estado"] == EstadoFlujo.FINALIZADO
    assert r_fin["borrador"]["finalizado"] is True


def test_auditar_sin_categoria_o_tags_tematicos_error_amable(client, mock_buscador):
    """Auditar no se ofrece antes de definir categoría y etiquetas (REVISION_TIPO):
    se rechaza como opción no disponible, sin ejecutar la skill ni tocar Editor ni Vista previa."""
    r1 = client.post("/chat", json={"mensaje": "Cómo Configurar Facturación en Ventas"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})

    mock_baco = MagicMock(return_value=RESULTADO_AUDITOR_MOCK)
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=mock_baco):
        r_aud = client.post("/chat", json={"session_id": sid, "accion": "auditar"}).json()

    assert r_aud["estado"] == EstadoFlujo.REVISION_TIPO
    assert r_aud["mensaje"] == MSG_OPCION_NO_DISPONIBLE
    mock_baco.assert_not_called()
    assert r_aud["borrador"]["bloques_texto"] == [TEXTO_VALIDO]
    assert r_aud["borrador"]["resultado_skill_pendiente"] is False


