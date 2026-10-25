import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.recurso import Recurso
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    EstadoFlujo,
    ItemContenidoAdicional,
)
from baco.server.services.agente_service import (
    ejecutar_skill_plantillas,
    ejecutar_skill_validador,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.excepciones import EstadoInvalidoError
from baco.server.services.orquestador.sesion import (
    SESIONES,
    gestor_sesiones,
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
    buscador.obtener_articulo.return_value = None
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


def test_contenido_adicional_solo_en_enriquecer_o_actualizar():
    """El contenido adicional solo se habilita para enriquecer/actualizar y se prohíbe en 'nuevo'."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id

    # 1. Modo nuevo -> EstadoInvalidoError
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo="Artículo desde cero",
        texto="Texto inicial de prueba",
        texto_limpio="Texto inicial de prueba",
    )
    with pytest.raises(EstadoInvalidoError, match="solo está permitido en flujos de actualizar o enriquecer"):
        gestor_sesiones.agregar_contenido_adicional(sid, "Nota que no debería entrar")

    # 2. Modo enriquecimiento -> permitido
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=123,
        titulo="Artículo a enriquecer",
        texto="Texto base existente",
        texto_limpio="Texto base existente",
    )
    item = gestor_sesiones.agregar_contenido_adicional(sid, "Nuevo paso agregado")
    assert isinstance(item, ItemContenidoAdicional)
    assert item.contenido == "Nuevo paso agregado"
    assert len(sesion.borrador.contenido_adicional) == 1


def test_contenido_adicional_se_guarda_en_seccion_aparte_con_id_tipo_posicion():
    """Cada ítem agregado tiene un ID estable, su tipo/contenido y su posición ordenada."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=456,
        titulo="Enriquecer artículo",
        texto="Texto base",
        texto_limpio="Texto base",
    )

    item1 = gestor_sesiones.agregar_contenido_adicional(sid, "Primer contenido adicional", tipo="texto")
    item2 = gestor_sesiones.agregar_contenido_adicional(sid, "Segundo contenido adicional", tipo="nota")

    assert item1.id.startswith("ca_")
    assert item2.id.startswith("ca_")
    assert item1.id != item2.id

    assert item1.posicion == 0
    assert item1.tipo == "texto"
    assert item1.contenido == "Primer contenido adicional"

    assert item2.posicion == 1
    assert item2.tipo == "nota"
    assert item2.contenido == "Segundo contenido adicional"

    lista = gestor_sesiones.obtener_contenido_adicional(sid)
    assert len(lista) == 2
    assert lista[0].id == item1.id
    assert lista[1].id == item2.id


def test_contenido_adicional_no_modifica_texto_limpio():
    """Invariante: agregar contenido adicional a su sección aparte NO altera texto_limpio."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    texto_limpio_original = (
        "Pasos de configuración:\n"
        "1. Ir al menú contable.\n"
        "2. Guardar [[recurso:rec_1]]."
    )
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=789,
        titulo="Configuración",
        recursos={"rec_1": Recurso(id="rec_1", tipo="imagen", nombre="img", orden=0)},
        texto_limpio=texto_limpio_original,
    )
    sesion.texto_limpio = texto_limpio_original

    # Agregamos múltiples ítems adicionales
    gestor_sesiones.agregar_contenido_adicional(sid, "Anexo 1: Detalles técnicos")
    gestor_sesiones.agregar_contenido_adicional(sid, "Anexo 2: FAQ de soporte")

    # texto_limpio debe mantenerse 100% idéntico
    assert sesion.borrador.texto_limpio == texto_limpio_original
    assert sesion.texto_limpio == texto_limpio_original


def test_skills_no_leen_ni_modifican_contenido_adicional():
    """Las skills de agente (plantillas / validador) operan sobre texto_limpio y no tocan contenido_adicional."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    texto_limpio = "Texto para dar formato oficial con plantilla."
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=101,
        titulo="Instructivo Oficial",
        texto=texto_limpio,
        texto_limpio=texto_limpio,
        tipo_plantilla="instructivo",
        categoria_id=1,
        tags=["instructivo", "sistema"],
    )

    gestor_sesiones.agregar_contenido_adicional(sid, "TEXTO_SECRETO_ADICIONAL_QUE_NO_DEBE_IR_AL_PROMPT")

    mock_baco = MagicMock()
    mock_baco.return_value = "### Pasos a seguir\n\n1. Texto para dar formato oficial con plantilla."

    # Ejecutar skill plantillas
    resultado_plantillas = ejecutar_skill_plantillas(sid, sesion.borrador, mock_baco)

    # Verificar que el prompt enviado al LLM NUNCA incluyó el contenido adicional
    prompt_enviado = mock_baco.call_args[0][0]
    assert "TEXTO_SECRETO_ADICIONAL_QUE_NO_DEBE_IR_AL_PROMPT" not in prompt_enviado

    # Verificar que la sección aparte sigue intacta
    assert len(sesion.borrador.contenido_adicional) == 1
    assert sesion.borrador.contenido_adicional[0].contenido == "TEXTO_SECRETO_ADICIONAL_QUE_NO_DEBE_IR_AL_PROMPT"


def test_endpoints_api_contenido_adicional(client, mock_buscador):
    """Prueba los endpoints HTTP de la API REST para contenido adicional."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    # 1. Sesión en modo 'nuevo' -> POST /chat/contenido-adicional da 403
    r_nuevo = client.post("/chat", json={"mensaje": "Artículo completamente nuevo"}).json()
    sid_nuevo = r_nuevo["session_id"]
    client.post(
        "/chat",
        json={"session_id": sid_nuevo, "accion": "confirmar_texto", "texto": "Este es el cuerpo del nuevo artículo de prueba de longitud adecuada."}
    )

    res_fail = client.post(
        "/chat/contenido-adicional",
        headers={"X-Session-ID": sid_nuevo},
        json={"contenido": "Contenido prohibido en modo nuevo"},
    )
    assert res_fail.status_code == 403

    client.cookies.clear()

    # 2. Sesión en modo 'enriquecimiento' -> POST /chat/contenido-adicional da 200
    sesion_enriq, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid_enriq = sesion_enriq.session_id
    sesion_enriq.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=999,
        titulo="Enriquecer existente",
        texto="Contenido base",
        texto_limpio="Contenido base",
    )

    res_ok = client.post(
        "/chat/contenido-adicional",
        headers={"X-Session-ID": sid_enriq},
        json={"contenido": "Información complementaria 2026", "tipo": "texto"},
    )
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["contenido"] == "Información complementaria 2026"
    assert data["posicion"] == 0
    assert data["id"].startswith("ca_")

    # 3. GET /chat/contenido-adicional lista los ítems agregados
    res_list = client.get("/chat/contenido-adicional", headers={"X-Session-ID": sid_enriq})
    assert res_list.status_code == 200
    items = res_list.json()
    assert len(items) == 1
    assert items[0]["contenido"] == "Información complementaria 2026"


def test_front_boton_agregar_solo_en_enriquecer_o_actualizar():
    """El front solo renderiza el botón '+' si el borrador es enriquecer o actualizar, no en nuevo."""
    from pathlib import Path
    app_js = Path("frontend/js/app.js").read_text(encoding="utf-8")

    # Verifica la condición que habilita el botón
    assert "esEnriquecerOActualizar = b && (b.modo === 'enriquecimiento' || b.modo === 'actualizar' || b.articulo_original_id != null)" in app_js
    assert "if (esEnriquecerOActualizar)" in app_js
    assert 'id="btnAgregarContenido"' in app_js

    # Verifica estilos CSS
    styles_css = Path("frontend/styles.css").read_text(encoding="utf-8")
    assert ".btn-agregar-contenido" in styles_css
    assert ".eib-sec-adicional" in styles_css


def test_eliminar_item_contenido_adicional():
    """Eliminar quita solo el ítem elegido y re-indexa las posiciones restantes."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=123,
        titulo="Artículo",
        texto="Base",
        texto_limpio="Base",
    )

    it1 = gestor_sesiones.agregar_contenido_adicional(sid, "Item 1")
    it2 = gestor_sesiones.agregar_contenido_adicional(sid, "Item 2")
    it3 = gestor_sesiones.agregar_contenido_adicional(sid, "Item 3")

    assert len(sesion.borrador.contenido_adicional) == 3

    # Elimina el ítem del medio
    eliminado = gestor_sesiones.eliminar_item_contenido_adicional(sid, it2.id)
    assert eliminado is True
    assert len(sesion.borrador.contenido_adicional) == 2

    restantes = gestor_sesiones.obtener_contenido_adicional(sid)
    assert [it.id for it in restantes] == [it1.id, it3.id]
    assert restantes[0].posicion == 0
    assert restantes[1].posicion == 1

    # Intentar eliminar un id inexistente da False
    assert gestor_sesiones.eliminar_item_contenido_adicional(sid, "no_existe") is False


def test_reordenar_contenido_adicional_persiste_orden():
    """Reordenar persiste el nuevo orden en el borrador y actualiza sus posiciones."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=123,
        titulo="Artículo",
        texto="Base",
        texto_limpio="Base",
    )

    it1 = gestor_sesiones.agregar_contenido_adicional(sid, "Paso A")
    it2 = gestor_sesiones.agregar_contenido_adicional(sid, "Paso B")
    it3 = gestor_sesiones.agregar_contenido_adicional(sid, "Paso C")

    # Invertimos el orden: Paso C, Paso A, Paso B
    nuevo_orden = [it3.id, it1.id, it2.id]
    reordenados = gestor_sesiones.reordenar_contenido_adicional(sid, nuevo_orden)

    assert [it.id for it in reordenados] == nuevo_orden
    assert reordenados[0].posicion == 0
    assert reordenados[1].posicion == 1
    assert reordenados[2].posicion == 2

    # Persiste en la sesión
    en_sesion = gestor_sesiones.obtener_contenido_adicional(sid)
    assert [it.id for it in en_sesion] == nuevo_orden


def test_eliminar_o_reordenar_invalida_conformidad():
    """Cualquier cambio (eliminar, reordenar o agregar) en contenido_adicional invalida la conformidad."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.estado = EstadoFlujo.CONFORMIDAD_USUARIO
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=123,
        titulo="Artículo",
        texto="Base",
        texto_limpio="Base",
        conforme=True,
        conforme_en="2026-10-24T12:00:00Z",
    )

    it1 = gestor_sesiones.agregar_contenido_adicional(sid, "Item 1")
    it2 = gestor_sesiones.agregar_contenido_adicional(sid, "Item 2")

    # 1. Al agregar con conformidad activa, se invalida
    assert sesion.borrador.conforme is False
    assert sesion.borrador.conforme_en is None
    assert sesion.borrador.conformidad_invalidada is True
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR

    # Restablecemos conformidad simulada
    sesion.estado = EstadoFlujo.CONFORMIDAD_USUARIO
    sesion.borrador.conforme = True
    sesion.borrador.conforme_en = "2026-10-24T12:30:00Z"
    sesion.borrador.conformidad_invalidada = False

    # 2. Al reordenar, se invalida
    gestor_sesiones.reordenar_contenido_adicional(sid, [it2.id, it1.id])
    assert sesion.borrador.conforme is False
    assert sesion.borrador.conforme_en is None
    assert sesion.borrador.conformidad_invalidada is True
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR

    # Restablecemos conformidad simulada
    sesion.estado = EstadoFlujo.CONFORMIDAD_USUARIO
    sesion.borrador.conforme = True
    sesion.borrador.conforme_en = "2026-10-24T12:45:00Z"
    sesion.borrador.conformidad_invalidada = False

    # 3. Al eliminar, se invalida
    gestor_sesiones.eliminar_item_contenido_adicional(sid, it1.id)
    assert sesion.borrador.conforme is False
    assert sesion.borrador.conforme_en is None
    assert sesion.borrador.conformidad_invalidada is True
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR


def test_endpoints_api_eliminar_y_reordenar(client):
    """Prueba los endpoints HTTP para eliminar y reordenar contenido adicional."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=888,
        titulo="Enriquecer API",
        texto="Base API",
        texto_limpio="Base API",
    )

    it1 = gestor_sesiones.agregar_contenido_adicional(sid, "Nota 1")
    it2 = gestor_sesiones.agregar_contenido_adicional(sid, "Nota 2")

    # 1. Reordenar vía PUT
    res_reord = client.put(
        "/chat/contenido-adicional/reordenar",
        headers={"X-Session-ID": sid},
        json={"orden_ids": [it2.id, it1.id]},
    )
    assert res_reord.status_code == 200
    assert [x["id"] for x in res_reord.json()] == [it2.id, it1.id]

    # 2. Eliminar vía DELETE
    res_del = client.delete(
        f"/chat/contenido-adicional/{it1.id}",
        headers={"X-Session-ID": sid},
    )
    assert res_del.status_code == 200
    assert res_del.json() == {"status": "ok", "eliminado": it1.id}

    # 3. Eliminar inexistente -> 404
    res_del_404 = client.delete(
        "/chat/contenido-adicional/no_existe",
        headers={"X-Session-ID": sid},
    )
    assert res_del_404.status_code == 404


def test_front_botones_eliminar_y_reordenar():
    """Verifica que el front incluya la 'x' para eliminar y los botones para reordenar."""
    from pathlib import Path
    app_js = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert 'class="btn-eliminar-item"' in app_js
    assert 'class="eib-reordenar-btns"' in app_js
    assert 'class="btn-mover-item"' in app_js

    styles_css = Path("frontend/styles.css").read_text(encoding="utf-8")
    assert ".btn-eliminar-item" in styles_css
    assert ".eib-reordenar-btns" in styles_css
    assert ".btn-mover-item" in styles_css


def test_descartar_borrador_vacia_contenido_adicional():
    """Al descartar el borrador, contenido_adicional se vacía completamente junto con el borrador."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=123,
        titulo="Artículo a descartar",
        texto="Texto inicial",
        texto_limpio="Texto inicial",
    )
    gestor_sesiones.agregar_contenido_adicional(sid, "Nota adicional 1")
    gestor_sesiones.agregar_contenido_adicional(sid, "Nota adicional 2")

    assert len(gestor_sesiones.obtener_contenido_adicional(sid)) == 2

    # Descartar borrador
    gestor_sesiones.descartar_borrador(sid)

    assert sesion.borrador is None
    assert sesion.contenido_adicional == []
    assert gestor_sesiones.obtener_contenido_adicional(sid) == []


@pytest.mark.anyio
async def test_reiniciar_sesion_vacia_contenido_adicional(mock_buscador):
    """Al reiniciar la sesión, se vacía contenido_adicional y se vuelve al estado inicial."""
    from baco.server.schemas.chat_orquestado import ChatOrquestadorRequest
    from baco.server.services.orquestador import manejar_turno

    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=123,
        titulo="Artículo previo",
        texto="Base",
        texto_limpio="Base",
    )
    gestor_sesiones.agregar_contenido_adicional(sid, "Nota a olvidar")

    assert len(sesion.contenido_adicional) == 1

    # Ejecuta acción reiniciar
    req = ChatOrquestadorRequest(session_id=sid, accion="reiniciar")
    resp = await manejar_turno(req, mock_buscador)

    # La nueva sesión no tiene contenido adicional ni borrador previo
    sesion_nueva = gestor_sesiones.obtener_sesion(resp.session_id)
    assert sesion_nueva.borrador is None
    assert sesion_nueva.contenido_adicional == []
    assert resp.borrador is None


@pytest.mark.anyio
async def test_descartar_enriquecimiento_en_esperando_texto_vacia_contenido_adicional(mock_buscador):
    """Al elegir descartar durante ESPERANDO_TEXTO con borrador de enriquecimiento, se vacía contenido_adicional."""
    from baco.server.schemas.chat_orquestado import ChatOrquestadorRequest
    from baco.server.services.orquestador import manejar_turno

    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=555,
        titulo="Enriquecer algo",
        texto="Texto base",
        texto_limpio="Texto base",
    )
    gestor_sesiones.agregar_contenido_adicional(sid, "Nota previa")
    assert len(sesion.contenido_adicional) == 1

    req = ChatOrquestadorRequest(session_id=sid, accion="descartar")
    resp = await manejar_turno(req, mock_buscador)

    assert sesion.borrador is None
    assert sesion.contenido_adicional == []


@pytest.mark.anyio
async def test_confirmar_rechazo_vacia_contenido_adicional(mock_buscador):
    """Al confirmar el rechazo/descarte en revisión, contenido_adicional se limpia por completo."""
    from baco.server.schemas.chat_orquestado import ChatOrquestadorRequest
    from baco.server.services.orquestador import manejar_turno

    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.estado = EstadoFlujo.REVISION_BORRADOR
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=777,
        titulo="Revisión",
        texto="Base texto",
        texto_limpio="Base texto",
    )
    gestor_sesiones.agregar_contenido_adicional(sid, "Nota descartable")
    assert len(sesion.contenido_adicional) == 1

    req = ChatOrquestadorRequest(session_id=sid, accion="confirmar_rechazo")
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.RECHAZADO
    assert sesion.borrador is None
    assert sesion.contenido_adicional == []


def test_modificar_item_contenido_adicional_actualiza_y_invalida_conformidad():
    """Modificar un ítem actualiza su contenido, invalida la conformidad y no toca texto_limpio."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    sesion.estado = EstadoFlujo.CONFORMIDAD_USUARIO
    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=888,
        titulo="Enriquecer con notas",
        texto="Texto base limpio",
        texto_limpio="Texto base limpio",
        conforme=True,
        conforme_en="2026-10-24T12:00:00Z",
    )
    item = gestor_sesiones.agregar_contenido_adicional(sid, "Texto inicial")

    # Modificar el ítem
    item_mod = gestor_sesiones.modificar_item_contenido_adicional(
        sid, item.id, "Texto modificado y corregido", nuevo_tipo="nota"
    )

    assert item_mod.id == item.id
    assert item_mod.contenido == "Texto modificado y corregido"
    assert item_mod.tipo == "nota"

    # La conformidad debe invalidarse
    assert sesion.borrador.conforme is False
    assert sesion.borrador.conforme_en is None
    assert sesion.borrador.conformidad_invalidada is True
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR

    # El texto limpio no debe ser modificado
    assert sesion.borrador.texto_limpio == "Texto base limpio"


def test_api_modificar_contenido_adicional_endpoints(client):
    """Prueba los endpoints PUT y PATCH /chat/contenido-adicional/{item_id}."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id
    client.cookies.set("baco_session", sid)

    sesion.borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=999,
        titulo="Artículo API",
        texto="Texto base",
        texto_limpio="Texto base",
    )
    item = gestor_sesiones.agregar_contenido_adicional(sid, "Contenido inicial API")

    # PUT
    res_put = client.put(
        f"/chat/contenido-adicional/{item.id}",
        json={"contenido": "Contenido actualizado vía PUT", "tipo": "nota"}
    )
    assert res_put.status_code == 200
    data_put = res_put.json()
    assert data_put["id"] == item.id
    assert data_put["contenido"] == "Contenido actualizado vía PUT"
    assert data_put["tipo"] == "nota"

    # PATCH
    res_patch = client.patch(
        f"/chat/contenido-adicional/{item.id}",
        json={"contenido": "Contenido actualizado vía PATCH"}
    )
    assert res_patch.status_code == 200
    data_patch = res_patch.json()
    assert data_patch["contenido"] == "Contenido actualizado vía PATCH"

    # Item inexistente -> 400
    res_err = client.put(
        "/chat/contenido-adicional/no_existe_id",
        json={"contenido": "Algo"}
    )
    assert res_err.status_code == 400

