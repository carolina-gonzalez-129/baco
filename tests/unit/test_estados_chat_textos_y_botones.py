from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados
from baco.server.app.dependencies import get_baco_agent
from baco.server.app.main import app
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.mensajes import (
    MSG_CATEGORIA_TAGS_COMPLETOS,
    MSG_PLANTILLA_VALIDADA,
)

from baco.server.app.middleware import API_KEY

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


def test_estado_plantilla_validada_texto_y_botones(client, mock_buscador):
    """
    1) Estado 'plantilla validada':
       - Mensaje exacto: '¡Perfecto! Si querés, podés aplicar la plantilla para estandarizar el contenido, o podés **Continuar** si ya la tiene.'
       - Botones exactos en orden: Aplicar plantilla | Continuar | Volver
       - Sin 'Seguir editando' ni 'Descartar borrador'.
       - 'Continuar' y 'Volver' conservan su comportamiento actual.
       - Si no hay agente, 'aplicar_plantilla' retorna mensaje amable de error sin modificar Editor ni Vista previa.
       - Con agente mockeado, primera aplicación sin skill previa:
         * Ejecuta la skill y preserva el original en texto_editor y texto_base_limpio.
         * El resultado queda en bloques_texto.
         * Estado permanece REVISION_BORRADOR.
         * Botones posteriores exactos: Continuar | Volver.
    """
    # 1. Iniciar sesión y enviar título
    r1 = client.post("/chat", json={"mensaje": "Cómo Configurar Facturación en Ventas"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # 2. Confirmar texto
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

    # 3. Elegir plantilla -> pasa a Estado 'plantilla validada' (REVISION_BORRADOR con revision_intermedia=True)
    r3 = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR

    # Verificación del mensaje exacto
    mensaje_esperado = "Podés Aplicar plantilla para darle el formato estándar, o tocar Continuar si ya lo tiene."
    assert r3["mensaje"] == mensaje_esperado
    assert r3["mensaje"] == MSG_PLANTILLA_VALIDADA

    # Verificación de la lista exacta de botones y su orden
    labels_botones = [b["label"] for b in r3.get("botones", [])]
    assert labels_botones == ["Aplicar plantilla", "Continuar", "Volver"]

    acciones_botones = [b["accion"] for b in r3.get("botones", [])]
    assert acciones_botones == ["aplicar_plantilla", "continuar_revision", "volver"]

    # Verificar que NO están "Seguir editando" ni "Descartar borrador"
    assert "Seguir editando" not in labels_botones
    assert "Descartar borrador" not in labels_botones
    assert "editar" not in acciones_botones
    assert "rechazar" not in acciones_botones

    # 4. Caso de error sin agente: no modifica Editor ni Vista previa y retorna mensaje amable
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=None):
        r_err = client.post("/chat", json={"session_id": sid, "accion": "aplicar_plantilla"}).json()
        assert r_err["estado"] == EstadoFlujo.REVISION_BORRADOR
        assert "No pudimos aplicar la plantilla en este momento" in r_err["mensaje"]
        assert [b["label"] for b in r_err.get("botones", [])] == ["Aplicar plantilla", "Continuar", "Volver"]
        # Vista previa y flags permanecen intactos
        assert r_err["borrador"]["bloques_texto"] == [TEXTO_VALIDO]
        assert r_err["borrador"]["resultado_skill_pendiente"] is False

    # 5. Primera aplicación con agente mockeado (sin skill previa)
    mock_baco = MagicMock(return_value=RESULTADO_PLANTILLA_MOCK)
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=mock_baco):
        r_skill = client.post("/chat", json={"session_id": sid, "accion": "aplicar_plantilla"}).json()

    assert r_skill["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_skill["mensaje"] == "Listo, apliqué la plantilla. Revisá el resultado y tocá **Continuar**."

    # Botones posteriores exactos: Continuar | Volver
    assert [b["label"] for b in r_skill.get("botones", [])] == ["Continuar", "Volver"]
    assert [b["accion"] for b in r_skill.get("botones", [])] == ["continuar_revision", "volver"]

    # Original preservado en texto_editor y texto_base_limpio
    assert r_skill["borrador"]["texto_editor"] == TEXTO_VALIDO
    assert r_skill["borrador"]["texto_base_limpio"] == TEXTO_VALIDO

    # Resultado en bloques_texto
    assert "Finnegans" in r_skill["borrador"]["bloques_texto"][0]
    assert r_skill["borrador"]["resultado_skill_pendiente"] is True
    assert r_skill["borrador"]["skill_pendiente"] == "plantilla"

    # 6. "Continuar" avanza a ESPERANDO_METADATOS
    r_cont = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_cont["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # 7. "Volver" desde ESPERANDO_METADATOS regresa a revisión intermedia
    r_volver1 = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r_volver1["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert [b["label"] for b in r_volver1.get("botones", [])] == ["Aplicar plantilla", "Continuar", "Volver"]

    # "Volver" desde revisión intermedia regresa a ESPERANDO_PLANTILLA
    r_volver2 = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r_volver2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA


def test_estado_categoria_y_tags_completos_texto_y_botones(client, mock_buscador):
    """
    2) Estado 'categoría y tags temáticos completos':
       - Mensaje exacto (una sola vez, sin duplicados): '¡Perfecto! Si querés, podés auditar la calidad editorial del contenido, o podés **Continuar** si ya la tiene.'
       - Botones exactos en orden: Auditar | Continuar | Volver
       - Sin 'Finalizar' ni 'Seguir editando'.
       - 'Continuar' ejecuta lo que antes ejecutaba Finalizar (finaliza el borrador).
       - 'Volver' tiene el mismo comportamiento fallback que en los demás estados.
       - Si no hay agente, 'auditar' retorna mensaje amable sin modificar Editor ni Vista previa.
       - Con agente mockeado, primera aplicación de auditar:
         * Ejecuta la skill y preserva original en texto_editor y texto_base_limpio.
         * El resultado queda en bloques_texto.
         * Estado permanece REVISION_BORRADOR.
         * Botones posteriores exactos: Continuar | Volver.
    """
    # 1. Iniciar sesión, enviar título, confirmar texto y elegir plantilla
    r1 = client.post("/chat", json={"mensaje": "Cómo Configurar Facturación en Ventas"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})
    client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"})

    # 2. Completar categoría y tags temáticos -> pasa a Estado 'categoría y tags temáticos completos'
    r_meta = client.post(
        "/chat",
        json={"session_id": sid, "mensaje": "Ventas", "categoria_id": 5, "tags": ["instructivo", "ventas"]},
    ).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_BORRADOR

    # Verificación del mensaje exacto
    mensaje_esperado = "Ya está todo completo. Podés Auditar el texto para mejorar su redacción, o tocar Continuar para enviarlo."
    assert r_meta["mensaje"] == mensaje_esperado
    assert r_meta["mensaje"] == MSG_CATEGORIA_TAGS_COMPLETOS
    assert "El borrador superó las validaciones." not in r_meta["mensaje"]

    # Verificación de la lista exacta de botones y su orden
    labels_botones = [b["label"] for b in r_meta.get("botones", [])]
    assert labels_botones == ["Auditar", "Continuar", "Volver"]

    acciones_botones = [b["accion"] for b in r_meta.get("botones", [])]
    assert acciones_botones == ["auditar", "continuar", "volver"]

    # Verificar que NO están "Finalizar" ni "Seguir editando"
    assert "Finalizar" not in labels_botones
    assert "Seguir editando" not in labels_botones
    assert "finalizar" not in acciones_botones
    assert "editar" not in acciones_botones

    # 3. Caso de error sin agente: no modifica Editor ni Vista previa y retorna mensaje amable
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=None):
        r_err = client.post("/chat", json={"session_id": sid, "accion": "auditar"}).json()
        assert r_err["estado"] == EstadoFlujo.REVISION_BORRADOR
        assert "No pudimos auditar el artículo en este momento" in r_err["mensaje"]
        assert [b["label"] for b in r_err.get("botones", [])] == ["Auditar", "Continuar", "Volver"]
        # Vista previa y flags permanecen intactos
        assert r_err["borrador"]["bloques_texto"] == [TEXTO_VALIDO]
        assert r_err["borrador"]["resultado_skill_pendiente"] is False

    # 4. Primera aplicación de auditar con agente mockeado
    mock_baco = MagicMock(return_value=RESULTADO_AUDITOR_MOCK)
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=mock_baco):
        r_aud = client.post("/chat", json={"session_id": sid, "accion": "auditar"}).json()

    assert r_aud["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_aud["mensaje"] == "Listo, revisé el texto. Mirá el resultado y tocá **Continuar**."

    # Botones posteriores exactos: Continuar | Volver
    assert [b["label"] for b in r_aud.get("botones", [])] == ["Continuar", "Volver"]
    assert [b["accion"] for b in r_aud.get("botones", [])] == ["continuar", "volver"]

    # Original preservado en texto_editor y texto_base_limpio
    assert r_aud["borrador"]["texto_editor"] == TEXTO_VALIDO
    assert r_aud["borrador"]["texto_base_limpio"] == TEXTO_VALIDO

    # Resultado en bloques_texto
    assert "Pasos de Configuración Editados" in r_aud["borrador"]["bloques_texto"][0]
    assert r_aud["borrador"]["resultado_skill_pendiente"] is True
    assert r_aud["borrador"]["skill_pendiente"] == "auditor"

    # 5. Acción "volver": comportamiento fallback (vuelve a ESPERANDO_METADATOS)
    r_vol = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r_vol["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Volver a ingresar metadatos para llegar de nuevo a revisión final
    r_meta2 = client.post(
        "/chat",
        json={"session_id": sid, "mensaje": "Ventas", "categoria_id": 5, "tags": ["instructivo", "ventas"]},
    ).json()
    assert r_meta2["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_meta2["mensaje"] == mensaje_esperado

    # 6. "Continuar" lleva a EDICION_FINAL y luego "Finalizar" finaliza el borrador
    r_ed = client.post("/chat", json={"session_id": sid, "accion": "continuar"}).json()
    assert r_ed["estado"] == EstadoFlujo.EDICION_FINAL
    r_fin = client.post("/chat", json={"session_id": sid, "accion": "finalizar"}).json()
    assert r_fin["estado"] == EstadoFlujo.FINALIZADO
    assert r_fin["borrador"]["finalizado"] is True


def test_auditar_sin_categoria_o_tags_tematicos_error_amable(client, mock_buscador):
    """
    En auditar, si faltan la categoría o los tags temáticos:
    - Retorna un mensaje amable informando que faltan metadatos.
    - No ejecuta la skill ni modifica Editor ni Vista previa.
    """
    # 1. Iniciar sesión y llegar a revisión intermedia (donde aún no se ingresaron categoría ni tags temáticos)
    r1 = client.post("/chat", json={"mensaje": "Cómo Configurar Facturación en Ventas"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})

    mock_baco = MagicMock(return_value=RESULTADO_AUDITOR_MOCK)
    with patch("baco.server.app.dependencies.get_baco_agent", return_value=mock_baco):
        r_aud = client.post("/chat", json={"session_id": sid, "accion": "auditar"}).json()

    assert r_aud["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "Para auditar el artículo, primero es necesario definir la categoría" in r_aud["mensaje"]

    # La skill no se ejecutó
    mock_baco.assert_not_called()

    # Editor y Vista previa permanecen intactos
    assert r_aud["borrador"]["bloques_texto"] == [TEXTO_VALIDO]
    assert r_aud["borrador"]["resultado_skill_pendiente"] is False
