"""Tests para la anonimización preventiva de PII en la frontera de entrada.

Verifica:
1. Turno 1 con PII: El título/mensaje se anonimiza preventivamente antes de buscar duplicados,
   y se emite aviso_privacidad de forma inmediata en el Turno 1.
2. Rechazo por texto corto (< TEXTO_MIN): Sanitiza antes de validar longitud; el texto devuelto
   y la sesión nunca exponen PII en claro y contienen aviso_privacidad.
3. RequestValidationError: Los errores 422 eliminan permanentemente el campo 'input'.
4. Idempotencia: La re-sanitización de textos ya anonimizados no re-detecta marcadores ni altera el contenido.
5. texto_editor: El editor siempre recibe texto anonimizado (con marcadores protegidos) y jamás PII en claro.
6. Casos borde: Múltiples PII, datos repetidos, formatos variados de DNI y CUIT, y correos personales vs genéricos.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados, get_baco_agent
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.validar_articulo import sanitizar_borrador
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos
from baco.server.services.orquestador.sesion import SESIONES


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


def test_turno_1_titulo_con_pii_se_anonimiza_y_emite_aviso(client, mock_buscador):
    """En el Turno 1, si el usuario envía un título con PII, este se anonimiza antes de
    la búsqueda de duplicados y la respuesta incluye aviso_privacidad inmediatamente."""
    titulo_con_pii = "Alta de operador CUIT 20-30405060-9 y correo juan.perez@gmail.com"
    r1 = client.post("/chat", json={"mensaje": titulo_con_pii}).json()

    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    # El dato personal NUNCA debe estar en claro
    assert "20-30405060-9" not in str(r1)
    assert "juan.perez@gmail.com" not in str(r1)
    # Debe emitir aviso de privacidad en este primer turno
    assert r1["aviso_privacidad"] is not None
    assert "seguridad" in r1["aviso_privacidad"].lower() or "preservarte" in r1["aviso_privacidad"].lower()

    # El buscador de duplicados solo debe haber recibido el título anonimizado
    mock_buscador.evaluar_titulo.assert_called_once()
    args_llamada = mock_buscador.evaluar_titulo.call_args[0]
    titulo_enviado_al_buscador = args_llamada[0]
    assert "20-30405060-9" not in titulo_enviado_al_buscador
    assert "juan.perez@gmail.com" not in titulo_enviado_al_buscador
    assert "[CUIT_OCULTO]" in titulo_enviado_al_buscador
    assert "usuario@ejemplo.com" in titulo_enviado_al_buscador

    # La sesión en memoria no debe contener el dato en claro
    sesion = SESIONES[r1["session_id"]]
    assert "20-30405060-9" not in sesion.titulo
    assert "juan.perez@gmail.com" not in sesion.titulo
    assert "[CUIT_OCULTO]" in sesion.titulo


def test_rechazo_por_texto_corto_nunca_devuelve_pii_en_claro(client, mock_buscador):
    """Si el usuario envía un texto menor a TEXTO_MIN con PII, se sanitiza antes de validar longitud."""
    r1 = client.post("/chat", json={"mensaje": "Manual de Alta de Clientes en el Sistema"}).json()
    sid = r1["session_id"]

    texto_corto_con_pii = "CUIT 20-30405060-9"
    r2 = client.post(
        "/chat",
        json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_corto_con_pii},
    ).json()

    # Rechazado por longitud mínima de texto
    assert "mínimo" in r2["mensaje"].lower() or "caracteres" in r2["mensaje"].lower()
    # El PII NO debe estar en claro en ningún campo de la respuesta
    assert "20-30405060-9" not in str(r2)
    # Debe contener aviso de privacidad
    assert r2["aviso_privacidad"] is not None
    # El texto limpio interno quedó anonimizado
    assert "[CUIT_OCULTO]" in r2["texto_limpio"]


def test_request_validation_error_elimina_campo_input(client):
    """Un error 422 por payload inválido no debe incluir el campo 'input' con datos del request."""
    # Enviar categoria_id con tipo inválido (str en vez de int)
    resp = client.post("/chat", json={"mensaje": "Test de validación", "categoria_id": "NO_ES_ENTERO"})
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    for err in body["detail"]:
        assert "input" not in err, f"El error 422 contiene el campo prohibido 'input': {err}"


def test_idempotencia_sanitizacion():
    """Sanitizar un texto ya sanitizado no genera nuevos reemplazos ni altera el contenido."""
    texto_original = "Contacto CUIT 20-30405060-9 y mail maria.gonzalez@gmail.com DNI: 28.999.888"
    res1 = sanitizar_borrador(texto=texto_original)

    assert res1["reemplazos_total"] >= 3
    texto_sanitizado = res1["texto_sanitizado"]
    assert "[CUIT_OCULTO]" in texto_sanitizado
    assert "usuario@ejemplo.com" in texto_sanitizado
    assert "[DOCUMENTO_OCULTO]" in texto_sanitizado

    # Segunda corrida sobre el resultado sanitizado
    res2 = sanitizar_borrador(texto=texto_sanitizado)
    assert res2["reemplazos_total"] == 0
    assert res2["texto_sanitizado"] == texto_sanitizado
    assert res2["aviso_privacidad"] is None


def test_texto_editor_siempre_anonimizado(client, mock_buscador):
    """texto_editor en la respuesta y en la sesión contiene marcadores protegidos y nunca PII crudo."""
    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Seguridad Operativa"}).json()
    sid = r1["session_id"]

    texto_con_pii = (
        "Pasos de configuración inicial del sistema operativo corporativo:\n\n"
        "1. Conectar con token Bearer AAAAAAAAAAAAAAAAAAAAAAAA y validar CUIT 20-30405060-9.\n"
        "2. Guardar y verificar la conexión."
    )
    r2 = client.post(
        "/chat",
        json={"session_id": sid, "texto": texto_con_pii},
    ).json()

    sesion = SESIONES[sid]
    assert sesion.texto_editor is not None
    assert "20-30405060-9" not in sesion.texto_editor
    assert "AAAAAAAAAAAAAAAAAAAAAAAA" not in sesion.texto_editor
    assert "[CUIT_OCULTO]" in sesion.texto_editor
    assert "[TOKEN_OCULTO]" in sesion.texto_editor


def test_casos_borde_multiples_pii_y_formatos(client, mock_buscador):
    """Múltiples PII en un solo mensaje, formatos diversos de DNI y exclusión de buzones genéricos."""
    titulo = "Guía Técnica de Cobranzas y Facturación de Ventas"
    r1 = client.post("/chat", json={"mensaje": titulo}).json()
    sid = r1["session_id"]

    texto_casos_borde = (
        "Procedimiento con múltiples datos sensibles y variaciones de formato:\n\n"
        "- Operador 1: DNI 30.123.456 y CUIL: 20-30405060-9\n"
        "- Operador 2 con DNI sin puntos: documento 35123456\n"
        "- Correo personal: juan.perez@gmail.com\n"
        "- Correo genérico permitido: soporte@empresa.com y ventas@finnegans.com.ar\n"
        "- Tarjeta con formato agrupado: 4532-0151-1283-0366 (titular Juan Perez)\n"
        "- CUIT repetido: 20-30405060-9 y 20-30405060-9\n"
        "- Credencial secreta: password: SuperPasswordSecreto123\n"
    )

    r2 = client.post(
        "/chat",
        json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_casos_borde},
    ).json()

    # Ninguno de los datos personales reales debe figurar en la respuesta
    assert "30.123.456" not in str(r2)
    assert "35123456" not in str(r2)
    assert "20-30405060-9" not in str(r2)
    assert "juan.perez@gmail.com" not in str(r2)
    assert "4532-0151-1283-0366" not in str(r2)
    assert "SuperPasswordSecreto123" not in str(r2)

    # Los correos institucionales o buzones genéricos se conservan
    assert "soporte@empresa.com" in r2["texto_limpio"]
    assert "ventas@finnegans.com.ar" in r2["texto_limpio"]


def test_frontend_anonimizacion_en_pantalla_y_editor():
    """Verifica que el frontend no exponga PII en burbujas ni retenga texto crudo en el editor."""
    from pathlib import Path
    app_js = Path("frontend/js/app.js").read_text(encoding="utf-8")
    estados_js = Path("frontend/js/estados.js").read_text(encoding="utf-8")
    api_mock_js = Path("frontend/js/api-mock.js").read_text(encoding="utf-8")

    # 1. En app.js existe anonimizarTextoFront y la burbuja de usuario no muestra PII
    assert "anonimizarTextoFront" in app_js
    assert "burbuja('me', esc(anonimizarTextoFront(etiquetaUsuario)))" in app_js

    # 2. Re-renderiza los bloques del editor al recibir borrador sanitizado
    assert "reconstruirBloques(bloquesAutorizados, recsAutorizados, b);\n        }\n        renderBloques();" in app_js.replace("\r\n", "\n")

    # 3. Estados actualiza estado.form.titulo cuando el servidor devuelve r.titulo
    assert "estado.form.titulo = r.titulo;" in estados_js

    # 4. api-mock.js sanitiza tanto texto como título
    assert "t = limpiar(t);" in api_mock_js
    assert "limpiar(String(titulo || ''))" in api_mock_js

