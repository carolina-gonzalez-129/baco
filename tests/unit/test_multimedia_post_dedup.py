"""Paso 3: el mini panel multimedia está operativo en las tres ramas posteriores a buscar_duplicados.

Ramas: sin coincidencias, coincidencias descartadas y coincidencia aceptada (enriquecer / actualizar).
En todas: listar, agregar, mover y eliminar funcionan.
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

URL_IMG = "https://bc.finneg.com/uploads/default/original/2X/a/error.png"
TEXTO_CON_IMAGEN = (
    "Pasos para resolver el error de ajuste por inflación:\n\n"
    "1. Ingresar a la cuenta contable de bienes de cambio.\n\n"
    f"![captura_error]({URL_IMG})\n\n"
    "2. Desmarcar la casilla 'Genera ajuste por inflación' y guardar los cambios."
)
COINCIDENCIA_TITULO = {
    "mensaje": "Coincidencia de título encontrada",
    "link": "https://bc.finneg.com/t/2414",
    "coincidencias": [(2414, "Ajuste por Inflación en Bienes de Cambio", "https://bc.finneg.com/t/2414")],
}


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


# ---------------------------------------------------------------------------
# Cómo llegar a cada rama
# ---------------------------------------------------------------------------

def _rama_sin_coincidencias(client, mock_buscador):
    r1 = client.post("/chat", json={"mensaje": "Guía nueva de ajuste por inflación"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r1["multimedia_habilitada"] is False
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_CON_IMAGEN}).json()
    return sid, r2


def _rama_coincidencia_descartada(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = COINCIDENCIA_TITULO
    r1 = client.post("/chat", json={"mensaje": "Ajuste por Inflación en Bienes de Cambio"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO
    assert r1["multimedia_habilitada"] is False
    client.post("/chat", json={"session_id": sid, "accion": "descartar"})
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_CON_IMAGEN}).json()
    return sid, r3


def _rama_enriquecer(client, mock_buscador, accion="enriquecer"):
    mock_buscador.evaluar_titulo.return_value = COINCIDENCIA_TITULO
    r1 = client.post("/chat", json={"mensaje": "Ajuste por Inflación en Bienes de Cambio"}).json()
    sid = r1["session_id"]
    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (TEXTO_CON_IMAGEN, 21, ["instructivo", "contabilidad"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": accion}).json()
    return sid, r2


RAMAS = {
    "sin_coincidencias": _rama_sin_coincidencias,
    "coincidencia_descartada": _rama_coincidencia_descartada,
    "enriquecer": _rama_enriquecer,
    "actualizar": lambda c, m: _rama_enriquecer(c, m, accion="actualizar"),
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rama", list(RAMAS))
def test_panel_multimedia_operativo_en_todas_las_ramas(client, mock_buscador, rama):
    sid, resp = RAMAS[rama](client, mock_buscador)
    h = {"X-Session-ID": sid}

    # 1. Habilitado y con la imagen del texto como recurso (no como texto)
    assert resp["multimedia_habilitada"] is True, resp["estado"]
    borrador = resp["borrador"]
    assert [m["referencia"] for m in borrador["multimedia"]] == [URL_IMG]
    assert borrador["orden_multimedia"] == [0]
    assert URL_IMG not in borrador["texto_limpio"]
    assert "[[recurso:rec_1]]" in borrador["texto_limpio"]

    # 2. Listar
    r = client.get("/chat/recursos", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1
    id_existente = r.json()[0]["id"]

    # 3. Agregar al principio (también sobre recursos existentes en enriquecer/actualizar)
    r = client.post("/chat/recursos/agregar", headers=h, json={
        "tipo": "video", "nombre": "Tutorial", "referencia": "https://youtu.be/abc", "posicion": 0,
    })
    assert r.status_code == 200, r.text
    id_nuevo = r.json()["id"]
    assert [x.id for x in SESIONES[sid].borrador.multimedia] == [id_nuevo, id_existente]

    # 4. Mover
    r = client.put("/chat/recursos/reordenar", headers=h, json={"from_index": 0, "to_index": 1})
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == [id_existente, id_nuevo]

    # 5. Eliminar el recurso preexistente con la "x"
    r = client.delete(f"/chat/recursos/{id_existente}", headers=h)
    assert r.status_code == 200, r.text

    b = SESIONES[sid].borrador
    assert [x.id for x in b.multimedia] == [id_nuevo]
    assert b.orden_multimedia == [0] == b.posiciones
    # Decisión 4: eliminar un recurso elimina también su marcador en borrador.texto_limpio y sesion.texto_limpio
    assert f"[[recurso:{id_existente}]]" not in b.texto_limpio
    assert f"[[recurso:{id_existente}]]" not in SESIONES[sid].texto_limpio
    # La vista compuesta refleja la lista actual
    assert "https://youtu.be/abc" in b.texto and URL_IMG not in b.texto


def test_panel_no_disponible_mientras_se_decide_la_deduplicacion(client, mock_buscador):
    """Al volver a DECISION_TITULO desde enriquecer, el borrador sigue en memoria pero el panel se cierra."""
    sid, resp = _rama_enriquecer(client, mock_buscador)
    assert resp["multimedia_habilitada"] is True

    r = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r["estado"] == EstadoFlujo.DECISION_TITULO
    assert r["multimedia_habilitada"] is False
    assert client.get("/chat/recursos", headers={"X-Session-ID": sid}).status_code == 409


def test_panel_no_depende_del_modo(client, mock_buscador):
    """En el flujo de artículo nuevo (modo='nuevo', sin articulo_original_id) el panel está habilitado."""
    sid, resp = _rama_sin_coincidencias(client, mock_buscador)
    assert resp["borrador"]["modo"] == "nuevo"
    assert resp["borrador"]["articulo_original_id"] is None
    assert resp["multimedia_habilitada"] is True


# ===========================================================================
# Paso 4: subida de archivos habilitada y alta por URL con detección de tipo
# ===========================================================================

import io

from baco.server.config_limites import MAX_RECURSOS_POR_SESION, PERMITIR_SUBIDA_RECURSOS, RECURSO_MAX_BYTES
from baco.server.schemas.recurso import Recurso
from baco.server.services.orquestador.recursos_service import limpiar_archivos_temporales_sesion

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"


@pytest.fixture
def sesion_nueva(client, mock_buscador):
    """Borrador en la rama sin coincidencias (modo 'nuevo'); limpia los temporales al final."""
    sid, resp = _rama_sin_coincidencias(client, mock_buscador)
    assert resp["multimedia_habilitada"] is True
    yield sid
    limpiar_archivos_temporales_sesion(sid)


def _subir(client, sid, nombre="grafico.png", contenido=PNG, mime="image/png", posicion=None):
    data = {} if posicion is None else {"posicion": str(posicion)}
    return client.post(
        "/chat/recursos",
        headers={"X-Session-ID": sid},
        files={"file": (nombre, io.BytesIO(contenido), mime)},
        data=data,
    )


def test_flag_de_subida_habilitado():
    assert PERMITIR_SUBIDA_RECURSOS is True


@pytest.mark.parametrize("rama", list(RAMAS))
def test_subida_en_posicion_no_toca_texto_limpio(client, mock_buscador, rama):
    sid, resp = RAMAS[rama](client, mock_buscador)
    try:
        tl = SESIONES[sid].borrador.texto_limpio
        r = _subir(client, sid, posicion=0)
        assert r.status_code == 200, r.text
        rec = r.json()
        assert rec["origen"] == "subido" and rec["tipo"] == "imagen" and rec["mime_type"] == "image/png"

        b = SESIONES[sid].borrador
        assert b.multimedia[0].id == rec["id"]
        assert b.orden_multimedia == list(range(len(b.recursos))) == b.posiciones
        assert b.texto_limpio == tl
    finally:
        limpiar_archivos_temporales_sesion(sid)


def test_subida_rechaza_spoofing_y_archivos_grandes(client, sesion_nueva):
    exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
    assert _subir(client, sesion_nueva, nombre="malicioso.png", contenido=exe).status_code == 400

    grande = PNG + b"\x00" * RECURSO_MAX_BYTES
    r = _subir(client, sesion_nueva, nombre="enorme.png", contenido=grande)
    assert r.status_code == 400 and "tamaño máximo" in r.json()["detail"]
    assert len(SESIONES[sesion_nueva].borrador.recursos) == 1  # solo la imagen original


def test_cupo_maximo_aplica_a_subidas_y_urls(client, sesion_nueva):
    b = SESIONES[sesion_nueva].borrador
    for i in range(MAX_RECURSOS_POR_SESION - len(b.recursos)):
        b.recursos[f"x_{i}"] = Recurso(id=f"x_{i}", tipo="imagen", nombre="x", referencia=f"https://x/{i}.png", orden=99)
    assert _subir(client, sesion_nueva).status_code == 400
    r = client.post("/chat/recursos/agregar", headers={"X-Session-ID": sesion_nueva},
                    json={"referencia": "https://youtu.be/otro"})
    assert r.status_code == 400 and "límite" in r.json()["detail"]


def test_id_de_subida_no_pisa_recursos_existentes(client, sesion_nueva):
    """Antes el ID era rec_{len+1}: después de borrar uno, podía pisar a otro existente."""
    h = {"X-Session-ID": sesion_nueva}
    r1 = _subir(client, sesion_nueva, nombre="a.png").json()  # rec_2 (rec_1 es la imagen del texto)
    client.delete("/chat/recursos/rec_1", headers=h)            # queda 1 recurso: rec_2
    r2 = _subir(client, sesion_nueva, nombre="b.png").json()
    assert r2["id"] != r1["id"]
    assert {x.id for x in SESIONES[sesion_nueva].borrador.multimedia} == {r1["id"], r2["id"]}


@pytest.mark.parametrize("url,tipo", [
    ("https://youtu.be/abc", "video"),
    ("https://www.youtube.com/watch?v=xyz", "video"),
    ("https://bc.finneg.com/uploads/foto.png?v=2", "imagen"),
    ("https://docs.google.com/document/d/123/edit", "documento"),
    ("https://cdn.finneg.com/manual.pdf#page=3", "documento"),
    ("https://cdn.finneg.com/locucion.mp3", "audio"),
])
def test_alta_por_url_detecta_tipo(client, sesion_nueva, url, tipo):
    tl = SESIONES[sesion_nueva].borrador.texto_limpio
    r = client.post("/chat/recursos/agregar", headers={"X-Session-ID": sesion_nueva}, json={"referencia": url})
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == tipo
    assert r.json()["nombre"]  # derivado de la URL si no se envía
    assert SESIONES[sesion_nueva].borrador.texto_limpio == tl


def test_alta_por_url_validaciones(client, sesion_nueva):
    h = {"X-Session-ID": sesion_nueva}
    post = lambda body: client.post("/chat/recursos/agregar", headers=h, json=body)

    # Esquemas no permitidos
    assert post({"referencia": "javascript:alert(1)"}).status_code == 400
    assert post({"referencia": "ftp://x/archivo.png"}).status_code == 400
    # Enlace no reconocible: pide el tipo; con tipo explícito se acepta
    assert post({"referencia": "https://finneg.com/pagina"}).status_code == 400
    r = post({"referencia": "https://finneg.com/pagina", "tipo": "documento", "nombre": "Ficha"})
    assert r.status_code == 200 and r.json()["tipo"] == "documento" and r.json()["nombre"] == "Ficha"
    # Duplicado (la imagen que ya venía en el texto)
    assert post({"referencia": URL_IMG}).status_code == 409
