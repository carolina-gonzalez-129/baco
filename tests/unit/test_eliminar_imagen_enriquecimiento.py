from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.app.dependencies import get_buscador_duplicados
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados

TEXTO_CON_IMAGEN = (
    "Este es el texto original del artículo que contiene suficientes caracteres para superar las validaciones mínimas.\n\n"
    "![diagrama.png](https://bc.finneg.com/uploads/diagrama.png)\n\n"
    "Y aquí continúa el texto explicativo con los pasos correspondientes."
)

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
    with TestClient(app, headers={"X-API-Key": API_KEY}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_eliminar_imagen_en_enriquecimiento_persiste_y_no_resucita(client, mock_buscador):
    """Verifica que al enriquecer un artículo con imagen, un recurso solo se elimina por acción
    explícita (DELETE /chat/recursos/{id}) y al editar y confirmar el texto no reaparece."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título",
        "link": "https://bc.finneg.com/t/9991",
        "coincidencias": [(9991, "Artículo Con Imagen Previa", "https://bc.finneg.com/t/9991")],
    }

    # 1. Título
    r1 = client.post("/chat", json={"mensaje": "Artículo Con Imagen Previa"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # 2. Enriquecer (carga artículo con imagen)
    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_CON_IMAGEN, 12, ["instructivo", "contabilidad"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert len(r2["borrador"]["multimedia"]) == 1
    assert "https://bc.finneg.com/uploads/diagrama.png" in r2["borrador"]["texto_alineado_discourse"]

    # 3. El usuario elimina explícitamente el recurso vía endpoint y edita el texto
    rec_id = r2["borrador"]["multimedia"][0]["id"]
    resp_del = client.delete(f"/chat/recursos/{rec_id}", headers={"X-Session-ID": sid})
    assert resp_del.status_code == 200

    texto_sin_imagen = (
        "Este es el texto original del artículo que contiene suficientes caracteres para superar las validaciones mínimas.\n\n"
        "Y aquí continúa el texto explicativo con los pasos correspondientes editados por el usuario."
    )
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_sin_imagen}).json()

    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "diagrama.png" not in r3["borrador"]["texto_alineado_discourse"]
    assert "https://bc.finneg.com/uploads/diagrama.png" not in r3["borrador"]["texto_alineado_discourse"]
    assert len(r3["borrador"]["multimedia"]) == 0
    assert len(r3["borrador"]["recursos"]) == 0


def test_eliminar_imagen_en_articulo_nuevo(client, mock_buscador):
    """En artículo nuevo, editar el texto preserva los recursos existentes y solo se eliminan por acción explícita."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Título para Nuevo Artículo Sin Duplicados"}).json()
    sid = r1["session_id"]

    texto_con_dos_imgs = (
        "Contenido de longitud adecuada para cumplir con el mínimo exigido por el sistema sin problemas.\n\n"
        "![foto1.png](https://bc.finneg.com/foto1.png)\n\n"
        "Paso intermedio con más información requerida.\n\n"
        "![foto2.png](https://bc.finneg.com/foto2.png)"
    )

    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_con_dos_imgs}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert len(r2["borrador"]["multimedia"]) == 2

    # El usuario pasa plantilla
    r3 = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    # Pasa etiquetas
    r4 = client.post("/chat", json={"session_id": sid, "tags": ["instructivo", "general"], "categoria_id": 1}).json()
    assert r4["estado"] == EstadoFlujo.REVISION_BORRADOR

    # Editar el texto sin llamar a DELETE conserva ambos recursos (_sincronizar_borrador_con_edicion no borra recursos)
    texto_editado = (
        "Contenido de longitud adecuada para cumplir con el mínimo exigido por el sistema sin problemas.\n\n"
        "Paso intermedio con más información requerida."
    )
    r_preserva = client.post("/chat", json={"session_id": sid, "accion": "editar", "texto": texto_editado}).json()
    assert len(r_preserva["borrador"]["multimedia"]) == 2

    # Ahora elimina foto1 explícitamente por el endpoint de recursos
    id_foto1 = next(m["id"] for m in r_preserva["borrador"]["multimedia"] if m["nombre"] == "foto1.png")
    resp_del = client.delete(f"/chat/recursos/{id_foto1}", headers={"X-Session-ID": sid})
    assert resp_del.status_code == 200

    r5 = client.post("/chat", json={"session_id": sid, "accion": "editar", "texto": texto_editado}).json()
    assert r5["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "foto1.png" not in r5["borrador"]["texto_alineado_discourse"]
    assert "foto2.png" in r5["borrador"]["texto_alineado_discourse"]
    assert len(r5["borrador"]["multimedia"]) == 1
    assert r5["borrador"]["multimedia"][0]["nombre"] == "foto2.png"
