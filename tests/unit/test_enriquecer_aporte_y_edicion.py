import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados, get_baco_agent
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.sesion import SESIONES


TEXTO_BASE_DB = (
    "Guía oficial para la emisión de comprobantes electrónicos en Finneg.\n\n"
    "1. Ingresar al módulo de Facturación.\n\n"
    "2. Seleccionar el tipo de comprobante y pulsar Generar."
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
    buscador.obtener_articulo.return_value = {
        "id": 999,
        "titulo": "Emisión de Comprobantes Electrónicos",
        "url": "https://bc.finneg.com/t/999",
        "texto": TEXTO_BASE_DB,
        "categoria_id": 5,
        "tags": ["instructivo", "ventas"],
    }
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


def test_decision_texto_enriquecer_transiciona_a_esperando_texto_y_conserva_aporte(client, mock_buscador):
    """Al elegir enriquecer en DECISION_TEXTO, transiciona a ESPERANDO_TEXTO con el contenido cargado (base + aporte)."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia de contenido detectada",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Emisión de Comprobantes Electrónicos", "https://bc.finneg.com/t/999")],
    }

    # 1. Título
    r1 = client.post("/chat", json={"mensaje": "Facturación y Comprobantes AFIP"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # 2. Envía texto que coincide semánticamente
    aporte_usuario = "Paso adicional: verificar que el punto de venta esté habilitado previamente en ARCA/AFIP."
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": aporte_usuario}).json()
    assert r2["estado"] == EstadoFlujo.DECISION_TEXTO

    # 3. Elige 'enriquecer' -> debe ir a ESPERANDO_TEXTO, no saltar a REVISION_BORRADOR
    r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert "confirmar_texto" in r3["opciones"]
    assert "descartar" in r3["opciones"]
    assert "volver" in r3["opciones"]

    # El editor contiene el aporte del usuario, y la vista previa contiene únicamente el base original
    assert r3["borrador"]["texto_editor"] == aporte_usuario
    txt_vista_previa = r3["texto_limpio"]
    assert "Guía oficial para la emisión de comprobantes" in txt_vista_previa
    assert "verificar que el punto de venta esté habilitado" not in txt_vista_previa

    # 4. El usuario incorpora manualmente su aporte a la vista previa, agrega texto y confirma
    nuevo_texto = txt_vista_previa + "\n\n" + aporte_usuario + "\n\n3. Revisar el CAE generado en la solapa de auditoría."
    r4 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": nuevo_texto}).json()

    # Recién ahora avanza a REVISION_BORRADOR con metadatos heredados
    assert r4["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r4["aviso_metadatos_heredados"] is not None
    assert "aceptar" in r4["opciones"]
    assert "Revisar el CAE generado" in r4["texto_limpio"]


def test_edicion_en_revision_con_metadatos_pendientes(client, mock_buscador):
    """En REVISION_BORRADOR, editar texto aplica cambios sin desbloquear conformidad prematuramente."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Emisión de Comprobantes Electrónicos", "https://bc.finneg.com/t/999")],
    }

    r1 = client.post("/chat", json={"mensaje": "Título Test Edición"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Texto inicial de prueba para enriquecimiento."})
    r_enriq = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r_enriq["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # Confirma texto para llegar a revisión
    r_rev = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r_enriq["texto_limpio"]}).json()
    assert r_rev["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_rev["aviso_metadatos_heredados"] is not None

    # Intento de conformidad bloqueado
    r_conf_bloq = client.post("/chat", json={"session_id": sid, "accion": "conforme"}).json()
    assert r_conf_bloq["estado"] == EstadoFlujo.REVISION_BORRADOR

    # Edición mientras los metadatos siguen pendientes
    texto_editado = r_rev["texto_limpio"] + "\n\nObservación corregida en revisión."
    r_edit = client.post("/chat", json={"session_id": sid, "accion": "editar", "texto": texto_editado}).json()
    assert r_edit["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "Observación corregida en revisión." in r_edit["texto_limpio"]
    # Los metadatos heredados siguen pendientes
    assert r_edit["aviso_metadatos_heredados"] is not None

    # Conformidad sigue bloqueada hasta aceptar/rechazar
    r_conf2 = client.post("/chat", json={"session_id": sid, "accion": "conforme"}).json()
    assert r_conf2["estado"] == EstadoFlujo.REVISION_BORRADOR

    # Aceptar metadatos heredados
    r_acep = client.post("/chat", json={"session_id": sid, "accion": "aceptar"}).json()
    assert r_acep["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_acep["aviso_metadatos_heredados"] is None

    # Nuevo flujo: 'continuar_revision' cierra la revisión intermedia (metadatos heredados completos -> revisión final)
    r_cont = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_cont["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "conforme" in r_cont["opciones"]

    # Ahora sí permite conformidad
    r_fin = client.post("/chat", json={"session_id": sid, "accion": "conforme"}).json()
    assert r_fin["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO


def test_volver_en_esperando_texto_restaura_decision_texto(client, mock_buscador):
    """Pulsar 'volver' desde ESPERANDO_TEXTO en enriquecimiento semántico regresa a DECISION_TEXTO."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia semántica",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Emisión de Comprobantes Electrónicos", "https://bc.finneg.com/t/999")],
    }

    r1 = client.post("/chat", json={"mensaje": "Título Test Volver"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Mi aporte previo que debe conservarse."})
    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # Toca volver
    r3 = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r3["estado"] == EstadoFlujo.DECISION_TEXTO
    assert "enriquecer" in r3["opciones"]
    assert "continuar" in r3["opciones"]


def test_descartar_en_esperando_texto_restaura_aporte(client, mock_buscador):
    """Pulsar 'descartar' restaura el aporte del usuario."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia semántica",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Emisión de Comprobantes Electrónicos", "https://bc.finneg.com/t/999")],
    }

    aporte_original = "Mi texto original redactado con esmero para este artículo particular."
    r1 = client.post("/chat", json={"mensaje": "Título Test Descartar"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": aporte_original})
    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # Elige descartar el artículo existente
    r3 = client.post("/chat", json={"session_id": sid, "accion": "descartar"}).json()
    # Continúa en ESPERANDO_TEXTO pero habiendo descartado el existente
    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert SESIONES[sid].borrador is None


def test_enriquecer_respeta_borrados_y_no_reinyecta_base(client, mock_buscador):
    """En enriquecimiento, si el usuario borra secciones del texto precargado, no se concatenan ni re-inyectan."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia de contenido detectada",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Emisión de Comprobantes Electrónicos", "https://bc.finneg.com/t/999")],
    }

    r1 = client.post("/chat", json={"mensaje": "Facturación y Comprobantes AFIP"}).json()
    sid = r1["session_id"]
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Aporte inicial del usuario."}).json()
    r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # El usuario borra el paso 2 del texto base y reemplaza por un paso 3 nuevo
    texto_editado = (
        "Guía oficial para la emisión de comprobantes electrónicos en Finneg.\n\n"
        "1. Ingresar al módulo de Facturación.\n\n"
        "3. Redacción totalmente nueva reemplazando el paso 2 eliminado por el usuario."
    )
    r4 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_editado}).json()
    assert r4["estado"] == EstadoFlujo.REVISION_BORRADOR
    tl = r4["texto_limpio"]

    # El paso 2 eliminado no debe aparecer
    assert "Seleccionar el tipo de comprobante y pulsar Generar" not in tl
    # El nuevo contenido debe estar presente
    assert "Redacción totalmente nueva reemplazando el paso 2" in tl
    # No debe duplicarse la guía oficial (no re-inyección ni doble concatenación)
    assert tl.count("Guía oficial para la emisión de comprobantes") == 1


def test_actualizar_respeta_reescritura_completa(client, mock_buscador):
    """En actualizar, el texto confirmado por el usuario en el editor es el nuevo texto exacto."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia de contenido detectada",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Emisión de Comprobantes Electrónicos", "https://bc.finneg.com/t/999")],
    }

    r1 = client.post("/chat", json={"mensaje": "Facturación y Comprobantes AFIP"}).json()
    sid = r1["session_id"]
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Aporte que se actualizará."}).json()
    r3 = client.post("/chat", json={"session_id": sid, "accion": "actualizar"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    texto_completamente_nuevo = (
        "Nueva versión completa del proceso de facturación electrónica sin relación con el texto previo.\n\n"
        "Paso único: Ingresar al portal unificado de facturación y autorizar el comprobante."
    )
    r4 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_completamente_nuevo}).json()
    assert r4["estado"] == EstadoFlujo.REVISION_BORRADOR
    tl = r4["texto_limpio"]

    assert "Guía oficial para la emisión de comprobantes" not in tl
    assert "Nueva versión completa del proceso de facturación" in tl
    assert "Paso único: Ingresar al portal unificado" in tl


def test_edicion_en_revision_borra_parrafo_sin_resurreccion(client, mock_buscador):
    """En REVISION_BORRADOR, al editar borrando un párrafo, este no resurge."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Emisión de Comprobantes Electrónicos", "https://bc.finneg.com/t/999")],
    }

    r1 = client.post("/chat", json={"mensaje": "Título Test Edición Borrado"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Aporte inicial a conservar."})
    r_enriq = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    r_rev = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r_enriq["texto_limpio"]}).json()
    assert r_rev["estado"] == EstadoFlujo.REVISION_BORRADOR

    # El usuario edita desde revisión borrando el paso 1
    texto_sin_paso_1 = (
        "Guía oficial para la emisión de comprobantes electrónicos en Finneg.\n\n"
        "2. Seleccionar el tipo de comprobante y pulsar Generar.\n\n"
        "Aporte inicial a conservar."
    )
    r_edit = client.post("/chat", json={"session_id": sid, "accion": "editar", "texto": texto_sin_paso_1}).json()
    assert r_edit["estado"] == EstadoFlujo.REVISION_BORRADOR
    tl = r_edit["texto_limpio"]

    assert "1. Ingresar al módulo de Facturación" not in tl
    assert "2. Seleccionar el tipo de comprobante y pulsar Generar" in tl
