from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados, get_baco_agent
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.services.orquestador import (
    manejar_turno,
    obtener_borrador_conforme,
    actualizar_borrador_texto,
)
from baco.server.services.orquestador.mensajes import MENSAJE_BIENVENIDA
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import validar_borrador as _validar_borrador
from baco.server.config_limites import (
    TEXTO_MAX,
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)
from baco.server.schemas.articulo import ArticuloSchema
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados

TEXTO_VALIDO = (
    "Para configurar el punto de venta electrónico en el sistema Finnegans ERP es necesario ingresar "
    "al maestro de puntos de venta dentro del módulo de Ventas, asociar el certificado digital vigente "
    "otorgado por AFIP y verificar que el tipo de emisión esté habilitado para comprobantes electrónicos."
)


@pytest.fixture(autouse=True)
def limpiar_sesiones():
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
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as test_client:
            yield test_client
    app.dependency_overrides.clear()


def test_camino_coincidencia_titulo_enriquecer_con_datos_db_valida_y_aprueba(client, mock_buscador):
    # 1. Bienvenida precargada
    r1 = client.post("/chat", json={}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TITULO
    assert r1["mensaje"] == MENSAJE_BIENVENIDA

    # 2. Envía título -> buscar_duplicados solo por título (mejor candidato único)
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Ya existe un artículo con exactamente este título",
        "link": "https://bc.finneg.com/t/101",
        "coincidencias": [(101, "Cómo Configurar Punto de Venta AFIP", "https://bc.finneg.com/t/101")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 101,
        "titulo": "Cómo Configurar Punto de Venta AFIP",
        "url": "https://bc.finneg.com/t/101",
        "texto": TEXTO_VALIDO,
        "categoria_id": 5,
        "tags": ["instructivo", "ventas"],
    }
    r2 = client.post("/chat", json={"session_id": sid, "mensaje": "Configurar Punto de Venta AFIP"}).json()
    assert r2["estado"] == EstadoFlujo.DECISION_TITULO
    assert len(r2["coincidencias"]) == 1
    assert r2["coincidencias"][0]["id"] == 101
    mock_buscador.evaluar_texto.assert_not_called()

    # 3. Acepta enriquecer -> ofrece ingresar texto para enriquecer
    r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    mock_buscador.obtener_articulo.assert_called_once_with(101)
    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert "Cargué el texto del artículo #101" in r3["mensaje"]

    # 4. Envía el texto con aportes/modificaciones -> avanza a REVISION_BORRADOR
    r3b = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r3b["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3b["borrador"]["modo"] == "enriquecimiento"
    assert r3b["borrador"]["articulo_original_id"] == 101
    assert r3b["borrador"]["texto_alineado_discourse"] == TEXTO_VALIDO
    assert r3b["borrador"]["tipo_plantilla"] == "instructivo"
    assert r3b["borrador"]["tags"] == ["instructivo", "ventas"]
    assert r3b["validacion"]["valido"] is True

    # Mientras no esté CONFORMIDAD_USUARIO, no se expone el borrador externo (409 Conflict si existe pero no está en conformidad)
    assert obtener_borrador_conforme(sid) is None
    assert client.get("/chat/borrador").status_code == 409
    with TestClient(app, headers={"X-API-Key": API_KEY}) as c_inexistente:
        assert c_inexistente.get("/chat/borrador", headers={"X-Session-ID": "inexistente-123"}).status_code == 404

    # Acepta los metadatos heredados de la versión anterior
    client.post("/chat", json={"session_id": sid, "accion": "aceptar"})

    # 4. Revisión humana final -> da conformidad y garantiza sanitización determinista
    r4 = client.post("/chat", json={"session_id": sid, "accion": "conforme"}).json()
    assert r4["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO

    resp_borrador = client.get("/chat/borrador")
    assert resp_borrador.status_code == 200
    datos_b = resp_borrador.json()
    assert datos_b["titulo"] == "Configurar Punto de Venta AFIP"  # sin el 'Cómo ' redundante
    assert datos_b["texto_alineado_discourse"] == TEXTO_VALIDO
    assert datos_b["tipo_plantilla"] == "instructivo"


def test_camino_descarta_titulo_duplicado_en_texto_y_enriquece(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Encontramos un artículo muy similar",
        "link": "https://bc.finneg.com/t/202",
        "coincidencias": [(202, "Configuración de Puntos de Venta", "https://bc.finneg.com/t/202")],
    }
    r1 = client.post("/chat", json={"mensaje": "Configurar Punto de Venta Electrónico"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # Descarta coincidencia de título -> pide texto
    r2 = client.post("/chat", json={"session_id": sid, "accion": "descartar"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # Envía texto -> detecta duplicado con el texto
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Ya existe un artículo que explica prácticamente lo mismo",
        "link": "https://bc.finneg.com/t/305",
        "coincidencias": [(305, "Asociar Certificado AFIP", "https://bc.finneg.com/t/305")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 305,
        "titulo": "Asociar Certificado AFIP",
        "url": "https://bc.finneg.com/t/305",
        "texto": TEXTO_VALIDO,
        "categoria_id": 3,
        "tags": ["soluciones", "afip"],
    }
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r3["estado"] == EstadoFlujo.DECISION_TEXTO
    assert r3["coincidencias"][0]["id"] == 305

    # Acepta enriquecer -> pasa a ESPERANDO_TEXTO en modo enriquecimiento
    r4 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r4["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r4["borrador"]["modo"] == "enriquecimiento"
    assert r4["borrador"]["articulo_original_id"] == 305

    # Confirma texto -> avanza a REVISION_BORRADOR con datos de DB + validar_articulo
    r5 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r4["borrador"]["texto_alineado_discourse"]}).json()
    assert r5["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r5["borrador"]["tipo_plantilla"] == "soluciones"
    assert r5["validacion"]["valido"] is True


def test_camino_articulo_nuevo_pide_plantilla_y_metadatos_sanitiza_y_aprueba(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Similar",
        "link": "https://bc.finneg.com/t/401",
        "coincidencias": [(401, "Novedades ERP Mayo 2026", "https://bc.finneg.com/t/401")],
    }
    sid = client.post("/chat", json={"mensaje": "Novedades ERP Junio 2026"}).json()["session_id"]
    client.post("/chat", json={"session_id": sid, "mensaje": "no"})

    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Similar texto",
        "link": "https://bc.finneg.com/t/402",
        "coincidencias": [(402, "Configuración de Punto de Venta", "https://bc.finneg.com/t/402")],
    }
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO + " CUIT 20-30405060-9."})

    # Rechaza también la coincidencia de texto -> pide primero tipo de plantilla (Variante C1 - Parte A)
    r_plant = client.post("/chat", json={"session_id": sid, "accion": "continuar"}).json()
    assert r_plant["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r_plant["opciones"] == ["instructivo", "soluciones", "volver"]

    # Elige plantilla 'instructivo' -> pasa a REVISION_BORRADOR y luego 'continuar_revision' pide metadatos
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_BORRADOR
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r_meta["borrador"]["tipo_plantilla"] == "instructivo"

    # Ingresa tags temáticos y categoría -> corre validar_articulo y pasa a REVISION_BORRADOR
    r_val = client.post("/chat", json={"session_id": sid, "mensaje": "ventas, facturacion, 4"}).json()
    assert r_val["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_val["borrador"]["modo"] == "nuevo"
    assert r_val["borrador"]["tags"] == ["instructivo", "ventas", "facturacion"]
    assert r_val["borrador"]["categoria_id"] == 4
    # Ahora es autosanitizante: ya reemplazó el CUIT automáticamente y es válido con aviso
    assert r_val["validacion"]["valido"] is True
    assert "[CUIT_OCULTO]" in r_val["borrador"]["texto_alineado_discourse"]

    r_ok = client.post("/chat", json={"session_id": sid, "accion": "conforme"}).json()
    assert r_ok["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO


def test_camino_sin_coincidencias_plantilla_metadatos_y_rechazo_humano(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    r1 = client.post("/chat", json={"mensaje": "Integración de API de Cobranzas Bancarias"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    mock_buscador.evaluar_texto.return_value = None
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

    r3 = client.post("/chat", json={"session_id": sid, "mensaje": "soluciones"}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r3 = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    r4 = client.post("/chat", json={"session_id": sid, "tags": ["cobranzas", "bancos"], "categoria_id": 1}).json()
    assert r4["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r4["borrador"]["modo"] == "nuevo"
    assert r4["borrador"]["tipo_plantilla"] == "soluciones"
    assert r4["borrador"]["tags"] == ["soluciones", "cobranzas", "bancos"]
    assert r4["validacion"]["valido"] is True

    r5 = client.post("/chat", json={"session_id": sid, "accion": "rechazar"}).json()
    assert r5["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "confirmar_rechazo" in r5["opciones"]

    r6 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_rechazo"}).json()
    assert r6["estado"] == EstadoFlujo.RECHAZADO


def test_validacion_cotas_titulo_esperando_titulo(client):
    # 1. Título menor a 15 caracteres
    r_corto = client.post("/chat", json={"mensaje": "Factura AFIP"}).json()
    assert r_corto["estado"] == EstadoFlujo.ESPERANDO_TITULO
    assert "al menos 15 caracteres" in r_corto["mensaje"]

    # 2. Título mayor a 255 caracteres
    r_largo = client.post("/chat", json={"mensaje": "A" * 256}).json()
    assert r_largo["estado"] == EstadoFlujo.ESPERANDO_TITULO
    assert f"supera los {TITULO_MAX} caracteres" in r_largo["mensaje"]


def test_validacion_cotas_texto_esperando_texto(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    r1 = client.post("/chat", json={"mensaje": "Título Válido de Prueba con Más de 15 Caracteres"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # Texto menor a 20 caracteres
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": "Texto muy corto"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert "al menos 20 caracteres" in r2["mensaje"]


def test_edicion_borrador_con_longitud_invalida_no_rompe_y_muestra_bloqueante(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    sid = client.post("/chat", json={"mensaje": "Título Inicial Válido Para el Borrador"}).json()["session_id"]

    mock_buscador.evaluar_texto.return_value = None
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "mensaje": "instructivo"})
    r_val = client.post("/chat", json={"session_id": sid, "tags": ["instructivo", "ventas"], "categoria_id": 1}).json()
    assert r_val["estado"] == EstadoFlujo.REVISION_BORRADOR

    # Editamos el borrador con un título inválido (< 15 caracteres)
    r_edit = client.post("/chat", json={"session_id": sid, "accion": "editar", "titulo": "Corto"}).json()
    assert r_edit["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "puntos obligatorios pendientes" in r_edit["mensaje"]
    assert r_edit["validacion"]["valido"] is False


def test_articulo_schema_texto_max_plus_one_lanza_validation_error():
    with pytest.raises(ValidationError) as exc:
        ArticuloSchema(id=1, titulo="A" * 20, texto="A" * (TEXTO_MAX_PERCENTIL_99 + 1))
    assert "texto" in str(exc.value)


def test_articulo_schema_texto_exactamente_texto_max_es_valido():
    art = ArticuloSchema(id=1, titulo="A" * 20, texto="A" * TEXTO_MAX)
    assert len(art.texto) == TEXTO_MAX


def test_articulo_schema_texto_exactamente_texto_max_percentil_99_es_valido():
    art = ArticuloSchema(id=1, titulo="A" * 20, texto="A" * TEXTO_MAX_PERCENTIL_99)
    assert len(art.texto) == TEXTO_MAX_PERCENTIL_99


def test_chat_request_texto_max_plus_one_rechazado_con_mensaje_claro():
    with pytest.raises(ValidationError) as exc:
        ChatOrquestadorRequest(texto="A" * (TEXTO_MAX_PERCENTIL_99 + 1))
    assert f"El texto supera los {TEXTO_MAX_PERCENTIL_99} caracteres. Dividilo o resumilo." in str(exc.value)


def test_chat_request_texto_exactamente_texto_max_aceptado():
    req = ChatOrquestadorRequest(texto="A" * TEXTO_MAX)
    assert len(req.texto) == TEXTO_MAX


def test_chat_request_texto_exactamente_texto_max_percentil_99_aceptado():
    req = ChatOrquestadorRequest(texto="A" * TEXTO_MAX_PERCENTIL_99)
    assert len(req.texto) == TEXTO_MAX_PERCENTIL_99


@pytest.mark.anyio
async def test_orquestador_texto_demasiado_largo_en_esperando_texto_no_cambia_estado(mock_buscador):
    sid = "test-sid-largo"
    sesion = SesionChat(session_id=sid, estado=EstadoFlujo.ESPERANDO_TEXTO, titulo="A" * 20)
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest.model_construct(session_id=sid, texto="A" * (TEXTO_MAX_PERCENTIL_99 + 10))
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO
    assert f"El texto supera los {TEXTO_MAX_PERCENTIL_99} caracteres" in resp.mensaje


@pytest.mark.anyio
async def test_orquestador_texto_demasiado_largo_en_edicion_revision_borrador_no_cambia_estado(mock_buscador):
    sid = "test-sid-edit-largo"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="A" * 20,
        texto=TEXTO_VALIDO,
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
    )
    sesion = SesionChat(session_id=sid, estado=EstadoFlujo.REVISION_BORRADOR, borrador=borrador)
    SESIONES[sid] = sesion

    req = ChatOrquestadorRequest.model_construct(session_id=sid, accion="editar", texto="A" * (TEXTO_MAX_PERCENTIL_99 + 10))
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert f"El texto supera los {TEXTO_MAX_PERCENTIL_99} caracteres" in resp.mensaje
    assert sesion.borrador.texto_alineado_discourse == TEXTO_VALIDO


def test_validar_borrador_error_en_otro_campo_menciona_ese_campo():
    sesion = SesionChat(
        session_id="test-campo-invalido",
        borrador=BorradorSesion.model_construct(
            modo="nuevo",
            titulo="A" * 20,
            texto=TEXTO_VALIDO,
            articulo_original_id="no_es_un_int",
            tags=[],
        ),
    )
    msg, ops = _validar_borrador(sesion)
    assert sesion.validacion.valido is False
    assert any("id" in (f.field or "") for f in sesion.validacion.findings)
    assert not any("longitud mínima requerida" in f.description for f in sesion.validacion.findings)


def test_enriquecer_articulo_existente_texto_db_supera_texto_max_rechazado_sin_borrador(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Título Existente en BD", "https://bc.finneg.com/t/999")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 999,
        "titulo": "Título Existente en BD",
        "url": "https://bc.finneg.com/t/999",
        "texto": "X" * (TEXTO_MAX_PERCENTIL_99 + 1),
        "categoria_id": 1,
        "tags": ["instructivo", "general"],
    }

    r1 = client.post("/chat", json={"mensaje": "Título Existente en BD"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # Intenta enriquecer -> texto_db supera TEXTO_MAX_PERCENTIL_99
    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r2["estado"] == EstadoFlujo.DECISION_TITULO
    assert r2["borrador"] is None
    assert r2["opciones"] == ["descartar", "reiniciar"]
    assert f"Este artículo es muy largo para editarlo desde el chat (supera los {TEXTO_MAX_PERCENTIL_99} caracteres). Podés modificarlo directamente en la plataforma." in r2["mensaje"]


def test_enriquecer_articulo_existente_texto_db_exactamente_texto_max_crea_borrador_completo(client, mock_buscador):
    texto_exacto = "Z" * TEXTO_MAX
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/998",
        "coincidencias": [(998, "Título Existente Exacto", "https://bc.finneg.com/t/998")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 998,
        "titulo": "Título Existente Exacto",
        "url": "https://bc.finneg.com/t/998",
        "texto": texto_exacto,
        "categoria_id": 1,
        "tags": ["instructivo", "general"],
    }

    r1 = client.post("/chat", json={"mensaje": "Título Existente Exacto"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    r2b = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_exacto}).json()
    assert r2b["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r2b["borrador"] is not None
    assert len(r2b["borrador"]["texto_alineado_discourse"]) == TEXTO_MAX
    assert r2b["borrador"]["texto_alineado_discourse"] == texto_exacto


def test_aplicar_plantilla_con_session_id_inexistente_retorna_404(client):
    client.cookies.clear()
    resp = client.post("/chat/aplicar-plantilla", headers={"X-Session-ID": "sesion-inexistente-1234"})
    assert resp.status_code == 404
    assert "No existe la sesión" in resp.json()["detail"]


def test_aplicar_plantilla_con_session_id_pendiente_retorna_409(client):
    r1 = client.post("/chat", json={}).json()
    sid = r1["session_id"]

    resp = client.post("/chat/aplicar-plantilla")
    assert resp.status_code == 409
    assert "El borrador no está en estado CONFORMIDAD_USUARIO" in resp.json()["detail"]


def test_aplicar_plantilla_conforme_inyecta_prompt_y_sobreescribe_borrador(client):
    sid = "sesion-conforme-test"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Configurar Facturación Electrónica",
        texto=TEXTO_VALIDO,
        categoria_id=5,
        tags=["instructivo", "ventas"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Facturación Electrónica",
            texto=TEXTO_VALIDO,
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
            categoria_id=5,
            tags=["instructivo", "ventas"]
        )
    )

    plantilla_markdown = "## Objetivo\nInstructivo de facturación...\n\n## Pasos\n1. Ingresar..."
    mock_agente = MagicMock(return_value=plantilla_markdown)
    app.dependency_overrides[get_baco_agent] = lambda: mock_agente

    try:
        resp = client.post("/chat/aplicar-plantilla", headers={"X-Session-ID": sid})
    finally:
        app.dependency_overrides.pop(get_baco_agent, None)

    assert resp.status_code == 200
    assert resp.json()["response"] == plantilla_markdown

    # Verificar que el prompt inyectado a Baco contiene la skill y los datos del borrador en conformidad
    prompt_inyectado = mock_agente.call_args[0][0]
    assert "Skill solicitada: plantillas" in prompt_inyectado
    assert "Plantilla a aplicar: instructivo" in prompt_inyectado
    assert "Configurar Facturación Electrónica" in prompt_inyectado
    assert TEXTO_VALIDO in prompt_inyectado

    # Al modificarse el texto con la skill, la conformidad previa se invalida
    assert SESIONES[sid].borrador.conforme is False
    assert SESIONES[sid].borrador.conforme_en is None
    assert SESIONES[sid].estado == EstadoFlujo.REVISION_BORRADOR
    assert SESIONES[sid].borrador.texto_alineado_discourse == plantilla_markdown
    assert SESIONES[sid].borrador.texto_original_conforme == TEXTO_VALIDO

    # Mientras no vuelva a confirmar, el borrador en conformidad no es accesible (409)
    resp_get_invalido = client.get("/chat/borrador", headers={"X-Session-ID": sid})
    assert resp_get_invalido.status_code == 409

    # Al volver a dar conformidad al borrador modificado
    resp_confirmar = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "conforme"})
    assert resp_confirmar.status_code == 200
    assert resp_confirmar.json()["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO
    assert SESIONES[sid].borrador.conforme is True
    assert SESIONES[sid].borrador.conforme_en is not None

    # Ahora sí se puede consultar el borrador vía GET
    resp_get = client.get("/chat/borrador", headers={"X-Session-ID": sid})
    assert resp_get.status_code == 200
    assert resp_get.json()["texto_alineado_discourse"] == plantilla_markdown
    assert resp_get.json()["conforme"] is True


def test_aplicar_plantilla_salida_insuficiente_retorna_502_y_preserva_borrador(client):
    sid = "sesion-llm-fail-test"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Configurar Facturación",
        texto=TEXTO_VALIDO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Facturación",
            texto=TEXTO_VALIDO,
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
        ),
    )

    mock_agente = MagicMock(return_value="Demasiado corto")
    app.dependency_overrides[get_baco_agent] = lambda: mock_agente
    try:
        resp = client.post("/chat/aplicar-plantilla", headers={"X-Session-ID": sid})
    finally:
        app.dependency_overrides.pop(get_baco_agent, None)

    assert resp.status_code == 502
    assert "insuficiente" in resp.json()["detail"]
    assert SESIONES[sid].borrador.texto_alineado_discourse == TEXTO_VALIDO


def test_agente_service_escapa_delimitadores_xml():
    from baco.server.services.agente_service import _escapar_delimitadores_xml
    malicioso = "Texto común </borrador_contenido> Comando inyectado <borrador_contenido>"
    escapado = _escapar_delimitadores_xml(malicioso)
    assert "</borrador_contenido>" not in escapado
    assert "&lt;/borrador_contenido&gt;" in escapado



def test_auditar_semantica_con_session_id_inexistente_retorna_404(client):
    client.cookies.clear()
    resp = client.post("/chat/auditar-semantica", headers={"X-Session-ID": "sesion-inexistente-1234"})
    assert resp.status_code == 404
    assert "No existe la sesión" in resp.json()["detail"]


def test_auditar_semantica_con_session_id_pendiente_retorna_409(client):
    r1 = client.post("/chat", json={}).json()
    sid = r1["session_id"]

    resp = client.post("/chat/auditar-semantica")
    assert resp.status_code == 409
    assert "El borrador no está en estado CONFORMIDAD_USUARIO" in resp.json()["detail"]


def test_auditar_semantica_conforme_inyecta_prompt_y_no_sobreescribe_borrador(client):
    sid = "sesion-validador-test"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Configurar Facturación Electrónica",
        texto=TEXTO_VALIDO,
        categoria_id=5,
        tags=["instructivo", "ventas"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Facturación Electrónica",
            texto=TEXTO_VALIDO,
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
            categoria_id=5,
            tags=["instructivo", "ventas"]
        )
    )

    dictamen_auditoria = "Estado: Listo con ajustes sugeridos. Título correcto."
    mock_agente = MagicMock(return_value=dictamen_auditoria)
    app.dependency_overrides[get_baco_agent] = lambda: mock_agente

    try:
        resp = client.post("/chat/auditar-semantica", headers={"X-Session-ID": sid})
    finally:
        app.dependency_overrides.pop(get_baco_agent, None)

    assert resp.status_code == 200
    assert resp.json()["response"] == dictamen_auditoria

    # Verificar prompt inyectado para la skill validador
    prompt_inyectado = mock_agente.call_args[0][0]
    assert "Skill solicitada: validador" in prompt_inyectado
    assert "Categoría / Módulo ERP: 5" in prompt_inyectado
    assert "Tags: instructivo, ventas" in prompt_inyectado
    assert "Configurar Facturación Electrónica" in prompt_inyectado
    assert TEXTO_VALIDO in prompt_inyectado

    # Verificar que para auditar-semantica NO se sobreescribe el texto del borrador
    assert SESIONES[sid].borrador.texto_alineado_discourse == TEXTO_VALIDO


def test_exhaustividad_y_completitud_state_handlers():
    from baco.server.schemas.chat_orquestado import EstadoFlujo
    from baco.server.services.orquestador.handlers import STATE_HANDLERS

    estados_terminales = {EstadoFlujo.CONFORMIDAD_USUARIO, EstadoFlujo.RECHAZADO}
    estados_activos = set(EstadoFlujo) - estados_terminales

    assert set(STATE_HANDLERS.keys()) == estados_activos, (
        f"Faltan handlers en STATE_HANDLERS: {estados_activos - set(STATE_HANDLERS.keys())}"
    )

    for estado, handler in STATE_HANDLERS.items():
        assert callable(handler), f"El handler para el estado {estado} debe ser una función ejecutable."


def test_flujo_completo_con_cookies_sin_session_id_en_front(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {"mensaje": "Sin coincidencias", "coincidencias": []}
    mock_buscador.evaluar_texto.return_value = {"mensaje": "Sin coincidencias", "coincidencias": []}

    mock_agente = MagicMock(return_value="## Objetivo\nInstructivo oficial maquetado exitosamente por Baco.")
    app.dependency_overrides[get_baco_agent] = lambda: mock_agente
    try:
        # 1. Inicio de chat sin session_id (el servidor setea la cookie baco_session)
        r1 = client.post("/chat", json={"mensaje": "Cómo configurar listas de precios mayoristas"})
        assert r1.status_code == 200
        assert "baco_session" in client.cookies
        cookie_sid = client.cookies["baco_session"]
        assert r1.json()["session_id"] == cookie_sid

        # 2. Enviar texto y tags sin session_id (TestClient envía la cookie automáticamente)
        r2 = client.post(
            "/chat",
            json={
                "accion": "confirmar_texto",
                "texto": TEXTO_VALIDO,
                "tags": ["instructivo", "ventas"],
                "categoria_id": 5,
            },
        )
        assert r2.status_code == 200
        assert r2.json()["estado"] == EstadoFlujo.REVISION_BORRADOR

        # Nuevo flujo: 'continuar_revision' cierra la revisión intermedia (metadatos completos -> revisión final)
        r_cont = client.post("/chat", json={"accion": "continuar_revision"})
        assert r_cont.json()["estado"] == EstadoFlujo.REVISION_BORRADOR

        # 3. Dar conformidad al borrador sin session_id
        r3 = client.post("/chat", json={"accion": "conforme"})
        assert r3.status_code == 200
        assert r3.json()["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO

        # 4. GET /chat/borrador sin session_id en path ni query
        r4 = client.get("/chat/borrador")
        assert r4.status_code == 200
        assert r4.json()["titulo"] == "Configurar listas de precios mayoristas"

        # Nuevo flujo: en la revisión final las skills solo se rehabilitan si el texto cambió
        client.post("/chat", json={"accion": "editar", "texto": TEXTO_VALIDO + " Ajuste final del redactor."})

        # 5. POST /chat/aplicar-plantilla sin session_id en path
        r5 = client.post("/chat/aplicar-plantilla")
        assert r5.status_code == 200
        assert "Instructivo oficial" in r5.json()["response"]

        # Al modificar el texto con la plantilla, la conformidad se invalida:
        assert SESIONES[cookie_sid].borrador.conforme is False
        assert SESIONES[cookie_sid].estado == EstadoFlujo.REVISION_BORRADOR

        # El usuario vuelve a confirmar el borrador con la plantilla aplicada
        r_reconf = client.post("/chat", json={"accion": "conforme"})
        assert r_reconf.status_code == 200
        assert r_reconf.json()["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO
        assert SESIONES[cookie_sid].borrador.conforme is True

        # 6. POST /chat/auditar-semantica sin session_id en path
        r6 = client.post("/chat/auditar-semantica")
        assert r6.status_code == 200

        # 7. Cliente limpio sin cookies falla con 401
        cliente_limpio = TestClient(app, headers={"X-API-Key": API_KEY})
        r7 = cliente_limpio.get("/chat/borrador")
        assert r7.status_code == 401
        assert "No se encontró una sesión activa" in r7.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_baco_agent, None)


def test_id_desconocido_genera_sesion_nueva_y_avisa_expiracion(client):
    id_desconocido = "sesion-inexistente-o-expirada"
    client.cookies.set("baco_session", id_desconocido)

    resp = client.post("/chat", json={"mensaje": "Hola de nuevo"})
    assert resp.status_code == 200
    data = resp.json()
    assert "la sesión se cerró por inactividad" in data["mensaje"]
    assert data["session_id"] != id_desconocido
    assert len(data["session_id"]) >= 32
    assert data["estado"] == EstadoFlujo.ESPERANDO_TITULO


def test_accion_reiniciar_rota_session_id(client):
    r1 = client.post("/chat", json={}).json()
    sid1 = r1["session_id"]
    assert sid1 in SESIONES

    r2 = client.post("/chat", json={"accion": "reiniciar"}).json()
    sid2 = r2["session_id"]

    assert sid2 != sid1
    assert sid1 not in SESIONES
    assert sid2 in SESIONES
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TITULO


def test_coincidencia_expone_score_en_json(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Encontramos un artículo muy similar",
        "link": "https://bc.finneg.com/t/501",
        "coincidencias": [(501, "Configuración de Puntos de Venta", "https://bc.finneg.com/t/501", "norm", "query", 0.825)],
    }
    r = client.post("/chat", json={"mensaje": "Configurar Punto de Venta AFIP"}).json()
    assert r["estado"] == EstadoFlujo.DECISION_TITULO
    assert len(r["coincidencias"]) == 1
    assert r["coincidencias"][0]["id"] == 501
    assert r["coincidencias"][0]["score"] == 0.825


def test_enriquecer_consolida_texto_evitando_rechazo_por_texto_breve(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Ya existe un artículo con exactamente este título",
        "link": "https://bc.finneg.com/t/601",
        "coincidencias": [(601, "Guía de Facturación AFIP", "https://bc.finneg.com/t/601")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 601,
        "titulo": "Guía de Facturación AFIP",
        "url": "https://bc.finneg.com/t/601",
        "texto": TEXTO_VALIDO,
        "categoria_id": 5,
        "tags": ["instructivo", "afip"],
    }
    r1 = client.post("/chat", json={"mensaje": "Guía de Facturación AFIP"}).json()
    sid = r1["session_id"]

    # Elegir enriquecer
    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # Enviar aporte breve (menor a TEXTO_MIN = 20 o 100 caracteres si fuera estricto)
    aporte_breve = "Válido para versión 2026."
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": aporte_breve}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert TEXTO_VALIDO in r3["borrador"]["texto_alineado_discourse"]
    assert aporte_breve in r3["borrador"]["texto_alineado_discourse"]


def test_sanitizacion_aviso_privacidad_un_solo_turno(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Cobranzas Especiales"}).json()
    sid = r1["session_id"]

    texto_con_cuit = TEXTO_VALIDO + " Contacto con CUIT 20-30405060-9."
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_con_cuit}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r2["aviso_privacidad"] is not None
    assert "identificación personal" in r2["aviso_privacidad"].lower() or "privacidad" in r2["aviso_privacidad"].lower()

    # En el siguiente turno, el aviso de privacidad no debe persistir (aviso de un solo turno)
    r3 = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3["aviso_privacidad"] is None


def test_enriquecer_con_cuit_emite_aviso_y_consolida(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Ya existe un artículo con exactamente este título",
        "link": "https://bc.finneg.com/t/701",
        "coincidencias": [(701, "Guía de Ventas AFIP", "https://bc.finneg.com/t/701")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 701,
        "titulo": "Guía de Ventas AFIP",
        "url": "https://bc.finneg.com/t/701",
        "texto": TEXTO_VALIDO,
        "categoria_id": 5,
        "tags": ["instructivo", "ventas"],
    }
    r1 = client.post("/chat", json={"mensaje": "Guía de Ventas AFIP"}).json()
    sid = r1["session_id"]

    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})

    aporte_sensible = "Actualización: soporte para contribuyente CUIT 20-30405060-9."
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": aporte_sensible}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3["aviso_privacidad"] is not None
    assert "[CUIT_OCULTO]" in r3["borrador"]["texto_alineado_discourse"]
    assert "20-30405060-9" not in r3["borrador"]["texto_alineado_discourse"]
    assert TEXTO_VALIDO in r3["borrador"]["texto_alineado_discourse"]


def test_metadatos_tags_en_texto_y_categoria_default(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Flujo de Pruebas de Metadatos y Categorías"}).json()
    sid = r1["session_id"]

    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    # Selecciona plantilla mediante 'texto'
    r_plant = client.post("/chat", json={"session_id": sid, "texto": "instructivo"}).json()
    assert r_plant["estado"] == EstadoFlujo.REVISION_BORRADOR
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_plant = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_plant["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Envía tags mediante 'texto' separados por coma, sin categoría: no debe avanzar silenciosamente a REVISION_BORRADOR
    r_meta = client.post("/chat", json={"session_id": sid, "texto": "contabilidad, balances"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "categoría" in r_meta["mensaje"].lower()
    assert r_meta["borrador"]["categoria_id"] is None
    assert "contabilidad" in r_meta["borrador"]["tags"]
    assert "balances" in r_meta["borrador"]["tags"]
    assert "instructivo" in r_meta["borrador"]["tags"]

    # Al ingresar la categoría requerida, avanza a REVISION_BORRADOR
    r_cat = client.post("/chat", json={"session_id": sid, "categoria_id": 5}).json()
    assert r_cat["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_cat["borrador"]["categoria_id"] == 5
    assert "contabilidad" in r_cat["borrador"]["tags"]
    assert "balances" in r_cat["borrador"]["tags"]
    assert "instructivo" in r_cat["borrador"]["tags"]


def test_ajuste_editorial_confirmar_aprueba(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    # Título con fórmula redundante ('Cómo...') que genera 'Requiere ajuste'
    r1 = client.post("/chat", json={"mensaje": "Cómo configurar el punto de venta AFIP"}).json()
    sid = r1["session_id"]

    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"})
    r_val = client.post("/chat", json={"session_id": sid, "tags": ["instructivo", "afip"], "categoria_id": 5}).json()

    assert r_val["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_val["validacion"]["status"] == "Listo con ajustes sugeridos"
    assert "observación(es) editoriales" in r_val["mensaje"]

    # Redactor confirma explícitamente mantener la observación editorial
    r_conf = client.post("/chat", json={"session_id": sid, "accion": "confirmar"}).json()
    assert r_conf["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO
    assert "observaciones de estilo confirmadas" in r_conf["mensaje"]


def test_ajuste_editorial_corregir_limpia_y_aprueba(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    # Título redundante
    r1 = client.post("/chat", json={"mensaje": "Cómo configurar el punto de venta AFIP"}).json()
    sid = r1["session_id"]

    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"})
    r_val = client.post("/chat", json={"session_id": sid, "tags": ["instructivo", "afip"], "categoria_id": 5}).json()
    assert r_val["validacion"]["status"] == "Listo con ajustes sugeridos"

    # Corrige el título redundante
    r_edit = client.post("/chat", json={"session_id": sid, "accion": "corregir", "titulo": "Configurar Punto de Venta AFIP"}).json()
    assert r_edit["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_edit["validacion"]["status"] == "Listo"

    r_apr = client.post("/chat", json={"session_id": sid, "accion": "conforme"}).json()
    assert r_apr["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO


def test_contrato_ampliado_etapa_tags_acumulados_y_categorias_desde_db(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None
    mock_buscador.cur.fetchall.side_effect = [
        [
            {"id": 1, "nombre": "General"},
            {"id": 5, "nombre": "Ventas"},
            {"id": 23, "nombre": "Impuestos"},
        ],
        [
            {"id": 10, "name": "afip", "slug": "afip"},
            {"id": 11, "name": "instructivo", "slug": "instructivo"},
            {"id": 12, "name": "ventas", "slug": "ventas"},
        ],
    ]

    # Etapa 1 de 5: Bienvenida (ESPERANDO_TITULO)
    r0 = client.post("/chat", json={}).json()
    assert r0["estado"] == EstadoFlujo.ESPERANDO_TITULO
    assert r0["etapa"]["actual"] == 1
    assert r0["etapa"]["total"] == 5
    assert r0["etapa"]["nombre"] == "Título y duplicados"
    assert len(r0["etapa"]["etapas"]) == 5
    assert r0["tags_acumulados"] == []
    assert r0["borrador"] is None
    assert r0["categorias_disponibles"] == [
        {"id": 1, "nombre": "General"},
        {"id": 5, "nombre": "Ventas"},
        {"id": 23, "nombre": "Impuestos"},
    ]
    assert r0["tags_disponibles"] == ["afip", "instructivo", "ventas"]

    # Etapa 2 de 5: Envía título -> ESPERANDO_TEXTO
    r1 = client.post("/chat", json={"titulo": "Configurar Punto de Venta AFIP en Ventas"}).json()
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r1["etapa"]["actual"] == 2
    assert r1["etapa"]["nombre"] == "Contenido"
    assert "volver" in r1["opciones"]

    # Etapa 3 de 5: Envía texto -> ESPERANDO_PLANTILLA
    r2 = client.post("/chat", json={"accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r2["etapa"]["actual"] == 3
    assert r2["etapa"]["nombre"] == "Plantilla y etiquetas"
    assert "instructivo" in r2["opciones"]
    assert "soluciones" in r2["opciones"]
    assert r2["borrador"] is not None

    # Elige plantilla -> REVISION_BORRADOR (Etapa 4); 'continuar_revision' sin metadatos -> ESPERANDO_METADATOS (Etapa 3)
    r3 = client.post("/chat", json={"accion": "instructivo"}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3["etapa"]["actual"] == 4
    r3 = client.post("/chat", json={"accion": "continuar_revision"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r3["etapa"]["actual"] == 3
    assert r3["tags_acumulados"] == ["instructivo"]

    # Etapa 4 de 5: Envía tags y categoría elegida (id=23) -> REVISION_BORRADOR
    r4 = client.post("/chat", json={"tags": ["ventas", "afip"], "categoria_id": 23}).json()
    assert r4["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r4["etapa"]["actual"] == 4
    assert r4["etapa"]["nombre"] == "Revisión"
    assert r4["tags_acumulados"] == ["instructivo", "ventas", "afip"]
    assert r4["borrador"]["categoria_id"] == 23
    assert r4["borrador"]["tags"] == ["instructivo", "ventas", "afip"]
    assert "conforme" in r4["opciones"]

    # Etapa 5 de 5: Da conformidad -> CONFORMIDAD_USUARIO con resumen final
    r5 = client.post("/chat", json={"accion": "conforme"}).json()
    assert r5["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO
    assert r5["etapa"]["actual"] == 5
    assert r5["etapa"]["total"] == 5
    assert r5["etapa"]["nombre"] == "Conformidad"
    assert r5["tags_acumulados"] == ["instructivo", "ventas", "afip"]
    assert r5["borrador"]["categoria_id"] == 23


def test_seleccion_categoria_por_nombre_en_metadatos(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None
    mock_buscador.cur.fetchall.side_effect = [
        [(1, "General"), (39, "Liquidación de Haberes")],
        [(1, "instructivo", "instructivo"), (2, "sueldos", "sueldos")],
    ]

    client.post("/chat", json={"titulo": "Configurar antigüedad acumulada en legajos"})
    client.post("/chat", json={"accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"accion": "instructivo"})
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    client.post("/chat", json={"accion": "continuar_revision"})

    # Usuario envía tag temático y el nombre de la categoría disponible
    r_val = client.post("/chat", json={"mensaje": "sueldos, Liquidación de Haberes"}).json()
    assert r_val["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_val["borrador"]["categoria_id"] == 39
    assert r_val["tags_acumulados"] == ["instructivo", "sueldos"]


def test_cache_en_memoria_reutiliza_catalogos_sin_consultar_db(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    # Primer turno: poblar el cache desde el cursor
    mock_buscador.cur.fetchall.side_effect = [
        [{"id": 1, "nombre": "General"}, {"id": 2, "nombre": "Ventas"}],
        [{"name": "instructivo"}, {"name": "ventas"}],
    ]
    r1 = client.post("/chat", json={}).json()
    assert len(r1["categorias_disponibles"]) == 2
    assert len(r1["tags_disponibles"]) == 2

    # Desactivamos el cursor para que si consulta de nuevo devuelva vacío
    mock_buscador.cur.fetchall.side_effect = None
    mock_buscador.cur.fetchall.return_value = []

    # Nueva sesión (simulando otro usuario / otra sesión de chat)
    c2 = client.post("/chat", json={"session_id": "sesion-distinta-123", "mensaje": "Nuevo título de prueba"}).json()
    assert len(c2["categorias_disponibles"]) == 2
    assert c2["categorias_disponibles"][0]["nombre"] == "General"
    assert len(c2["tags_disponibles"]) == 2
    assert "instructivo" in c2["tags_disponibles"]


def test_catalogo_curado_opcion_a_y_resolucion_nombres(client, mock_buscador):
    from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos, DICCIONARIO_OFICIAL_CATEGORIAS
    limpiar_cache_catalogos()

    # Simular lectura de BD completa con 15 registros de 'Categoría {id}'
    filas_bd = [(cid, f"Categoría {cid}") for cid in [1, 2, 4, 19, 20, 21, 22, 23, 24, 25, 37, 39, 48, 62, 115, 128]]
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None
    mock_buscador.cur.fetchall.side_effect = [
        filas_bd,
        [{"name": "instructivo"}, {"name": "ventas"}],
    ]

    r = client.post("/chat", json={}).json()
    cats = r["categorias_disponibles"]
    # Debe entregar las 165 categorías oficiales completas
    assert len(cats) == 165
    nombres = [c["nombre"] for c in cats]
    assert "Contabilidad" in nombres
    assert "Ventas" in nombres
    assert "Agro" in nombres
    assert "Compras" in nombres
    assert "Tesorería" in nombres

    # Verificar mapeo de IDs y resolución con el diccionario oficial
    mapa = {c["id"]: c["nombre"] for c in cats}
    assert mapa[20] == "Ventas"
    assert mapa[21] == "Contabilidad"
    assert mapa[37] == "Agro"
    assert mapa[165] == "Novedades de Tecnología"


def test_actualizar_serie_toma_nuevo_titulo_de_entrada(client, mock_buscador):
    # Simular coincidencia de tipo serie
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de serie encontrada",
        "link": "https://bc.finneg.com/t/501",
        "coincidencias": [(501, "Novedades Impositivas Mayo 2026", "https://bc.finneg.com/t/501")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 501,
        "titulo": "Novedades Impositivas Mayo 2026",
        "url": "https://bc.finneg.com/t/501",
        "texto": TEXTO_VALIDO,
        "categoria_id": 23,
        "tags": ["instructivo", "afip"],
    }

    # Usuario ingresa el nuevo título de la serie
    r1 = client.post("/chat", json={"mensaje": "Novedades Impositivas Junio 2026"}).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO
    assert "actualizar" in r1["opciones"]
    assert "descartar" in r1["opciones"]

    # Usuario clickea en 'Actualizar el existente' (serie)
    r2 = client.post("/chat", json={"session_id": r1["session_id"], "accion": "actualizar"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r2["borrador"]["modo"] == "enriquecimiento"
    assert r2["borrador"]["articulo_original_id"] == 501
    # CONDICION CLAVE: Debe tomar el NUEVO título, no el histórico
    assert r2["borrador"]["titulo"] == "Novedades Impositivas Junio 2026"


def test_actualizar_o_enriquecer_termina_busqueda_duplicados_sin_evaluar_texto(client, mock_buscador):
    # Simular coincidencia de serie por título
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de serie encontrada",
        "link": "https://bc.finneg.com/t/501",
        "coincidencias": [(501, "Novedades Impositivas Mayo 2026", "https://bc.finneg.com/t/501")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 501,
        "titulo": "Novedades Impositivas Mayo 2026",
        "url": "https://bc.finneg.com/t/501",
        "texto": TEXTO_VALIDO,
        "categoria_id": 23,
        "tags": ["instructivo", "afip"],
    }

    # 1. Envía nuevo título de serie
    r1 = client.post("/chat", json={"mensaje": "Novedades Impositivas Junio 2026"}).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # 2. Clickea 'actualizar'
    r2 = client.post("/chat", json={"session_id": r1["session_id"], "accion": "actualizar"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r2["borrador"]["modo"] == "enriquecimiento"

    # 3. Envía texto con cambios
    r3 = client.post("/chat", json={"session_id": r1["session_id"], "accion": "confirmar_texto", "texto": TEXTO_VALIDO + " Novedades del mes."}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r3["borrador"]["titulo"] == "Novedades Impositivas Junio 2026"

    # CONDICION CLAVE FASE 2: evaluar_texto NUNCA debe haber sido llamado
    mock_buscador.evaluar_texto.assert_not_called()


def test_actualizar_luego_descartar_con_texto_explicito_evalua_duplicados_y_no_modifica_existente(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de serie encontrada",
        "link": "https://bc.finneg.com/t/501",
        "coincidencias": [(501, "Novedades Impositivas Mayo 2026", "https://bc.finneg.com/t/501")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 501,
        "titulo": "Novedades Impositivas Mayo 2026",
        "url": "https://bc.finneg.com/t/501",
        "texto": TEXTO_VALIDO,
        "categoria_id": 23,
        "tags": ["instructivo", "afip"],
    }
    mock_buscador.evaluar_texto.return_value = None

    # 1. Ingresa un título
    r1 = client.post("/chat", json={"mensaje": "Novedades Impositivas Junio 2026"}).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # 2. Elige "Actualizar el existente"
    r2 = client.post("/chat", json={"session_id": r1["session_id"], "accion": "actualizar"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r2["borrador"]["articulo_original_id"] == 501

    # 3. Al enviar texto explícitamente tras descartar, se evalúa texto y se crea borrador nuevo:
    texto_nuevo = "Este es un texto totalmente distinto para un articulo nuevo con mas de veinte caracteres."
    r3 = client.post("/chat", json={"session_id": r1["session_id"], "accion": "descartar", "texto": texto_nuevo}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r3["borrador"]["modo"] == "nuevo"
    assert r3["borrador"]["articulo_original_id"] is None
    assert r3["borrador"]["titulo"] == "Novedades Impositivas Junio 2026"
    mock_buscador.evaluar_texto.assert_called_once()


def test_descartar_titulo_con_titulo_y_texto_ejecuta_evaluar_texto_inmediatamente(client, mock_buscador):
    # Simular coincidencia de título
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título encontrada",
        "link": "https://bc.finneg.com/t/601",
        "coincidencias": [(601, "Configuración de Ventas Mayo", "https://bc.finneg.com/t/601")],
    }
    # Y coincidencia de texto que se disparará al descartar
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia de texto encontrada",
        "link": "https://bc.finneg.com/t/602",
        "coincidencias": [(602, "Configuración de Ventas General", "https://bc.finneg.com/t/602")],
    }

    # 1. Envía TÍTULO Y TEXTO juntos
    r1 = client.post(
        "/chat",
        json={"titulo": "Configuración de Ventas Junio", "texto": TEXTO_VALIDO},
    ).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO
    # Solo se evaluó título hasta acá
    mock_buscador.evaluar_texto.assert_not_called()

    # 2. Clickea 'descartar'
    # CONDICION SINE QUA NON FASE 3: Como ya se recibieron título y texto,
    # al descartar se ejecuta evaluar_texto inmediatamente.
    r2 = client.post("/chat", json={"session_id": r1["session_id"], "accion": "descartar"}).json()
    assert r2["estado"] == EstadoFlujo.DECISION_TEXTO
    assert r2["coincidencias"][0]["id"] == 602
    mock_buscador.evaluar_texto.assert_called_once()

    # Caso B: Si evaluar_texto no arroja coincidencias al descartar
    client.cookies.clear()
    mock_buscador.evaluar_texto.reset_mock()
    mock_buscador.evaluar_texto.return_value = None
    r_b1 = client.post(
        "/chat",
        json={"titulo": "Configuración de Ventas Julio", "texto": TEXTO_VALIDO},
    ).json()
    assert r_b1["estado"] == EstadoFlujo.DECISION_TITULO

    r_b2 = client.post("/chat", json={"session_id": r_b1["session_id"], "accion": "descartar"}).json()
    assert r_b2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r_b2["borrador"]["modo"] == "nuevo"
    assert r_b2["borrador"]["titulo"] == "Configuración de Ventas Julio"
    mock_buscador.evaluar_texto.assert_called_once()


def test_evaluar_texto_excluye_articulo_previamente_descartado(client, mock_buscador):
    client.cookies.clear()
    # Simular coincidencia de título con el artículo #701
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título encontrada",
        "link": "https://bc.finneg.com/t/701",
        "coincidencias": [(701, "Configuración AFIP Facturación", "https://bc.finneg.com/t/701")],
    }
    # La búsqueda de texto devuelve también el artículo #701 (el mismo)
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia de texto encontrada",
        "link": "https://bc.finneg.com/t/701",
        "coincidencias": [(701, "Configuración AFIP Facturación", "https://bc.finneg.com/t/701")],
    }

    # 1. Envía título y texto
    r1 = client.post(
        "/chat",
        json={"titulo": "Facturación Electrónica AFIP", "texto": TEXTO_VALIDO},
    ).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO
    assert r1["coincidencias"][0]["id"] == 701

    # 2. Descarta el artículo #701
    # CONDICION DE EXCLUSION: evaluar_texto busca y devuelve #701, pero el orquestador
    # lo excluye porque ya fue rechazado por el usuario. No debe volver a mostrar #701.
    r2 = client.post("/chat", json={"session_id": r1["session_id"], "accion": "descartar"}).json()
    # Al ser #701 la única coincidencia y estar excluida, avanza directo a ESPERANDO_PLANTILLA
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r2["borrador"]["modo"] == "nuevo"
    assert r2["borrador"]["titulo"] == "Facturación Electrónica AFIP"
# =========================================================================
# Tests PASO 2: Registro e invalidación de conformidad
# =========================================================================

def test_registro_conformidad_al_confirmar(client):
    """Verifica que al confirmar se registre conforme=True y conforme_en=ISO timestamp."""
    sid = "sesion-test-reg-conf"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Título de prueba",
        texto=TEXTO_VALIDO,
        categoria_id=1,
        tags=["instructivo", "ventas"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título de prueba",
            texto=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
            categoria_id=1,
            tags=["instructivo", "ventas"],
            conforme=False,
            conforme_en=None,
        ),
    )

    resp = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "conforme"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO

    ses = SESIONES[sid]
    assert ses.borrador.conforme is True
    assert ses.borrador.conforme_en is not None
    # Verificar formato ISO
    assert "T" in ses.borrador.conforme_en
    assert ses.borrador.texto_original_conforme == TEXTO_VALIDO


def test_invalida_conformidad_al_modificar_texto(client):
    """Verifica que si el texto cambia (por edición o skill), la conformidad se invalide y vuelva a REVISION_BORRADOR."""
    sid = "sesion-test-inv-conf"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Título de prueba",
        texto=TEXTO_VALIDO,
        categoria_id=1,
        tags=["instructivo", "ventas"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título de prueba",
            texto=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
            categoria_id=1,
            tags=["instructivo", "ventas"],
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme=TEXTO_VALIDO,
        ),
    )

    nuevo_texto = (
        "Texto modificado con suficiente cantidad de caracteres para superar el límite mínimo "
        "y verificar que al editar se invalida la conformidad previamente registrada por el usuario."
    )

    # 1. Modificación mediante acción de edición en el chat
    resp = client.post(
        "/chat",
        headers={"X-Session-ID": sid},
        json={"accion": "editar", "texto": nuevo_texto},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] == EstadoFlujo.REVISION_BORRADOR

    ses = SESIONES[sid]
    assert ses.borrador.conforme is False
    assert ses.borrador.conforme_en is None
    assert ses.estado == EstadoFlujo.REVISION_BORRADOR

    # 2. Modificación programática / vía skill (actualizar_borrador_texto)
    # Primero volvemos a dar conformidad
    client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "conforme"})
    assert ses.borrador.conforme is True
    assert ses.estado == EstadoFlujo.CONFORMIDAD_USUARIO

    # Ahora una skill actualiza el texto
    actualizar_borrador_texto(sid, nuevo_texto + "\n\nActualizado por skill.")
    assert ses.borrador.conforme is False
    assert ses.borrador.conforme_en is None
    assert ses.estado == EstadoFlujo.REVISION_BORRADOR


def test_no_puede_quedar_en_conformidad_con_texto_distinto_al_confirmado(client):
    """Verifica que no se pueda quedar en CONFORMIDAD_USUARIO con texto distinto al que se confirmó."""
    sid = "sesion-test-mismatch-conf"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Título de prueba",
        texto=TEXTO_VALIDO,
        categoria_id=1,
        tags=["instructivo"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título de prueba",
            texto="Texto alterado fuera de los flujos normales que no coincide con el original",
            tipo_plantilla="instructivo",
            categoria_id=1,
            tags=["instructivo"],
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme=TEXTO_VALIDO,
        ),
    )

    # Al intentar resolver o consultar el borrador, se detecta la discrepancia e invalida la conformidad
    resp = client.get("/chat/borrador", headers={"X-Session-ID": sid})
    assert resp.status_code == 409
    assert "no está en estado CONFORMIDAD_USUARIO" in resp.json()["detail"]

    ses = SESIONES[sid]
    assert ses.borrador.conforme is False
    assert ses.borrador.conforme_en is None
    assert ses.estado == EstadoFlujo.REVISION_BORRADOR


# =========================================================================
# Tests PASO 3: Mensajes del flujo de conformidad
# =========================================================================

def test_mensajes_flujo_conformidad(client):
    """Verifica los 3 mensajes requeridos: antes del botón, al confirmar y al invalidar por un cambio."""
    sid = "sesion-test-mensajes-conf"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.ESPERANDO_METADATOS,
        titulo="Configuración de prueba",
        texto=TEXTO_VALIDO,
        categoria_id=1,
        tags=["instructivo"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configuración de prueba",
            texto=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
            categoria_id=1,
            tags=["instructivo"],
        ),
    )

    # 1. Antes del botón (al pasar a REVISION_BORRADOR con metadatos válidos)
    r_meta = client.post(
        "/chat",
        headers={"X-Session-ID": sid},
        json={"tags": ["instructivo", "ventas"]},
    ).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert (
        "Revisá el borrador. Si estás conforme con el contenido, tocá **Estoy conforme**."
    ) in r_meta["mensaje"]

    # 2. Al confirmar (tocá Estoy conforme / accion: conforme)
    r_conf = client.post(
        "/chat",
        headers={"X-Session-ID": sid},
        json={"accion": "conforme"},
    ).json()
    assert r_conf["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO
    assert (
        "✅ Registramos tu conformidad. Tu borrador pasó las validaciones mínimas y quedó listo. "
        "Todavía no está publicado: la aprobación y publicación final las hace un administrador. "
        "Podés copiar el borrador y cargarlo en la Base de Conocimiento."
    ) in r_conf["mensaje"]
    assert r_conf["opciones"] == ["copiar_borrador", "reiniciar"]

    # Atajo de acción copiar_borrador
    r_copiar = client.post(
        "/chat",
        headers={"X-Session-ID": sid},
        json={"accion": "copiar_borrador"},
    ).json()
    assert r_copiar["estado"] == EstadoFlujo.CONFORMIDAD_USUARIO
    assert r_copiar["opciones"] == ["copiar_borrador", "reiniciar"]

    # 3. Si se invalida la conformidad por un cambio
    texto_editado = TEXTO_VALIDO + "\n\nSe agrega una aclaración adicional que modifica el texto confirmado."
    r_edit = client.post(
        "/chat",
        headers={"X-Session-ID": sid},
        json={"accion": "editar", "texto": texto_editado},
    ).json()
    assert r_edit["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "Modificaste el borrador, así que necesito que vuelvas a confirmar tu conformidad." in r_edit["mensaje"]
    # Y vuelve a incluir el mensaje antes del botón para invitar a confirmar de nuevo
    assert (
        "Revisá el borrador. Si estás conforme con el contenido, tocá **Estoy conforme**."
    ) in r_edit["mensaje"]


# =========================================================================
# Tests PASO NUEVO: Evento confirmar_texto en ESPERANDO_TEXTO
# =========================================================================

def test_esperando_texto_acumula_sin_confirmar_y_solo_busca_al_confirmar_texto(client, mock_buscador):
    """Mientras no se envía accion='confirmar_texto', el texto vive en texto_en_edicion sin disparar búsqueda."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Configurar percepción de IIBB en Compras"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # Envío parcial 1 sin confirmar_texto -> no llama a evaluar_texto ni avanza de estado
    r_parcial1 = client.post("/chat", json={"mensaje": "Paso 1: Ingresar al maestro de impuestos."}).json()
    assert r_parcial1["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert "confirmar_texto" in r_parcial1["opciones"]
    mock_buscador.evaluar_texto.assert_not_called()
    assert "Paso 1" in SESIONES[sid].texto_en_edicion

    # Envío parcial 2 sin confirmar_texto -> acumula en texto_en_edicion sin llamar a evaluar_texto
    r_parcial2 = client.post(
        "/chat",
        json={"mensaje": "Paso 2: Configurar la alícuota correspondiente a la jurisdicción provincial."},
    ).json()
    assert r_parcial2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert "confirmar_texto" in r_parcial2["opciones"]
    mock_buscador.evaluar_texto.assert_not_called()
    assert "Paso 1" in SESIONES[sid].texto_en_edicion
    assert "Paso 2" in SESIONES[sid].texto_en_edicion

    # Recién al hacer clic en Confirmar (accion='confirmar_texto') se dispara evaluar_texto y avanza
    r_confirm = client.post("/chat", json={"accion": "confirmar_texto"}).json()
    mock_buscador.evaluar_texto.assert_called_once()
    assert r_confirm["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert SESIONES[sid].texto_en_edicion == ""


def test_confirmar_texto_vacio_devuelve_mensaje_amable_y_no_avanza(client, mock_buscador):
    """Confirmar con texto vacío devuelve un mensaje amable y mantiene el estado ESPERANDO_TEXTO."""
    mock_buscador.evaluar_titulo.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Configurar retenciones de Ganancias en Pagos"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    r_vacio = client.post("/chat", json={"accion": "confirmar_texto", "texto": "   "}).json()
    assert r_vacio["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert len(r_vacio["mensaje"]) > 15
    mock_buscador.evaluar_texto.assert_not_called()


def test_metadatos_heredados_aviso_y_aceptar(client, mock_buscador):
    """Al enriquecer un artículo, se avisa de los metadatos heredados y se permite Aceptar."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/501",
        "coincidencias": [(501, "Guía de Liquidación de Sueldos", "https://bc.finneg.com/t/501")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 501,
        "titulo": "Guía de Liquidación de Sueldos",
        "url": "https://bc.finneg.com/t/501",
        "texto": TEXTO_VALIDO,
        "categoria_id": 39,
        "tags": ["instructivo", "hcm"],
    }
    r1 = client.post("/chat", json={"mensaje": "Liquidación de Sueldos y Jornales"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO

    # Acepta enriquecer -> pasa a ESPERANDO_TEXTO
    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})

    # Confirma texto -> REVISION_BORRADOR con aviso de metadatos heredados
    r_rev = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r_rev["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_rev["aviso_metadatos_heredados"] is not None
    assert "HCM" in r_rev["aviso_metadatos_heredados"] or "39" in r_rev["aviso_metadatos_heredados"]
    assert "instructivo" in r_rev["aviso_metadatos_heredados"]
    assert "aceptar" in r_rev["opciones"]
    assert "rechazar" in r_rev["opciones"]

    # Usuario pulsa 'aceptar' -> confirma metadatos heredados
    r_acepta = client.post("/chat", json={"session_id": sid, "accion": "aceptar"}).json()
    assert r_acepta["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_acepta["borrador"]["categoria_id"] == 39
    assert r_acepta["borrador"]["tags"] == ["instructivo", "hcm"]
    assert r_acepta["borrador"]["metadatos_heredados_revisados"] is True
    assert r_acepta["validacion"]["valido"] is True


def test_metadatos_heredados_rechazar_activa_proceso_validacion_asistido(client, mock_buscador):
    """Al rechazar los metadatos heredados, no se bloquea para carga manual sino que se activa el flujo guiado (plantilla y metadatos)."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/601",
        "coincidencias": [(601, "Módulo de Gestión de Inventarios", "https://bc.finneg.com/t/601")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 601,
        "titulo": "Módulo de Gestión de Inventarios",
        "url": "https://bc.finneg.com/t/601",
        "texto": TEXTO_VALIDO,
        "categoria_id": 19,
        "tags": ["instructivo", "inventarios"],
    }
    r1 = client.post("/chat", json={"mensaje": "Gestión de Inventarios y Depósitos"}).json()
    sid = r1["session_id"]

    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})

    # Rechaza metadatos heredados -> activa el proceso de validación guiado ofreciendo plantillas
    r_rech = client.post("/chat", json={"session_id": sid, "accion": "rechazar"}).json()
    assert r_rech["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert "instructivo" in r_rech["opciones"]
    assert "soluciones" in r_rech["opciones"]

    # Selecciona la plantilla instructivo -> pasa a pedir metadatos temáticos
    r_plantilla = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r_plantilla["estado"] == EstadoFlujo.REVISION_BORRADOR
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_plantilla = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_plantilla["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r_plantilla["borrador"]["tipo_plantilla"] == "instructivo"

    # Ingresa la etiqueta temática y categoría -> avanza a revisión con el borrador validado
    r_meta = client.post("/chat", json={"session_id": sid, "categoria_id": 24, "tags": ["compras"]}).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_meta["borrador"]["categoria_id"] == 24
    assert "instructivo" in r_meta["borrador"]["tags"]
    assert "compras" in r_meta["borrador"]["tags"]
    assert r_meta["validacion"]["valido"] is True

def test_metadatos_heredados_rechazar_y_volver_permite_reconsiderar(client, mock_buscador):
    """Si tras rechazar los metadatos heredados la persona toca 'volver', se le vuelve a ofrecer aceptarlos o rechazarlos."""
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia",
        "link": "https://bc.finneg.com/t/602",
        "coincidencias": [(602, "Módulo de Ventas", "https://bc.finneg.com/t/602")],
    }
    mock_buscador.obtener_articulo.return_value = {
        "id": 602,
        "titulo": "Módulo de Ventas",
        "url": "https://bc.finneg.com/t/602",
        "texto": TEXTO_VALIDO,
        "categoria_id": 15,
        "tags": ["instructivo", "ventas"],
    }
    r1 = client.post("/chat", json={"mensaje": "Ventas y Facturación"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})

    # Rechaza metadatos -> pasa a ESPERANDO_PLANTILLA
    r_rech = client.post("/chat", json={"session_id": sid, "accion": "rechazar"}).json()
    assert r_rech["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

    # Toca volver -> vuelve a REVISION_BORRADOR con el aviso de metadatos heredados
    r_volver = client.post("/chat", json={"session_id": sid, "accion": "volver"}).json()
    assert r_volver["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_volver["aviso_metadatos_heredados"] is not None
    assert "aceptar" in r_volver["opciones"]
    assert "rechazar" in r_volver["opciones"]


def test_solicitar_categoria_en_formulario_desde_chat(client, mock_buscador):
    """Verifica que en ESPERANDO_METADATOS el chat indique etiquetas en turno 1 y categoría en turno 2 con menú desplegable."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Nueva Guía de Facturación Electrónica"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_BORRADOR
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Turno 1: solicita etiquetas temáticas
    assert "etiquetas temáticas" in r_meta["mensaje"]

    # Turno 2: usuario envía etiquetas temáticas; el bot solicita la categoría con opción de chat o menú desplegable
    r_cat = client.post("/chat", json={"session_id": sid, "mensaje": "facturacion, afip"}).json()
    assert r_cat["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "menú desplegable en la sección inferior del panel izquierdo" in r_cat["mensaje"]
    assert "decime la categoría por acá" in r_cat["mensaje"]

    # Turno 3: define categoría y avanza a revisión
    r_rev = client.post("/chat", json={"session_id": sid, "categoria_id": 4}).json()
    assert r_rev["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_rev["borrador"]["categoria_id"] == 4
    assert "facturacion" in r_rev["borrador"]["tags"]


def test_mapear_categoria_directamente_desde_chat_en_turno_2(client, mock_buscador):
    """Verifica que en el Turno 2 el usuario pueda escribir la categoría en el chat y se mapee directamente."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Nueva Guía de Facturación Electrónica"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_BORRADOR
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Turno 1: ingresa etiquetas por chat
    r_cat = client.post("/chat", json={"session_id": sid, "mensaje": "facturacion, afip"}).json()
    assert r_cat["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Turno 2: usuario ingresa la categoría escribiendo 'Ventas' en el chat
    r_rev = client.post("/chat", json={"session_id": sid, "mensaje": "Ventas"}).json()
    assert r_rev["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r_rev["borrador"]["categoria_id"] is not None
    assert "facturacion" in r_rev["borrador"]["tags"]


def test_nueva_entrada_sin_duplicados_sin_categoria_es_bloqueante(client, mock_buscador):
    """Verifica que para una entrada nueva sin duplicados la categoría ausente no se asigne a 1 por omisión y sea bloqueante."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    # 1. Iniciar conversación con título sin duplicados
    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Alta y Configuración Inicial"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r1["borrador"] is None

    # 2. Enviar texto válido
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    assert r2["borrador"] is not None
    assert r2["borrador"]["categoria_id"] is None

    # 3. Elegir plantilla
    r3 = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    # Nuevo flujo: plantilla -> revisión intermedia (REVISION_BORRADOR); 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r3 = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r3["borrador"]["categoria_id"] is None
    assert "instructivo" in r3["borrador"]["tags"]

    # 4. Enviar sólo tags temáticos sin categoría: la categoría no debe auto-asignarse a 1 y debe exigir la categoría
    r4 = client.post("/chat", json={"session_id": sid, "tags": ["configuracion", "alta"]}).json()
    assert r4["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r4["borrador"]["categoria_id"] is None
    assert "categoría" in r4["mensaje"].lower()
    assert "configuracion" in r4["borrador"]["tags"]
    assert "alta" in r4["borrador"]["tags"]

    # 5. Proveer la categoría desbloquea el flujo hacia revisión
    r5 = client.post("/chat", json={"session_id": sid, "categoria_id": 2}).json()
    assert r5["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert r5["borrador"]["categoria_id"] == 2
    assert r5["validacion"]["valido"] is True


def test_revision_borrador_live_edit_autosanitiza_pii_inmediatamente(client, mock_buscador):
    """Verifica la convergencia absoluta en edición viva durante REVISION_BORRADOR:

    Cualquier texto editado reemplaza inmediatamente el PII por marcadores sanitizados,
    sin requerir tocar 'sanitizar', y emite aviso_privacidad al usuario.
    """
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    # 1. Iniciar artículo
    r1 = client.post("/chat", json={"mensaje": "Manual de Alta de Clientes en el Sistema"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    client.post("/chat", json={"session_id": sid, "accion": "instructivo"})
    r_rev = client.post("/chat", json={"session_id": sid, "tags": ["ventas", "alta"], "categoria_id": 2}).json()
    assert r_rev["estado"] == EstadoFlujo.REVISION_BORRADOR

    # 2. El usuario edita directamente el texto enviando PII (CUIL y correo personal)
    texto_con_pii = (
        "Pasos para dar de alta al cliente en la base corporativa:\n"
        "1. Solicitar la documentación fiscal.\n"
        "2. Verificar el CUIL: 20-30405060-9 del representante legal.\n"
        "3. Remitir la constancia al mail juan.perez@empresa.com para su validación final."
    )
    r_edit = client.post(
        "/chat",
        json={"session_id": sid, "accion": "editar", "texto": texto_con_pii},
    ).json()

    assert r_edit["estado"] == EstadoFlujo.REVISION_BORRADOR
    assert "20-30405060-9" not in r_edit["borrador"]["texto_limpio"]
    assert "juan.perez@empresa.com" not in r_edit["borrador"]["texto_limpio"]
    assert "[CUIT_OCULTO]" in r_edit["borrador"]["texto_limpio"]
    assert "usuario@ejemplo.com" in r_edit["borrador"]["texto_limpio"]

    # Aviso de privacidad presente en la respuesta
    assert r_edit.get("aviso_privacidad") is not None
    assert "preservarte" in r_edit["aviso_privacidad"]

    # Sesión activa con texto sanitizado
    sesion = SESIONES[sid]
    assert "[CUIT_OCULTO]" in sesion.texto_limpio
    assert "[CUIT_OCULTO]" in sesion.borrador.texto_limpio
    assert "20-30405060-9" not in sesion.texto_limpio


def test_evaluar_texto_recibe_texto_sin_marcadores_recursos(client, mock_buscador):
    """Ítem 4: Verifica que handlers.py invoque buscador.evaluar_texto con el texto
    efectivo sin marcadores [[recurso:...]] ni tags multimedia."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Título para prueba de búsqueda limpia"}).json()
    sid = r1["session_id"]

    texto_con_imagen = (
        "Texto de procedimiento técnico con caracteres suficientes para superar el mínimo requerido.\n\n"
        "![Captura del paso](https://bc.finneg.com/uploads/paso1.png)\n\n"
        "Continuación de la explicación detallada del sistema."
    )

    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_con_imagen})

    assert mock_buscador.evaluar_texto.called
    texto_busqueda_usado = mock_buscador.evaluar_texto.call_args[0][0]
    assert "[[recurso:" not in texto_busqueda_usado
    assert "https://bc.finneg.com" not in texto_busqueda_usado
    assert "paso1.png" not in texto_busqueda_usado
    assert "Texto de procedimiento técnico" in texto_busqueda_usado




