"""Pruebas unitarias para la resolución de categorías en el orquestador y chat.

Cubre:
1. Resolución por nombre exacto ("Ventas" -> id 20, "Ventas").
2. Distinto case y tildes ("ventas", "CATEGORIA", "tesoreria" vs "Tesorería").
3. Resolución por prefijo o contiene ("Agro", "Agr").
4. Manejo de ambigüedad ("comp" -> Compras, Compras agro, etc.).
5. Categoría inexistente ("Computación cuántica") y mensaje amigable sin repetición genérica.
6. Selección vía menú desplegable (req.categoria_id = 20) asignando id y nombre.
7. Que el borrador y resumen final muestren el nombre y no el id.
8. Reproducción del caso original:
   tags -> "Agro" (resuelve directo y asigna) -> o ingresar "Ventas" -> el artículo final muestra el nombre "Ventas".
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.validaciones import (
    resolver_categoria,
    limpiar_cache_catalogos,
)
from baco.server.services.orquestador.sesion import SESIONES


TEXTO_VALIDO = (
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


def test_resolver_categoria_unitario_exacto_case_tildes_y_prefijo():
    # 1. Nombre exacto
    res_exacto = resolver_categoria("Ventas")
    assert res_exacto.estado == "asignado"
    assert res_exacto.categoria_id == 20
    assert res_exacto.categoria_nombre == "Ventas"

    # 2. Distinto case y tildes
    res_case = resolver_categoria("ventas")
    assert res_case.estado == "asignado"
    assert res_case.categoria_id == 20
    assert res_case.categoria_nombre == "Ventas"

    res_tilde = resolver_categoria("tesoreria")
    assert res_tilde.estado == "asignado"
    assert res_tilde.categoria_id == 22
    assert "Tesorer" in res_tilde.categoria_nombre

    # 3. Prefijo 'Agro' y 'Agr'
    res_agro = resolver_categoria("Agro")
    assert res_agro.estado == "asignado"
    assert res_agro.categoria_id == 37
    assert res_agro.categoria_nombre == "Agro"

    res_agr = resolver_categoria("Agr")
    assert res_agr.estado == "asignado"
    assert res_agr.categoria_id == 37
    assert res_agr.categoria_nombre == "Agro"

    # 4. Ambigüedad
    res_ambiguo = resolver_categoria("comp")
    assert res_ambiguo.estado == "ambiguo"
    assert len(res_ambiguo.candidatos) >= 2
    nombres_cands = [c.nombre for c in res_ambiguo.candidatos]
    assert any("Compras" in n for n in nombres_cands)

    # 5. Inexistente
    res_inexistente = resolver_categoria("Computación cuántica")
    assert res_inexistente.estado == "no_encontrado"
    assert len(res_inexistente.candidatos) > 0  # Brinda sugerencias


def test_flujo_chat_resolucion_agro_directa(client, mock_buscador):
    """Flujo: asigna tags en turno 1 -> escribe 'Agro' en turno 2 -> resuelve id 37 y nombre 'Agro'."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Gestión Agropecuaria"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Turno 1: ingresa etiquetas
    r_tags = client.post("/chat", json={"session_id": sid, "mensaje": "granos, cosecha"}).json()
    assert r_tags["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "decime la categoría por acá" in r_tags["mensaje"]

    # Turno 2: escribe 'Agro' -> ya no es interceptado por tags, resuelve categoría Agro
    r_cat = client.post("/chat", json={"session_id": sid, "mensaje": "Agro"}).json()
    assert r_cat["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_cat["borrador"]["categoria_id"] == 37
    assert r_cat["borrador"]["categoria_nombre"] == "Agro"


def test_flujo_chat_categoria_ambigua_y_seleccion_posterior(client, mock_buscador):
    """Si el usuario ingresa término ambiguo, el bot pregunta por las opciones y al elegir una la asigna."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Circuitos de Adquisiciones"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})
    client.post("/chat", json={"session_id": sid, "mensaje": "facturacion, proveedores"})

    # Ingresa término ambiguo
    r_amb = client.post("/chat", json={"session_id": sid, "mensaje": "comp"}).json()
    assert r_amb["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "¿te referís a" in r_amb["mensaje"]
    assert "Compras" in r_amb["opciones"]

    # Selecciona 'Compras'
    r_ok = client.post("/chat", json={"session_id": sid, "mensaje": "Compras"}).json()
    assert r_ok["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_ok["borrador"]["categoria_id"] == 24
    assert r_ok["borrador"]["categoria_nombre"] == "Compras"


def test_flujo_chat_categoria_inexistente_mensaje_especifico(client, mock_buscador):
    """Si ingresa una categoría que no existe, el bot avisa específicamente qué no encontró sin mensaje genérico."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Administración Avanzada"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})
    client.post("/chat", json={"session_id": sid, "mensaje": "gestion, administracion"})

    r_no = client.post("/chat", json={"session_id": sid, "mensaje": "Computación cuántica"}).json()
    assert r_no["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "No encontré la categoría 'Computación cuántica'" in r_no["mensaje"]


def test_seleccion_via_menu_desplegable_asigna_id_y_nombre(client, mock_buscador):
    """Vía menú desplegable (req.categoria_id = 20) asigna ambos campos correctamente."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Ventas y Comprobantes"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})
    client.post("/chat", json={"session_id": sid, "mensaje": "ventas, facturacion"})

    r_menu = client.post("/chat", json={"session_id": sid, "categoria_id": 20}).json()
    assert r_menu["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_menu["borrador"]["categoria_id"] == 20
    assert r_menu["borrador"]["categoria_nombre"] == "Ventas"


def test_reproduccion_caso_original_articulo_muestra_nombre_ventas(client, mock_buscador):
    """Caso original: tags -> 'Agro' (se asigna o luego cambia a Ventas) -> conformidad -> borrador final muestra 'Ventas'."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Procedimiento Comercial Integral de Ventas"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})

    # 1. Tags temáticos
    client.post("/chat", json={"session_id": sid, "mensaje": "ventas, facturacion"})

    # 2. Ingresa 'Ventas'
    r_cat = client.post("/chat", json={"session_id": sid, "mensaje": "Ventas"}).json()
    assert r_cat["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_cat["borrador"]["categoria_id"] == 20
    assert r_cat["borrador"]["categoria_nombre"] == "Ventas"

    # 3. Presta conformidad
    r_conf = client.post("/chat", json={"session_id": sid, "accion": "conforme"}).json()
    assert r_conf["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO
    assert r_conf["borrador"]["conforme"] is True

    # 4. GET /chat/borrador para la página de artículo final
    res_borrador = client.get(
        "/chat/borrador",
        headers={"X-Session-ID": sid, "X-API-Key": API_KEY},
    )
    assert res_borrador.status_code == 200
    b_data = res_borrador.json()
    # Verifica que el borrador devuelto al front tenga el nombre de la categoría y no sólo el id
    assert b_data["categoria_id"] == 20
    assert b_data["categoria_nombre"] == "Ventas"
    assert "Categoría 20" not in b_data.get("categoria_nombre", "")


def test_turno_etiquetas_tematicas_con_ventas_y_agro_no_asigna_categoria_prematura(client, mock_buscador):
    """Verifica que si el usuario ingresa 'ventas,agro' en el turno de etiquetas, ambos se guarden como tags y no se tome 'ventas' como categoría."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Ventas en el Sector Agropecuario"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Turno 1: usuario ingresa 'ventas, agro'
    r_tags = client.post("/chat", json={"session_id": sid, "mensaje": "ventas, agro"}).json()
    assert r_tags["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "decime la categoría por acá" in r_tags["mensaje"]
    assert r_tags["borrador"]["categoria_id"] is None
    assert "ventas" in r_tags["borrador"]["tags"]
    assert "agro" in r_tags["borrador"]["tags"]

    # Turno 2: usuario ingresa la categoría (ej. 'Agro' o 'Ventas')
    r_cat = client.post("/chat", json={"session_id": sid, "mensaje": "Agro"}).json()
    assert r_cat["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_cat["borrador"]["categoria_id"] == 37
    assert r_cat["borrador"]["categoria_nombre"] == "Agro"
    assert "ventas" in r_cat["borrador"]["tags"]
    assert "agro" in r_cat["borrador"]["tags"]
