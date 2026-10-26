from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.config_limites import TEXTO_MAX, TEXTO_MAX_PERCENTIL_99, TEXTO_MIN
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.schemas.recurso import Recurso
from baco.server.services.orquestador import manejar_turno
from baco.server.services.orquestador.sesion import SESIONES, SesionChat


@pytest.fixture
def mock_buscador():
    b = MagicMock()
    b.evaluar_titulo.return_value = {"mensaje": "Sin coincidencia", "coincidencias": []}
    b.evaluar_texto.return_value = {"mensaje": "Sin coincidencia", "coincidencias": []}
    return b


@pytest.fixture
def client(mock_buscador):
    app.dependency_overrides[get_buscador_duplicados] = lambda: mock_buscador
    fake_baco = MagicMock()
    fake_baco.run.return_value = "Resultado simulado del agente"
    app.dependency_overrides[get_baco_agent] = lambda: fake_baco
    c = TestClient(app)
    c.headers.update({"X-API-Key": API_KEY})
    yield c
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Tests en el límite de TEXTO_MAX (6687) y sin recursos
# ==============================================================================

def test_skills_habilitadas_en_limite_exacto_texto_max():
    texto_exacto = "A" * TEXTO_MAX
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Título de prueba para artículo",
        texto_limpio=texto_exacto,
        recursos={},
    )
    assert borrador.skills_habilitadas is True
    assert borrador.skills_motivo is None


def test_skills_deshabilitadas_en_texto_max_mas_uno():
    texto_excedido = "A" * (TEXTO_MAX + 1)
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Título de prueba para artículo",
        texto_limpio=texto_excedido,
        recursos={},
    )
    assert borrador.skills_habilitadas is False
    assert borrador.skills_motivo is not None
    assert f"supera el límite de {TEXTO_MAX}" in borrador.skills_motivo
    assert str(TEXTO_MAX + 1) in borrador.skills_motivo


# ==============================================================================
# 2. Tests de admisión hasta TEXTO_MAX_PERCENTIL_99 (16777)
# ==============================================================================

def test_admision_hasta_texto_max_percentil_99_exacto():
    texto_p99 = "A" * TEXTO_MAX_PERCENTIL_99
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Título de prueba para artículo",
        texto_limpio=texto_p99,
        recursos={},
    )
    assert borrador.skills_habilitadas is False
    assert f"supera el límite de {TEXTO_MAX}" in borrador.skills_motivo


def test_rechazo_mas_alla_de_texto_max_percentil_99():
    with pytest.raises(Exception) as exc:
        ChatOrquestadorRequest(texto="A" * (TEXTO_MAX_PERCENTIL_99 + 1))
    assert f"supera los {TEXTO_MAX_PERCENTIL_99} caracteres" in str(exc.value)


# ==============================================================================
# 3. Tests con y sin recursos
# ==============================================================================

def test_skills_deshabilitadas_cuando_tiene_recursos_aunque_texto_sea_corto():
    rec = Recurso(
        id="rec_1",
        tipo="imagen",
        nombre="Captura",
        referencia="https://example.com/foto.png",
        orden=0,
    )
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Título de prueba para artículo",
        texto_limpio="Texto breve de prueba [[recurso:rec_1]] con contenido.",
        recursos={"rec_1": rec},
    )
    assert borrador.skills_habilitadas is False
    assert borrador.skills_motivo is not None
    assert "recursos multimedia" in borrador.skills_motivo


def test_skills_deshabilitadas_con_recursos_y_texto_excedido_informa_ambos():
    rec = Recurso(
        id="rec_1",
        tipo="imagen",
        nombre="Captura",
        referencia="https://example.com/foto.png",
        orden=0,
    )
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Título de prueba para artículo",
        texto_limpio=("A" * (TEXTO_MAX + 10)) + " [[recurso:rec_1]]",
        recursos={"rec_1": rec},
    )
    assert borrador.skills_habilitadas is False
    assert borrador.skills_motivo is not None
    assert "supera el límite" in borrador.skills_motivo
    assert "recursos multimedia" in borrador.skills_motivo


# ==============================================================================
# 4. El cliente no puede forzar el flag (seguridad del servidor)
# ==============================================================================

def test_cliente_no_puede_forzar_skills_habilitadas():
    rec = Recurso(
        id="rec_1",
        tipo="imagen",
        nombre="Captura",
        referencia="https://example.com/foto.png",
        orden=0,
    )
    # Intento malicioso de inyectar skills_habilitadas=True en el diccionario
    data = {
        "modo": "nuevo",
        "titulo": "Título de prueba para artículo",
        "texto_limpio": "Texto con imagen [[recurso:rec_1]]",
        "recursos": {"rec_1": rec},
        "skills_habilitadas": True,
        "skills_motivo": None,
    }
    borrador = BorradorSesion(**data)
    assert borrador.skills_habilitadas is False
    assert borrador.skills_motivo is not None


# ==============================================================================
# 5. POST /chat/aplicar-plantilla y POST /chat/auditar-semantica devuelven 422
# ==============================================================================

def test_endpoints_skills_devuelven_422_cuando_flag_es_false_por_recursos(client):
    sid = "test-session-skills-recursos"
    rec = Recurso(
        id="rec_1",
        tipo="imagen",
        nombre="Captura",
        referencia="https://example.com/foto.png",
        orden=0,
    )
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Configuración de prueba en Ventas",
        texto_limpio="Contenido válido para el borrador [[recurso:rec_1]] con suficientes caracteres de prueba.",
        recursos={"rec_1": rec},
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
        conforme=True,
    )
    sesion = SesionChat(session_id=sid, estado=EstadoFlujo.CONFORMIDAD_USUARIO, borrador=borrador)
    SESIONES[sid] = sesion

    # Probar aplicar-plantilla
    res_plantilla = client.post("/chat/aplicar-plantilla", headers={"X-Session-ID": sid})
    assert res_plantilla.status_code == 422
    assert "recursos multimedia" in res_plantilla.json()["detail"]

    # Probar auditar-semantica
    res_auditoria = client.post("/chat/auditar-semantica", headers={"X-Session-ID": sid})
    assert res_auditoria.status_code == 422
    assert "recursos multimedia" in res_auditoria.json()["detail"]


def test_endpoints_skills_devuelven_422_cuando_flag_es_false_por_longitud(client):
    sid = "test-session-skills-largo"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Configuración de prueba en Ventas",
        texto_limpio="A" * (TEXTO_MAX + 50),
        recursos={},
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
        conforme=True,
    )
    sesion = SesionChat(session_id=sid, estado=EstadoFlujo.CONFORMIDAD_USUARIO, borrador=borrador)
    SESIONES[sid] = sesion

    res_plantilla = client.post("/chat/aplicar-plantilla", headers={"X-Session-ID": sid})
    assert res_plantilla.status_code == 422
    assert f"supera el límite de {TEXTO_MAX}" in res_plantilla.json()["detail"]

    res_auditoria = client.post("/chat/auditar-semantica", headers={"X-Session-ID": sid})
    assert res_auditoria.status_code == 422
    assert f"supera el límite de {TEXTO_MAX}" in res_auditoria.json()["detail"]


def test_endpoints_skills_devuelven_200_cuando_flag_es_true(client):
    sid1 = "test-session-skills-ok-1"
    borrador1 = BorradorSesion(
        modo="nuevo",
        titulo="Configuración de listas de precios en Ventas",
        texto_limpio="Texto completamente válido sin recursos y dentro del límite de caracteres para skills.",
        texto_original_conforme="Texto completamente válido sin recursos y dentro del límite de caracteres para skills.",
        recursos={},
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
        conforme=True,
    )
    sesion1 = SesionChat(session_id=sid1, estado=EstadoFlujo.CONFORMIDAD_USUARIO, borrador=borrador1)
    SESIONES[sid1] = sesion1

    res_plantilla = client.post("/chat/aplicar-plantilla", headers={"X-Session-ID": sid1})
    assert res_plantilla.status_code == 200

    sid2 = "test-session-skills-ok-2"
    borrador2 = BorradorSesion(
        modo="nuevo",
        titulo="Configuración de listas de precios en Ventas",
        texto_limpio="Texto completamente válido sin recursos y dentro del límite de caracteres para skills.",
        texto_original_conforme="Texto completamente válido sin recursos y dentro del límite de caracteres para skills.",
        recursos={},
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
        conforme=True,
    )
    sesion2 = SesionChat(session_id=sid2, estado=EstadoFlujo.CONFORMIDAD_USUARIO, borrador=borrador2)
    SESIONES[sid2] = sesion2

    res_auditoria = client.post("/chat/auditar-semantica", headers={"X-Session-ID": sid2})
    assert res_auditoria.status_code == 200


# ==============================================================================
# 6. Orquestador: Opciones cuando el texto pegado trae recursos
# ==============================================================================

@pytest.mark.anyio
async def test_orquestador_flujo_normal_al_pegar_texto_con_recursos(mock_buscador):
    sid = "test-orq-recursos-opciones"
    sesion = SesionChat(session_id=sid, estado=EstadoFlujo.ESPERANDO_TEXTO, titulo="Configuración del módulo")
    SESIONES[sid] = sesion

    texto_con_foto = "Pasos para ingresar al módulo: ![captura](https://finneg.com/img/screen.png) y guardar."
    req = ChatOrquestadorRequest(session_id=sid, texto=texto_con_foto)
    resp = await manejar_turno(req, mock_buscador)

    assert "confirmar_texto" in resp.opciones

    req_conf = ChatOrquestadorRequest(session_id=sid, accion="confirmar_texto")
    resp_conf = await manejar_turno(req_conf, mock_buscador)
    assert resp_conf.borrador is not None
    assert resp_conf.borrador.skills_habilitadas is False
    assert "recursos" in resp_conf.borrador.skills_motivo.lower()


@pytest.mark.anyio
async def test_orquestador_quitar_recursos_habilita_skills(mock_buscador):
    sid = "test-orq-quitar-recursos"
    sesion = SesionChat(session_id=sid, estado=EstadoFlujo.ESPERANDO_TEXTO, titulo="Configuración del módulo")
    SESIONES[sid] = sesion

    # Paso 1: Pega texto con imagen
    texto_con_foto = "Pasos para ingresar al módulo: ![captura](https://finneg.com/img/screen.png) y guardar."
    req1 = ChatOrquestadorRequest(session_id=sid, texto=texto_con_foto)
    await manejar_turno(req1, mock_buscador)

    # Paso 2: Elige quitar recursos
    req2 = ChatOrquestadorRequest(session_id=sid, accion="quitar_recursos")
    resp2 = await manejar_turno(req2, mock_buscador)

    assert resp2.borrador is not None
    assert len(resp2.borrador.recursos) == 0
    assert resp2.borrador.skills_habilitadas is True
    assert resp2.borrador.skills_motivo is None


@pytest.mark.anyio
async def test_orquestador_seguir_con_recursos_deshabilita_skills(mock_buscador):
    sid = "test-orq-seguir-recursos"
    sesion = SesionChat(session_id=sid, estado=EstadoFlujo.ESPERANDO_TEXTO, titulo="Configuración del módulo")
    SESIONES[sid] = sesion

    # Paso 1: Pega texto con imagen
    texto_con_foto = "Pasos para ingresar al módulo: ![captura](https://finneg.com/img/screen.png) y guardar."
    req1 = ChatOrquestadorRequest(session_id=sid, texto=texto_con_foto)
    await manejar_turno(req1, mock_buscador)

    # Paso 2: Elige seguir con recursos
    req2 = ChatOrquestadorRequest(session_id=sid, accion="seguir_con_recursos")
    resp2 = await manejar_turno(req2, mock_buscador)

    assert resp2.borrador is not None
    assert len(resp2.borrador.recursos) == 1
    assert resp2.borrador.skills_habilitadas is False
    assert "recursos multimedia" in resp2.borrador.skills_motivo
