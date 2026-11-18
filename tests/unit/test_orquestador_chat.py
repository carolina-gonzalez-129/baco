from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from flujo_helpers import avanzar_hasta
from pydantic import ValidationError

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.config_limites import (
    TEXTO_MAX,
    TEXTO_MAX_PERCENTIL_99,
    TITULO_MAX,
)
from baco.server.schemas.articulo import ArticuloSchema
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador import (
    actualizar_borrador_texto,
    manejar_turno,
    obtener_borrador_conforme,
)
from baco.server.services.orquestador.mensajes import (
    MENSAJE_BIENVENIDA,
    MSG_BORRADOR_FINALIZADO,
    MSG_EDICION_FINAL,
    msg_articulo_muy_largo,
)
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import (
    validar_borrador as _validar_borrador,
)

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
    assert "Cargué el artículo **Cómo Configurar Punto de Venta AFIP** en la **Vista previa**" in r3["mensaje"]

    # 4. Envía el texto con aportes/modificaciones -> paso de plantilla y, con los heredados, a REVISION_METADATOS
    r3b = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r3b["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    r3b = avanzar_hasta(client, sid, r3b, EstadoFlujo.REVISION_METADATOS)
    assert r3b["borrador"]["modo"] == "enriquecimiento"
    assert r3b["borrador"]["articulo_original_id"] == 101
    assert r3b["borrador"]["texto_alineado_discourse"] == TEXTO_VALIDO
    assert r3b["borrador"]["tipo_plantilla"] == "instructivo"
    assert r3b["borrador"]["tags"] == ["instructivo", "ventas"]
    assert r3b["validacion"]["valido"] is True

    # Mientras no esté FINALIZADO, no se expone el borrador externo (409 Conflict si existe pero no está en finalizado)
    assert obtener_borrador_conforme(sid) is None
    assert client.get("/chat/borrador").status_code == 409
    with TestClient(app, headers={"X-API-Key": API_KEY}) as c_inexistente:
        assert c_inexistente.get("/chat/borrador", headers={"X-Session-ID": "inexistente-123"}).status_code == 404

    # 4. Revisión humana final -> finaliza y garantiza sanitización determinista
    r4 = avanzar_hasta(client, sid, r3b, EstadoFlujo.FINALIZADO)
    assert r4["estado"] == EstadoFlujo.FINALIZADO

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

    # Confirma texto -> paso de plantilla; con los heredados precargados llega a REVISION_METADATOS
    r5 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": r4["borrador"]["texto_alineado_discourse"]}).json()
    assert r5["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
    r5 = avanzar_hasta(client, sid, r5, EstadoFlujo.REVISION_METADATOS, plantilla="soluciones")
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
    assert r_plant["opciones"] == ["instructivo", "soluciones"]
    assert r_plant["navegacion"] == ["volver"]

    # Elige plantilla 'instructivo' -> pasa a REVISION_BORRADOR y luego 'continuar_revision' pide metadatos
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_TIPO
    # Nuevo flujo: plantilla -> REVISION_TIPO; 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r_meta["borrador"]["tipo_plantilla"] == "instructivo"

    # Ingresa tags temáticos y categoría -> corre validar_articulo y pasa a REVISION_BORRADOR
    r_val = client.post("/chat", json={"session_id": sid, "mensaje": "ventas, facturacion, 4"}).json()
    # La carga por chat se confirma con Enviar datos (rama arreglar-meta-datos)
    assert r_val["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r_val["accion_panel"]["accion"] == "enviar_datos"
    r_val = client.post("/chat", json={"session_id": sid, "accion": "enviar_datos"}).json()
    assert r_val["estado"] == EstadoFlujo.REVISION_METADATOS
    assert r_val["borrador"]["modo"] == "nuevo"
    assert r_val["borrador"]["tags"] == ["instructivo", "ventas", "facturacion"]
    assert r_val["borrador"]["categoria_id"] == 4
    # Ahora es autosanitizante: ya reemplazó el CUIT automáticamente y es válido con aviso
    assert r_val["validacion"]["valido"] is True
    assert "[CUIT_OCULTO]" in r_val["borrador"]["texto_alineado_discourse"]

    client.post("/chat", json={"session_id": sid, "accion": "continuar"})
    r_ok = client.post("/chat", json={"session_id": sid, "accion": "finalizar"}).json()
    assert r_ok["estado"] == EstadoFlujo.FINALIZADO


def test_camino_sin_coincidencias_plantilla_metadatos_y_rechazo_humano(client, mock_buscador):
    mock_buscador.evaluar_titulo.return_value = None
    r1 = client.post("/chat", json={"mensaje": "Integración de API de Cobranzas Bancarias"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    mock_buscador.evaluar_texto.return_value = None
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

    r3 = client.post("/chat", json={"session_id": sid, "mensaje": "soluciones"}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_TIPO
    # Nuevo flujo: plantilla -> REVISION_TIPO; 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r3 = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    r4 = client.post("/chat", json={"session_id": sid, "tags": ["cobranzas", "bancos"], "categoria_id": 1}).json()
    assert r4["estado"] == EstadoFlujo.REVISION_METADATOS
    assert r4["borrador"]["modo"] == "nuevo"
    assert r4["borrador"]["tipo_plantilla"] == "soluciones"
    assert r4["borrador"]["tags"] == ["soluciones", "cobranzas", "bancos"]
    assert r4["validacion"]["valido"] is True

    # "Descartar borrador" solo se ofrece con bloqueantes de validar_borrador; el flujo
    # normal ya no los produce (las ediciones inválidas se rechazan antes), así que se simula.
    SESIONES[sid].ultimas_opciones = ["editar", "rechazar"]
    r5 = client.post("/chat", json={"session_id": sid, "accion": "rechazar"}).json()
    assert r5["estado"] == EstadoFlujo.REVISION_METADATOS
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
    r = client.post("/chat", json={"session_id": sid, "mensaje": "instructivo"}).json()
    r_val = avanzar_hasta(client, sid, r, EstadoFlujo.REVISION_METADATOS, tags=["ventas"], categoria_id=1)

    # Editar con un título inválido (< 15 caracteres) desde el panel: no rompe, no se guarda y avisa
    r_edit = client.post("/chat", json={"session_id": sid, "titulo": "Corto"}).json()
    assert r_edit["estado"] == EstadoFlujo.REVISION_METADATOS
    assert "más largo" in r_edit["mensaje"]
    assert r_edit["borrador"]["titulo"] == "Título Inicial Válido Para el Borrador"


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
    sesion = SesionChat(session_id=sid, estado=EstadoFlujo.REVISION_METADATOS, borrador=borrador)
    SESIONES[sid] = sesion

    # Guardado desde el panel (sin acción): el contrato ya no ofrece "editar" en REVISION_METADATOS
    req = ChatOrquestadorRequest.model_construct(session_id=sid, texto="A" * (TEXTO_MAX_PERCENTIL_99 + 10))
    resp = await manejar_turno(req, mock_buscador)

    assert resp.estado == EstadoFlujo.REVISION_METADATOS
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
    assert r2["mensaje"] == msg_articulo_muy_largo(TEXTO_MAX_PERCENTIL_99)


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
    r2b = avanzar_hasta(client, sid, r2b, EstadoFlujo.REVISION_METADATOS)
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
    assert "El borrador no está en un estado válido" in resp.json()["detail"]


def test_aplicar_plantilla_conforme_inyecta_prompt_y_sobreescribe_borrador(client):
    sid = "sesion-conforme-test"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.EDICION_FINAL,
        titulo="Configurar Facturación Electrónica",
        texto=TEXTO_VALIDO,
        categoria_id=5,
        tags=["instructivo", "ventas"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Facturación Electrónica",
            texto=TEXTO_VALIDO,
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

    # El resultado de la skill queda en la Vista previa; el estado no cambia
    assert SESIONES[sid].borrador.finalizado is False
    assert SESIONES[sid].estado == EstadoFlujo.EDICION_FINAL
    assert SESIONES[sid].borrador.texto_alineado_discourse == plantilla_markdown

    # Mientras no se finalice, el borrador no es accesible (409)
    resp_get_invalido = client.get("/chat/borrador", headers={"X-Session-ID": sid})
    assert resp_get_invalido.status_code == 409

    # Al finalizar el borrador modificado
    SESIONES[sid].ultimas_opciones = ["finalizar"]
    resp_confirmar = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "finalizar"})
    assert resp_confirmar.status_code == 200
    assert resp_confirmar.json()["estado"] == EstadoFlujo.FINALIZADO
    assert SESIONES[sid].borrador.finalizado is True

    # Ahora sí se puede consultar el borrador vía GET
    resp_get = client.get("/chat/borrador", headers={"X-Session-ID": sid})
    assert resp_get.status_code == 200
    assert resp_get.json()["texto_alineado_discourse"] == plantilla_markdown
    assert resp_get.json()["finalizado"] is True


def test_aplicar_plantilla_salida_insuficiente_retorna_502_y_preserva_borrador(client):
    sid = "sesion-llm-fail-test"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.EDICION_FINAL,
        titulo="Configurar Facturación",
        texto=TEXTO_VALIDO,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Facturación",
            texto=TEXTO_VALIDO,
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
    assert "El borrador no está en un estado válido" in resp.json()["detail"]


def test_auditar_semantica_conforme_inyecta_prompt_y_no_sobreescribe_borrador(client):
    sid = "sesion-validador-test"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.EDICION_FINAL,
        titulo="Configurar Facturación Electrónica",
        texto=TEXTO_VALIDO,
        categoria_id=5,
        tags=["instructivo", "ventas"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Facturación Electrónica",
            texto=TEXTO_VALIDO,
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

    estados_terminales = {EstadoFlujo.FINALIZADO, EstadoFlujo.RECHAZADO}
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

        # 2. Enviar texto sin session_id (TestClient envía la cookie automáticamente)
        r2 = client.post("/chat", json={"accion": "confirmar_texto", "texto": TEXTO_VALIDO})
        assert r2.status_code == 200
        assert r2.json()["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA

        # 3. Hasta la edición final (avanzar_hasta manda el session_id de la cookie)
        r3 = avanzar_hasta(client, cookie_sid, r2.json(), EstadoFlujo.EDICION_FINAL, tags=["ventas"], categoria_id=5)
        assert r3["estado"] == EstadoFlujo.EDICION_FINAL

        # 4. POST /chat/aplicar-plantilla y /chat/auditar-semantica sin session_id en path
        r5 = client.post("/chat/aplicar-plantilla")
        assert r5.status_code == 200
        assert "Instructivo oficial" in r5.json()["response"]
        assert SESIONES[cookie_sid].estado == EstadoFlujo.EDICION_FINAL
        r6 = client.post("/chat/auditar-semantica")
        assert r6.status_code == 200

        # 5. Finalizar sin session_id y leer el borrador por GET
        r_fin = client.post("/chat", json={"accion": "finalizar"})
        assert r_fin.status_code == 200
        assert r_fin.json()["estado"] == EstadoFlujo.FINALIZADO
        assert SESIONES[cookie_sid].borrador.finalizado is True
        r4 = client.get("/chat/borrador")
        assert r4.status_code == 200
        assert r4.json()["titulo"] == "Configurar listas de precios mayoristas"
        assert "Instructivo oficial" in r4.json()["texto_alineado_discourse"]

        # 6. FINALIZADO es terminal: las skills ya no corren
        assert client.post("/chat/aplicar-plantilla").status_code == 409

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
    assert "se cerró por inactividad" in data["mensaje"]
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
    # El front pasa el aporte a la Vista previa (que ya tiene el artículo) y confirma ese texto
    aporte_breve = "Válido para versión 2026."
    vista_previa = TEXTO_VALIDO + "\n\n" + aporte_breve
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": vista_previa}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
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
    assert r3["estado"] == EstadoFlujo.REVISION_TIPO
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
    vista_previa = TEXTO_VALIDO + "\n\n" + aporte_sensible
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": vista_previa}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
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
    r_plant = client.post("/chat", json={"session_id": sid, "mensaje": "instructivo"}).json()
    assert r_plant["estado"] == EstadoFlujo.REVISION_TIPO
    # Nuevo flujo: plantilla -> REVISION_TIPO; 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_plant = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_plant["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Envía tags mediante 'texto' separados por coma, sin categoría: no debe avanzar silenciosamente a REVISION_BORRADOR
    # Por chat (mensaje): el campo "texto" del panel es el cuerpo del artículo en este estado
    r_meta = client.post("/chat", json={"session_id": sid, "mensaje": "contabilidad, balances"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "categoría" in r_meta["mensaje"].lower()
    assert r_meta["borrador"]["categoria_id"] is None
    assert "contabilidad" in r_meta["borrador"]["tags"]
    assert "balances" in r_meta["borrador"]["tags"]
    assert "instructivo" in r_meta["borrador"]["tags"]

    # Al ingresar la categoría requerida y confirmar con Enviar datos, avanza a REVISION_METADATOS
    r_cat = client.post("/chat", json={"session_id": sid, "accion": "enviar_datos", "categoria_id": 5}).json()
    assert r_cat["estado"] == EstadoFlujo.REVISION_METADATOS
    assert r_cat["borrador"]["categoria_id"] == 5
    assert "contabilidad" in r_cat["borrador"]["tags"]
    assert "balances" in r_cat["borrador"]["tags"]
    assert "instructivo" in r_cat["borrador"]["tags"]


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
    assert "volver" in r1["navegacion"]

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
    assert r3["estado"] == EstadoFlujo.REVISION_TIPO
    assert r3["etapa"]["actual"] == 4
    r3 = client.post("/chat", json={"accion": "continuar_revision"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r3["etapa"]["actual"] == 3
    assert r3["tags_acumulados"] == ["instructivo"]

    # Etapa 4 de 5: Envía tags y categoría elegida (id=23) -> REVISION_BORRADOR
    r4 = client.post("/chat", json={"accion": "enviar_datos", "tags": ["ventas", "afip"], "categoria_id": 23}).json()
    assert r4["estado"] == EstadoFlujo.REVISION_METADATOS
    assert r4["etapa"]["actual"] == 4
    assert r4["etapa"]["nombre"] == "Revisión"
    assert r4["tags_acumulados"] == ["instructivo", "ventas", "afip"]
    assert r4["borrador"]["categoria_id"] == 23
    assert r4["borrador"]["tags"] == ["instructivo", "ventas", "afip"]

    # La edición final sigue en la etapa 4; finalizar pasa a la 5
    r4b = client.post("/chat", json={"accion": "continuar"}).json()
    assert r4b["estado"] == EstadoFlujo.EDICION_FINAL
    assert r4b["etapa"]["actual"] == 4
    assert "finalizar" in r4b["opciones"]

    # Etapa 5 de 5: Finaliza -> FINALIZADO con resumen final
    r5 = client.post("/chat", json={"accion": "finalizar"}).json()
    assert r5["estado"] == EstadoFlujo.FINALIZADO
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
    # Nuevo flujo: plantilla -> REVISION_TIPO; 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    client.post("/chat", json={"accion": "continuar_revision"})

    # Usuario envía tag temático y el nombre de la categoría disponible
    r_val = client.post("/chat", json={"mensaje": "sueldos, Liquidación de Haberes"}).json()
    # La carga por chat se confirma con Enviar datos (rama arreglar-meta-datos)
    assert r_val["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r_val["accion_panel"]["accion"] == "enviar_datos"
    r_val = client.post("/chat", json={"accion": "enviar_datos"}).json()
    assert r_val["estado"] == EstadoFlujo.REVISION_METADATOS
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
    from baco.server.services.orquestador.validaciones import (
        limpiar_cache_catalogos,
    )
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
    assert r3["estado"] == EstadoFlujo.ESPERANDO_PLANTILLA
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
# Tests PASO 2: Registro e invalidación de finalizado
# =========================================================================

def test_registro_conformidad_al_confirmar(client):
    """Verifica que al finalizar se registre finalizado=True."""
    sid = "sesion-test-reg-conf"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.EDICION_FINAL,
        ultimas_opciones=["finalizar"],
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
            finalizado=False,
        ),
    )

    resp = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "finalizar"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] == EstadoFlujo.FINALIZADO

    ses = SESIONES[sid]
    assert ses.borrador.finalizado is True


def test_invalida_conformidad_al_modificar_texto(client):
    """FINALIZADO es terminal para el chat; solo una skill (actualizar_borrador_texto) invalida el finalizado."""
    sid = "sesion-test-inv-conf"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.FINALIZADO,
        ultima_navegacion=["ver_articulo_final"],
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
            finalizado=True,
        ),
    )

    nuevo_texto = (
        "Texto modificado con suficiente cantidad de caracteres para superar el límite mínimo "
        "y verificar que al editar se invalida el finalizado previamente registrado por el usuario."
    )

    # 1. Una edición desde el panel con el artículo cerrado se descarta: sigue finalizado
    resp = client.post("/chat", headers={"X-Session-ID": sid}, json={"texto": nuevo_texto})
    assert resp.status_code == 200
    ses = SESIONES[sid]
    assert ses.estado == EstadoFlujo.FINALIZADO
    assert ses.borrador.finalizado is True

    # 2. Una skill que actualiza el texto invalida el finalizado y reabre la edición final
    actualizar_borrador_texto(sid, nuevo_texto + "\n\nActualizado por skill.")
    assert ses.borrador.finalizado is False
    assert ses.estado == EstadoFlujo.EDICION_FINAL


def test_no_puede_quedar_en_conformidad_con_texto_distinto_al_confirmado(client):
    """Verifica que no se pueda acceder al borrador si no está en FINALIZADO con finalizado=True."""
    sid = "sesion-test-mismatch-conf"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_METADATOS,
        titulo="Título de prueba",
        texto=TEXTO_VALIDO,
        categoria_id=1,
        tags=["instructivo"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título de prueba",
            texto="Texto alterado",
            tipo_plantilla="instructivo",
            categoria_id=1,
            tags=["instructivo"],
            finalizado=False,
        ),
    )

    resp = client.get("/chat/borrador", headers={"X-Session-ID": sid})
    assert resp.status_code == 409
    assert "no está en estado FINALIZADO" in resp.json()["detail"]


# =========================================================================
# Tests PASO 3: Mensajes del flujo de finalizado
# =========================================================================

def test_mensajes_flujo_conformidad(client):
    """Verifica los mensajes del flujo: al pasar a revisión, al finalizar y al editar tras finalizar."""
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
        json={"accion": "enviar_datos", "tags": ["instructivo", "ventas"]},
    ).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_METADATOS
    assert (
        "Si querés hacer cambios antes, editá lo que necesites en el panel"
    ) in r_meta["mensaje"]

    # 2. Edición final y Finalizar
    r_ed = client.post("/chat", headers={"X-Session-ID": sid}, json={"accion": "continuar"}).json()
    assert r_ed["estado"] == EstadoFlujo.EDICION_FINAL
    assert r_ed["mensaje"].startswith(MSG_EDICION_FINAL)
    r_conf = client.post(
        "/chat",
        headers={"X-Session-ID": sid},
        json={"accion": "finalizar"},
    ).json()
    assert r_conf["estado"] == EstadoFlujo.FINALIZADO
    assert MSG_BORRADOR_FINALIZADO in r_conf["mensaje"]
    assert r_conf["opciones"] == []
    assert r_conf["navegacion"] == ["ver_articulo_final"]


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
    assert r_parcial1["accion_panel"]["accion"] == "confirmar_texto"
    mock_buscador.evaluar_texto.assert_not_called()
    assert "Paso 1" in SESIONES[sid].texto_en_edicion

    # Envío parcial 2 sin confirmar_texto -> acumula en texto_en_edicion sin llamar a evaluar_texto
    r_parcial2 = client.post(
        "/chat",
        json={"mensaje": "Paso 2: Configurar la alícuota correspondiente a la jurisdicción provincial."},
    ).json()
    assert r_parcial2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert r_parcial2["accion_panel"]["accion"] == "confirmar_texto"
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


def test_solicitar_categoria_en_formulario_desde_chat(client, mock_buscador):
    """Verifica que en ESPERANDO_METADATOS el chat indique etiquetas en turno 1 y categoría en turno 2 con menú desplegable."""
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = None

    r1 = client.post("/chat", json={"mensaje": "Nueva Guía de Facturación Electrónica"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": TEXTO_VALIDO})
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "instructivo"}).json()
    assert r_meta["estado"] == EstadoFlujo.REVISION_TIPO
    # Nuevo flujo: plantilla -> REVISION_TIPO; 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Turno 1: pide categoría y al menos una etiqueta temática
    assert "una etiqueta temática" in r_meta["mensaje"]
    assert "**categoría**" in r_meta["mensaje"]

    # Turno 2: usuario envía etiquetas temáticas; el bot pide solo la categoría (menú del panel)
    r_cat = client.post("/chat", json={"session_id": sid, "mensaje": "facturacion, afip"}).json()
    assert r_cat["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert "Sólo falta la **categoría**" in r_cat["mensaje"]

    # Turno 3: define categoría con Enviar datos y avanza a revisión
    r_rev = client.post("/chat", json={"session_id": sid, "accion": "enviar_datos", "categoria_id": 4}).json()
    assert r_rev["estado"] == EstadoFlujo.REVISION_METADATOS
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
    assert r_meta["estado"] == EstadoFlujo.REVISION_TIPO
    # Nuevo flujo: plantilla -> REVISION_TIPO; 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
    r_meta = client.post("/chat", json={"session_id": sid, "accion": "continuar_revision"}).json()
    assert r_meta["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Turno 1: ingresa etiquetas por chat
    r_cat = client.post("/chat", json={"session_id": sid, "mensaje": "facturacion, afip"}).json()
    assert r_cat["estado"] == EstadoFlujo.ESPERANDO_METADATOS

    # Turno 2: usuario ingresa la categoría escribiendo 'Ventas' en el chat
    r_rev = client.post("/chat", json={"session_id": sid, "mensaje": "Ventas"}).json()
    # La carga por chat se confirma con Enviar datos (rama arreglar-meta-datos)
    assert r_rev["estado"] == EstadoFlujo.ESPERANDO_METADATOS
    assert r_rev["accion_panel"]["accion"] == "enviar_datos"
    r_rev = client.post("/chat", json={"session_id": sid, "accion": "enviar_datos"}).json()
    assert r_rev["estado"] == EstadoFlujo.REVISION_METADATOS
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
    assert r3["estado"] == EstadoFlujo.REVISION_TIPO
    # Nuevo flujo: plantilla -> REVISION_TIPO; 'continuar_revision' sin categoría/tags -> ESPERANDO_METADATOS
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
    assert r5["estado"] == EstadoFlujo.REVISION_METADATOS
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
    assert r_rev["estado"] == EstadoFlujo.REVISION_TIPO

    # 2. El usuario edita directamente el texto enviando PII (CUIL y correo personal)
    texto_con_pii = (
        "Pasos para dar de alta al cliente en la base corporativa:\n"
        "1. Solicitar la documentación fiscal.\n"
        "2. Verificar el CUIL: 20-30405060-9 del representante legal.\n"
        "3. Remitir la constancia al mail juan.perez@empresa.com para su validación final."
    )
    # Guardado desde el panel en REVISION_TIPO (sin acción)
    r_edit = client.post("/chat", json={"session_id": sid, "texto": texto_con_pii}).json()

    assert r_edit["estado"] == EstadoFlujo.REVISION_TIPO
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


