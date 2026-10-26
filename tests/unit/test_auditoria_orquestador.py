"""Tests de regresión para los 8 casos de la auditoría crítica del orquestador de BACO."""
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.config_limites import TEXTO_MAX, TEXTO_MIN
from baco.server.schemas.chat_orquestado import BorradorSesion, EstadoFlujo
from baco.server.schemas.recurso import BloqueItem, ConfirmarBloquesRequest, RecursoBloqueInput
from baco.server.services.agente_service import _obtener_texto_limpio_estricto
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.recursos_service import (
    derivar_desde_bloques,
    extraer_recursos_y_texto_limpio,
)
from baco.server.services.orquestador.sesion import SESIONES, SesionChat, gestor_sesiones


@pytest.fixture(autouse=True)
def limpiar_estado():
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


def test_caso_1_marcador_canonico_unico_ids_monotonicos_y_url_repetida(client):
    """Decisiones 1 y 2:
    - /chat/bloques y derivar_desde_bloques usan [[recurso:rec_N]] (nunca [[R1]]).
    - Si la misma URL aparece dos veces, ambos marcadores apuntan al mismo rec_id y la validación lo permite.
    - El contador monotónico por borrador nunca reutiliza el ID de un recurso eliminado.
    """
    req = ConfirmarBloquesRequest(
        bloques=[
            BloqueItem(tipo="texto", contenido="Paso 1: abrir configuración general del módulo contable."),
            BloqueItem(tipo="recurso", recurso=RecursoBloqueInput(url="https://bc.finneg.com/uploads/img1.png", nombre="Img 1")),
            BloqueItem(tipo="texto", contenido="Paso 2: repetir referencia a la misma captura y agregar otra."),
            BloqueItem(tipo="recurso", recurso=RecursoBloqueInput(url="https://bc.finneg.com/uploads/img1.png", nombre="Img 1 bis")),
            BloqueItem(tipo="recurso", recurso=RecursoBloqueInput(url="https://bc.finneg.com/uploads/img2.png", nombre="Img 2")),
        ]
    )
    texto_limpio, recursos, _ = derivar_desde_bloques(req.bloques)
    assert "[[R1]]" not in texto_limpio
    assert texto_limpio.count("[[recurso:rec_1]]") == 2
    assert "[[recurso:rec_2]]" in texto_limpio
    assert set(recursos.keys()) == {"rec_1", "rec_2"}

    # Verificar contador monotónico en sesión tras eliminar rec_2 y agregar un nuevo recurso
    sid = "ses-monotonico"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Título de prueba válido",
        texto_limpio=texto_limpio,
        recursos=recursos,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título de prueba válido",
            texto_limpio=texto_limpio,
            recursos=recursos,
        ),
    )
    assert gestor_sesiones.eliminar_recurso_multimedia(sid, "rec_2") is True
    assert "rec_2" not in SESIONES[sid].borrador.recursos

    resp_add = client.post(
        "/chat/recursos/agregar",
        headers={"X-Session-ID": sid},
        json={"referencia": "https://bc.finneg.com/uploads/img3.png", "nombre": "Img 3"},
    )
    assert resp_add.status_code == 200
    assert resp_add.json()["id"] == "rec_3"  # Nunca reutiliza rec_2


def test_caso_2_img_html_y_sanitizacion_alt_y_url():
    """Decisiones 5 y 6 (Caso 2):
    - <img ...> se convierte a recurso con marcador [[recurso:rec_1]].
    - sanitizar_url_recurso quita parámetros sensibles (token) pero conserva query no sensible (v=2).
    - sanitizar_borrador limpia PII del alt/nombre del recurso.
    """
    entrada = (
        "Paso 1: abrir menú.\n\n"
        '<img src="https://bc.finneg.com/uploads/default/1.png?token=secreto123&v=2" alt="Captura de juan.perez@gmail.com">\n\n'
        "Paso 2: guardar."
    )
    texto_limpio, recursos = extraer_recursos_y_texto_limpio(entrada)
    assert "<img" not in texto_limpio
    assert "[[recurso:rec_1]]" in texto_limpio
    assert len(recursos) == 1
    r1 = recursos["rec_1"]
    assert r1.tipo == "imagen"
    assert r1.referencia == "https://bc.finneg.com/uploads/default/1.png?v=2"
    assert "token=" not in r1.referencia
    assert "juan.perez@gmail.com" not in r1.nombre
    assert "usuario@ejemplo.com" in r1.nombre


def test_caso_3_video_y_audio_html():
    """Decisión 5 (Caso 3):
    - <video> y <audio> se convierten a recursos y se reemplazan por [[recurso:rec_N]].
    """
    entrada = (
        "Paso 1: ver video.\n\n"
        '<video src="https://bc.finneg.com/uploads/default/demo.mp4" controls></video>\n\n'
        "Paso 2: escuchar audio.\n\n"
        '<audio controls><source src="https://bc.finneg.com/uploads/default/nota.mp3" type="audio/mpeg"></audio>\n\n'
        "Paso 3: continuar."
    )
    texto_limpio, recursos = extraer_recursos_y_texto_limpio(entrada)
    assert "<video" not in texto_limpio
    assert "<audio" not in texto_limpio
    assert "[[recurso:rec_1]]" in texto_limpio
    assert "[[recurso:rec_2]]" in texto_limpio
    assert recursos["rec_1"].tipo == "video"
    assert recursos["rec_1"].referencia == "https://bc.finneg.com/uploads/default/demo.mp4"
    assert recursos["rec_2"].tipo == "audio"
    assert recursos["rec_2"].referencia == "https://bc.finneg.com/uploads/default/nota.mp3"


def test_caso_4_iframe_dominio_permitido_vs_no_permitido():
    """Decisiones 5 y 6 (Caso 4):
    - <iframe> de dominio permitido (YouTube, Vimeo, Google Docs, etc.) se extrae como recurso.
    - <iframe> de dominio no permitido queda como texto.
    """
    entrada = (
        "Paso 1: ver presentación.\n\n"
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?access_token=abc" width="560" height="315"></iframe>\n\n'
        "Paso 2: iframe externo.\n\n"
        '<iframe src="https://malicioso.example.org/embed/123" width="400"></iframe>\n\n'
        "Paso 3: fin."
    )
    texto_limpio, recursos = extraer_recursos_y_texto_limpio(entrada)
    assert "youtube.com/embed/dQw4w9WgXcQ" not in texto_limpio
    assert "[[recurso:rec_1]]" in texto_limpio
    assert len(recursos) == 1
    assert recursos["rec_1"].referencia == "https://www.youtube.com/embed/dQw4w9WgXcQ"
    # El iframe de dominio no permitido queda como texto
    assert "https://malicioso.example.org/embed/123" in texto_limpio


def test_caso_5_links_con_query_y_urls_sueltas_con_extension():
    """Decisiones 5 y 6 (Caso 5):
    - Evaluar extensión sobre URL sin query.
    - Aceptar cualquier URL suelta con extensión multimedia o de documento.
    - Quitar solo parámetros sensibles (token) conservando no sensibles (v=123).
    """
    entrada = (
        "Ver [Manual PDF](https://empresa.com/manual.pdf?token=abc) "
        "y [Adjunto|attachment](https://bc.finneg.com/uploads/doc.docx) "
        "y [Imagen con query](https://cdn.com/foto.png?v=123) "
        "y [Enlace web normal](https://finneg.com/ayuda) y URL suelta mp4:\n"
        "https://cdn.empresa.com/video.mp4\n"
        "Fin."
    )
    texto_limpio, recursos = extraer_recursos_y_texto_limpio(entrada)
    assert "manual.pdf" not in texto_limpio
    assert "token=abc" not in texto_limpio
    assert "foto.png" not in texto_limpio
    assert "https://cdn.empresa.com/video.mp4" not in texto_limpio
    assert "[Enlace web normal](https://finneg.com/ayuda)" in texto_limpio
    assert len(recursos) == 4
    assert recursos["rec_1"].referencia == "https://empresa.com/manual.pdf"
    assert recursos["rec_2"].referencia == "https://bc.finneg.com/uploads/doc.docx"
    assert recursos["rec_3"].referencia == "https://cdn.com/foto.png?v=123"
    assert recursos["rec_4"].referencia == "https://cdn.empresa.com/video.mp4"


def test_caso_6_bloques_de_codigo_cercados_e_inline_intactos():
    """Decisión 5 (Caso 6):
    - Enmascarar bloques de código (cercados e inline) antes de extraer y restaurarlos idénticos.
    """
    bloque_codigo = (
        "```bash\n"
        "  curl -O https://bc.finneg.com/uploads/default/script.pdf\n"
        "  ![no_es_imagen](https://bc.finneg.com/uploads/default/fake.png)\n"
        "  https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
        "```"
    )
    inline_codigo = "`![inline_img](https://bc.finneg.com/uploads/inline.png)`"
    entrada = f"Ejemplo de código:\n\n{bloque_codigo}\n\nY en línea {inline_codigo} fin."

    texto_limpio, recursos = extraer_recursos_y_texto_limpio(entrada)
    assert recursos == {}
    assert bloque_codigo in texto_limpio
    assert inline_codigo in texto_limpio


def test_caso_7_reordenar_eliminar_y_enriquecer_decision_texto(client, mock_buscador):
    """Decisiones 3, 4 y 7:
    - Reordenar: los marcadores quedan en sus posiciones del texto y se permutan los recursos que ocupan cada slot.
    - Eliminar: elimina también su marcador en borrador.texto_limpio y sesion.texto_limpio.
    - handle_decision_texto / consolidar_texto_enriquecimiento: preserva texto_base_limpio y fusiona recursos sin colisión de IDs.
    """
    # 1. Flujo hacia DECISION_TEXTO con artículo base + aporte largo (>250 chars) con imagen propia
    r1 = client.post("/chat", json={"mensaje": "Título sin coincidencia directa"}).json()
    sid = r1["session_id"]

    texto_base_api = (
        "### Paso 1 del artículo oficial\n\n"
        "Texto base oficial que debe preservarse siempre íntegro.\n\n"
        "![Captura Base](https://bc.finneg.com/uploads/base.png)"
    )
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia semántica detectada",
        "coincidencias": [(555, "Artículo Oficial Existente", "https://bc.finneg.com/t/555")],
    }
    aporte_usuario = (
        "### Aporte adicional del usuario\n\n"
        + ("Detalle técnico nuevo agregado por el operador para enriquecer la guía. " * 5)
        + "\n\n![Captura Aporte](https://bc.finneg.com/uploads/aporte.png)"
    )
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": aporte_usuario}).json()
    assert r2["estado"] == EstadoFlujo.DECISION_TEXTO

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (texto_base_api, 21, ["instructivo", "contabilidad"])
        r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    borrador = SESIONES[sid].borrador
    assert "Texto base oficial que debe preservarse siempre íntegro." in borrador.texto_limpio
    assert "Detalle técnico nuevo agregado por el operador" in borrador.texto_limpio
    assert "[[recurso:rec_1]]" in borrador.texto_limpio
    assert "[[recurso:rec_2]]" in borrador.texto_limpio
    assert borrador.recursos["rec_1"].referencia == "https://bc.finneg.com/uploads/base.png"
    assert borrador.recursos["rec_2"].referencia == "https://bc.finneg.com/uploads/aporte.png"

    # 2. Reordenar recursos (permutar rec_1 y rec_2 en los slots del texto sin cambiar el texto circundante)
    resp_reord = client.put(
        "/chat/recursos/reordenar",
        headers={"X-Session-ID": sid},
        json={"from_index": 0, "to_index": 1},
    )
    assert resp_reord.status_code == 200
    tl_reord = SESIONES[sid].borrador.texto_limpio
    assert tl_reord.index("[[recurso:rec_2]]") < tl_reord.index("[[recurso:rec_1]]")
    assert "Texto base oficial que debe preservarse siempre íntegro." in tl_reord
    assert SESIONES[sid].borrador.texto.index("aporte.png") < SESIONES[sid].borrador.texto.index("base.png")

    # 3. Eliminar rec_2 quita también su marcador de borrador.texto_limpio y sesion.texto_limpio
    resp_del = client.delete("/chat/recursos/rec_2", headers={"X-Session-ID": sid})
    assert resp_del.status_code == 200
    assert "[[recurso:rec_2]]" not in SESIONES[sid].borrador.texto_limpio
    assert "[[recurso:rec_2]]" not in SESIONES[sid].texto_limpio
    assert "[[recurso:rec_1]]" in SESIONES[sid].borrador.texto_limpio


def test_caso_8_solo_recursos_sin_texto_y_cotas_sin_marcadores(client):
    """Decisión 8 (Caso 8):
    - Validar texto efectivo descontando marcadores y medir las cotas (TEXTO_MIN a TEXTO_MAX / TEXTO_MAX_PERCENTIL_99) sobre el texto sin marcadores.
    """
    # 1. Borrador con solo marcadores y sin texto efectivo es rechazado en _obtener_texto_limpio_estricto
    borrador_solo_rec = BorradorSesion(
        modo="nuevo",
        titulo="Guía solo imagen",
        texto_limpio="[[recurso:rec_1]]\n\n[[recurso:rec_2]]",
        recursos={
            "rec_1": {"id": "rec_1", "tipo": "imagen", "nombre": "1", "referencia": "https://bc.finneg.com/1.png", "orden": 0},
            "rec_2": {"id": "rec_2", "tipo": "imagen", "nombre": "2", "referencia": "https://bc.finneg.com/2.png", "orden": 1},
        },
    )
    with pytest.raises(HTTPException) as exc:
        _obtener_texto_limpio_estricto(borrador_solo_rec)
    assert exc.value.status_code == 400

    # 2. En /chat (confirmar_texto), enviar 2 imágenes sin prosa real (< 20 chars sin marcadores) falla por TEXTO_MIN
    r1 = client.post("/chat", json={"mensaje": "Título válido para prueba de cota"}).json()
    sid = r1["session_id"]
    solo_dos_imagenes = (
        "![img1](https://bc.finneg.com/uploads/1.png)\n\n"
        "![img2](https://bc.finneg.com/uploads/2.png)"
    )
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": solo_dos_imagenes}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    assert str(TEXTO_MIN) in r2["mensaje"]

    # 3. En POST /chat/bloques, enviar solo recurso sin texto suficiente falla con 400
    resp_bloques_vacio = client.post(
        "/chat/bloques",
        json={
            "session_id": sid,
            "bloques": [
                {"tipo": "recurso", "recurso": {"url": "https://bc.finneg.com/uploads/1.png", "nombre": "Img"}},
            ],
        },
    )
    assert resp_bloques_vacio.status_code == 400

    # 4. Un texto con TEXTO_MAX (umbral de skills) caracteres efectivos + marcadores [[recurso:rec_N]] es admitido
    prosa_exacta = "A" * TEXTO_MAX
    texto_con_img = f"{prosa_exacta}\n\n![img](https://bc.finneg.com/uploads/1.png)"
    r_max = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": texto_con_img}).json()
    assert r_max["estado"] != EstadoFlujo.ESPERANDO_TEXTO
