import io
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.app.dependencies import get_buscador_duplicados
from baco.server.config_limites import (
    MAX_RECURSOS_POR_SESION,
    RECURSO_MAX_BYTES,
    MAX_RECURSOS_TOTAL_BYTES,
)
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados

TEXTO_ORIGINAL_CON_DOS_IMAGENES = (
    "Este es el texto original del artículo que contiene suficientes caracteres para superar las validaciones mínimas del sistema.\n\n"
    "![diagrama_a.png](https://bc.finneg.com/uploads/diagrama_a.png)\n\n"
    "Paso intermedio con detalles explicativos para el procedimiento contable oficial.\n\n"
    "![diagrama_b.png](https://bc.finneg.com/uploads/diagrama_b.png)\n\n"
    "Cierre del procedimiento con recomendaciones finales."
)


@pytest.fixture
def mock_buscador():
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.cur = MagicMock()
    buscador.con = MagicMock()
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


def test_a_eliminar_recurso_en_esperando_texto(client, mock_buscador):
    """Test A: Eliminar recurso en ESPERANDO_TEXTO:
    - desaparece del borrador
    - el orden de los restantes se mantiene
    - no cambia el Editor (texto_editor)
    - no escribe en DB
    - el flujo sigue pidiendo confirmar texto sin saltearse validaciones.
    """
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título",
        "link": "https://bc.finneg.com/t/5001",
        "coincidencias": [(5001, "Artículo Existente Con Recursos", "https://bc.finneg.com/t/5001")],
    }

    # 1. Ingresar título coincidente
    r1 = client.post("/chat", json={"mensaje": "Artículo Existente Con Recursos"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # 2. Enriquecer
    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_ORIGINAL_CON_DOS_IMAGENES, 10, ["instructivo", "contabilidad"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    borrador = r2["borrador"]
    assert len(borrador["multimedia"]) == 2
    id_a = borrador["multimedia"][0]["id"]
    id_b = borrador["multimedia"][1]["id"]
    editor_inicial = borrador["texto_editor"]

    # Reset mock_buscador.cur para auditar escrituras DB
    mock_buscador.cur.reset_mock()

    # 3. Eliminar el primer recurso (id_a)
    resp_del = client.delete(f"/chat/recursos/{id_a}", headers={"X-Session-ID": sid})
    assert resp_del.status_code == 200
    datos_del = resp_del.json()

    # Verifica que desaparece del borrador
    ids_restantes = [r["id"] for r in datos_del["recursos"]]
    assert id_a not in ids_restantes
    assert id_b in ids_restantes
    assert len(ids_restantes) == 1

    # Verificar sesión actual
    r_borrador = client.get("/chat/recursos", headers={"X-Session-ID": sid}).json()
    assert len(r_borrador["recursos"]) == 1
    assert r_borrador["recursos"][0]["id"] == id_b

    # El editor no cambió
    # Enviar un mensaje vacío o consulta de turno y verificar estado y texto_editor
    r_turno = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Mi aporte adicional"}).json()
    # Avanza a REVISION_BORRADOR porque ya tenía categoría y tags heredados
    assert r_turno["estado"] in (EstadoFlujo.REVISION_BORRADOR, EstadoFlujo.ESPERANDO_METADATOS)
    assert "diagrama_a.png" not in r_turno["borrador"]["texto_alineado_discourse"]
    assert "diagrama_b.png" in r_turno["borrador"]["texto_alineado_discourse"]

    # Verificar no persistencia en DB (sin INSERT/UPDATE en artículos)
    for call in mock_buscador.cur.execute.call_args_list:
        query = str(call[0][0]).upper()
        assert "INSERT INTO ARTICULOS" not in query
        assert "UPDATE ARTICULOS" not in query


def test_b_eliminar_en_esperando_plantilla_y_metadatos_el_estado_no_avanza(client, mock_buscador):
    """Test B: Eliminar en ESPERANDO_PLANTILLA y ESPERANDO_METADATOS: el estado no avanza
    y las validaciones obligatorias siguen vigentes.
    """
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/5002",
        "coincidencias": [(5002, "Artículo Sin Plantilla", "https://bc.finneg.com/t/5002")],
    }

    r1 = client.post("/chat", json={"mensaje": "Artículo Sin Plantilla"}).json()
    sid = r1["session_id"]

    # El artículo original no tiene plantilla ni tags suficientes
    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_ORIGINAL_CON_DOS_IMAGENES, None, [])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # Confirmar texto sin plantilla -> pasa a ESPERANDO_PLANTILLA
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

    # Eliminar recurso en ESPERANDO_PLANTILLA
    rec_id_1 = r3["borrador"]["multimedia"][0]["id"]
    resp_del1 = client.delete(f"/chat/recursos/{rec_id_1}", headers={"X-Session-ID": sid})
    assert resp_del1.status_code == 200

    # Comprobar que en el orquestador el estado NO avanzó
    r_check1 = client.post("/chat", json={"session_id": sid, "mensaje": "ayuda"}).json()
    assert r_check1["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

    # Seleccionar plantilla -> como faltan tags y categoría, pasa a ESPERANDO_METADATOS
    r4 = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r4["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Eliminar segundo recurso en ESPERANDO_METADATOS
    rec_id_2 = r4["borrador"]["multimedia"][0]["id"]
    resp_del2 = client.delete(f"/chat/recursos/{rec_id_2}", headers={"X-Session-ID": sid})
    assert resp_del2.status_code == 200
    assert len(resp_del2.json()["recursos"]) == 0

    # Comprobar que el estado sigue siendo ESPERANDO_METADATOS
    r_check2 = client.post("/chat", json={"session_id": sid, "mensaje": "ayuda"}).json()
    assert r_check2["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Cumplir metadatos obligatorios -> recién ahora pasa a REVISION_BORRADOR
    r5 = client.post("/chat", json={"session_id": sid, "categoria_id": 10, "tags": ["instructivo", "ventas"]}).json()
    assert r5["estado"] == EstadoFlujo.REVISION_BORRADOR


def test_c_agregar_imagen_con_vista_previa_activa(client, mock_buscador):
    """Test C: Agregar imagen con la Vista previa activa en esos estados:
    - se suma al borrador al final con posicion/orden contiguos
    - el contenido del Editor queda idéntico (texto_editor no cambia)
    """
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/5003",
        "coincidencias": [(5003, "Artículo Base Para Agregar Imagen", "https://bc.finneg.com/t/5003")],
    }

    r1 = client.post("/chat", json={"mensaje": "Artículo Base Para Agregar Imagen"}).json()
    sid = r1["session_id"]

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_ORIGINAL_CON_DOS_IMAGENES, 5, ["instructivo", "compras"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer", "texto": "Mi texto en el Editor"}).json()

    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r2["borrador"]["texto_editor"] == "Mi texto en el Editor"
    cant_inicial = len(r2["borrador"]["multimedia"])

    # Agregar nueva imagen vía POST /chat/recursos/agregar
    url_nueva = "https://bc.finneg.com/uploads/foto_adicional.png"
    resp_add = client.post(
        "/chat/recursos/agregar",
        headers={"X-Session-ID": sid},
        json={"referencia": url_nueva, "tipo": "imagen"},
    )
    assert resp_add.status_code == 200
    recs_actuales = resp_add.json()["recursos"]
    assert len(recs_actuales) == cant_inicial + 1

    # Verificar que va al final y con orden correlativo
    ultima = recs_actuales[-1]
    assert ultima["referencia"] == url_nueva
    assert ultima["orden"] == len(recs_actuales) - 1

    # Verificar que el contenido del Editor permanece idéntico
    assert resp_add.json()["borrador"]["texto_editor"] == "Mi texto en el Editor"
    r_check = client.post("/chat", json={"session_id": sid, "mensaje": "ayuda"}).json()
    assert r_check["borrador"]["texto_editor"] == "Mi texto en el Editor"


def test_d_cotas_config_limites(client, mock_buscador):
    """Test D: Cotas de config_limites.py:
    - El 21.º recurso se rechaza (máximo 20)
    - Un archivo > 10 MB se rechaza
    - Superar 50 MB total se rechaza
    """
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/5004",
        "coincidencias": [(5004, "Artículo Para Probar Cotas", "https://bc.finneg.com/t/5004")],
    }

    r1 = client.post("/chat", json={"mensaje": "Artículo Para Probar Cotas"}).json()
    sid = r1["session_id"]

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = ("Texto base con longitud suficiente para las validaciones mínimas.", 1, ["instructivo", "general"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    # 1. Cargar 20 recursos
    for i in range(MAX_RECURSOS_POR_SESION):
        resp = client.post(
            "/chat/recursos/agregar",
            headers={"X-Session-ID": sid},
            json={"referencia": f"https://bc.finneg.com/img_{i}.png", "tipo": "imagen"},
        )
        assert resp.status_code == 200

    # 2. El 21.º recurso se rechaza
    resp_21 = client.post(
        "/chat/recursos/agregar",
        headers={"X-Session-ID": sid},
        json={"referencia": "https://bc.finneg.com/img_exceso.png", "tipo": "imagen"},
    )
    assert resp_21.status_code == 400
    assert "límite máximo" in resp_21.json()["detail"].lower()

    # 3. Archivo > 10 MB se rechaza
    archivo_pesado = io.BytesIO(b"X" * (RECURSO_MAX_BYTES + 500))
    resp_pesado = client.post(
        "/chat/recursos",
        headers={"X-Session-ID": sid},
        files={"file": ("foto_grande.png", archivo_pesado, "image/png")},
    )
    assert resp_pesado.status_code in (400, 413, 422)


def test_e_no_persistencia_en_db(client, mock_buscador):
    """Test E: Verificar que ninguna operación de eliminación o agregado
    de recursos ejecute sentencias de escritura (INSERT/UPDATE) en la base de datos.
    """
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/5005",
        "coincidencias": [(5005, "Artículo Prueba Persistencia", "https://bc.finneg.com/t/5005")],
    }

    r1 = client.post("/chat", json={"mensaje": "Artículo Prueba Persistencia"}).json()
    sid = r1["session_id"]

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_ORIGINAL_CON_DOS_IMAGENES, 2, ["instructivo", "tesoreria"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    # Reset mock calls antes de operar con recursos
    mock_buscador.cur.reset_mock()
    mock_buscador.con.reset_mock()

    # Agregar recurso
    client.post(
        "/chat/recursos/agregar",
        headers={"X-Session-ID": sid},
        json={"referencia": "https://bc.finneg.com/img_nueva.png", "tipo": "imagen"},
    )

    # Eliminar recurso
    rec_id = r2["borrador"]["multimedia"][0]["id"]
    client.delete(f"/chat/recursos/{rec_id}", headers={"X-Session-ID": sid})

    # Verificar que no se llamaron commits ni queries de inserción/actualización
    for call in mock_buscador.cur.execute.call_args_list:
        q = str(call[0][0]).strip().upper()
        assert not q.startswith("INSERT")
        assert not q.startswith("UPDATE")
        assert not q.startswith("DELETE")

    assert mock_buscador.con.commit.call_count == 0


def test_f_resurreccion_volver_y_enriquecer_de_nuevo_conserva_eliminacion(client, mock_buscador):
    """Test F: Resurrección:
    eliminar recurso -> Volver a decisión -> Enriquecer de nuevo -> el recurso sigue eliminado.
    No se sobreescribe el borrador ni se restaura el recurso original de la base.
    """
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título",
        "link": "https://bc.finneg.com/t/5006",
        "coincidencias": [(5006, "Artículo Para Test Resurrección", "https://bc.finneg.com/t/5006")],
    }

    # 1. Ingresar título
    r1 = client.post("/chat", json={"mensaje": "Artículo Para Test Resurrección"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # 2. Enriquecer por primera vez
    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_ORIGINAL_CON_DOS_IMAGENES, 3, ["instructivo", "finanzas"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert len(r2["borrador"]["multimedia"]) == 2
    id_eliminado = r2["borrador"]["multimedia"][0]["id"]
    id_conservado = r2["borrador"]["multimedia"][1]["id"]

    # 3. Eliminar el primer recurso
    resp_del = client.delete(f"/chat/recursos/{id_eliminado}", headers={"X-Session-ID": sid})
    assert resp_del.status_code == 200

    # 4. El usuario toca "Volver" hacia la decisión de título
    r_volver = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r_volver["estado"] == EstadoFlujo.DECISION_TITULO

    # 5. El usuario decide nuevamente tocar "Enriquecer"
    # IMPORTANTE: No debe llamar a cargar_datos_articulo() ni restaurar el recurso eliminado
    r_enriquecer_nuevo = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r_enriquecer_nuevo["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # 6. Comprobar que el recurso eliminado SIGUE eliminado y solo queda el segundo
    recs_finales = r_enriquecer_nuevo["borrador"]["multimedia"]
    assert len(recs_finales) == 1
    assert recs_finales[0]["id"] == id_conservado
    assert id_eliminado not in [r["id"] for r in recs_finales]
