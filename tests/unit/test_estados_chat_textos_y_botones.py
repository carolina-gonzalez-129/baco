from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados
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
       - 'Aplicar plantilla' devuelve el mismo estado sin cambios.
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
    mensaje_esperado = "¡Perfecto! Si querés, podés aplicar la plantilla para estandarizar el contenido, o podés **Continuar** si ya la tiene."
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

    # 4. Acción "aplicar_plantilla": debe devolver el mismo estado sin cambios
    r_skill = client.post("/chat", json={"session_id": sid, "accion": "aplicar_plantilla"}).json()
    assert r_skill["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_skill["mensaje"] == mensaje_esperado
    assert [b["label"] for b in r_skill.get("botones", [])] == ["Aplicar plantilla", "Continuar", "Volver"]

    # 5. "Continuar" conserva su comportamiento actual (avanza a ESPERANDO_METADATOS)
    r_cont = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_cont["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # 6. "Volver" desde ESPERANDO_METADATOS regresa a revisión intermedia
    r_volver1 = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r_volver1["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert mensaje_esperado in r_volver1["mensaje"]
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
       - 'Auditar' devuelve el mismo estado sin cambios.
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
        json={"session_id": sid, "categoria_id": 5, "tags": ["instructivo", "ventas"]},
    ).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_BORRADOR

    # Verificación del mensaje exacto
    mensaje_esperado = "¡Perfecto! Si querés, podés auditar la calidad editorial del contenido, o podés **Continuar** si ya la tiene."
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

    # 3. Acción "auditar": debe devolver el mismo estado sin cambios
    r_aud = client.post("/chat", json={"session_id": sid, "accion": "auditar"}).json()
    assert r_aud["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_aud["mensaje"] == mensaje_esperado
    assert [b["label"] for b in r_aud.get("botones", [])] == ["Auditar", "Continuar", "Volver"]

    # 4. Acción "volver": comportamiento fallback (vuelve a ESPERANDO_METADATOS)
    r_vol = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r_vol["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Volver a ingresar metadatos para llegar de nuevo a revisión final
    r_meta2 = client.post(
        "/chat",
        json={"session_id": sid, "categoria_id": 5, "tags": ["instructivo", "ventas"]},
    ).json()
    assert r_meta2["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_meta2["mensaje"] == mensaje_esperado

    # 5. "Continuar" ejecuta por ahora lo mismo que hoy ejecuta Finalizar
    r_fin = client.post("/chat", json={"session_id": sid, "accion": "continuar"}).json()
    assert r_fin["estado"] == EstadoFlujo.FINALIZADO
    assert r_fin["borrador"]["finalizado"] is True
