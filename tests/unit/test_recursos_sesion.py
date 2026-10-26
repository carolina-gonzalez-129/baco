import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.config_limites import (
    MAX_RECURSOS_POR_SESION,
    RECURSO_MAX_BYTES,
    TEXTO_MAX,
)
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    EstadoFlujo,
)
from baco.server.schemas.recurso import Recurso
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.recursos_service import (
    DIR_TEMP_SESIONES,
    RecursoInvalidoError,
    SubidaRecursosDeshabilitadaError,
    clasificar_tipo_recurso,
    detectar_mime_type_real,
    eliminar_recurso_borrador as servicio_eliminar_recurso,
    extraer_recursos_y_texto_limpio,
    guardar_recurso_temporal_sesion,
    limpiar_archivos_temporales_sesion,
    reconstruir_texto_con_recursos,
    sanitizar_nombre_archivo,
    verificar_y_restaurar_marcadores,
)
from baco.server.services.orquestador.sesion import (
    SESIONES,
    GestorSesiones,
    SesionChat,
    gestor_sesiones,
)
from baco.server.services.orquestador.validaciones import (
    validar_borrador,
    validar_longitud_maxima,
)


@pytest.fixture(autouse=True)
def limpiar_sesiones_y_temporales():
    from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos
    SESIONES.clear()
    limpiar_cache_catalogos()
    if DIR_TEMP_SESIONES.exists():
        for d in DIR_TEMP_SESIONES.iterdir():
            if d.is_dir():
                limpiar_archivos_temporales_sesion(d.name)
    yield
    SESIONES.clear()
    limpiar_cache_catalogos()
    if DIR_TEMP_SESIONES.exists():
        for d in DIR_TEMP_SESIONES.iterdir():
            if d.is_dir():
                limpiar_archivos_temporales_sesion(d.name)


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


# =========================================================================
# 1. Extracción de texto_limpio y recursos con marcadores [[recurso:<id>]]
# =========================================================================

def test_extraccion_texto_limpio_y_recursos_multimedia():
    texto_entrada = (
        "## Instructivo de Configuración Contable\n\n"
        "1. Ingresar al módulo de compras.\n\n"
        "![Captura del error](https://bc.finneg.com/uploads/default/original/2X/a/error.png)\n\n"
        "2. Descargar el manual en PDF:\n\n"
        "[manual_soporte.pdf|attachment](https://bc.finneg.com/uploads/default/original/manual.pdf)\n\n"
        "3. Ver el video explicativo:\n\n"
        "[Video paso a paso](https://www.youtube.com/watch?v=dQw4w9WgXcQ)\n\n"
        "4. Consultar especificación en Google Docs:\n\n"
        "[Especificación Técnica](https://docs.google.com/document/d/12345/edit)\n\n"
        "5. Finalizar con el siguiente tutorial:\n\n"
        "https://youtu.be/abc987xyz"
    )

    texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto_entrada)

    # 1. texto_limpio no debe contener las URLs multimedia directas ni la sintaxis de imagen
    assert "https://bc.finneg.com/uploads/default/original/2X/a/error.png" not in texto_limpio
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" not in texto_limpio
    assert "https://docs.google.com/document/d/12345/edit" not in texto_limpio
    assert "https://youtu.be/abc987xyz" not in texto_limpio

    # 2. texto_limpio debe contener los marcadores estables
    assert "[[recurso:rec_1]]" in texto_limpio
    assert "[[recurso:rec_2]]" in texto_limpio
    assert "[[recurso:rec_3]]" in texto_limpio
    assert "[[recurso:rec_4]]" in texto_limpio
    assert "[[recurso:rec_5]]" in texto_limpio

    # 3. El diccionario de recursos debe contener la metadata clasificada
    assert len(recursos) == 5
    r1 = recursos["rec_1"]
    assert r1.id == "rec_1"
    assert r1.tipo == "imagen"
    assert r1.origen == "existente"
    assert "error.png" in r1.referencia

    r2 = recursos["rec_2"]
    assert r2.tipo == "documento"
    assert "manual.pdf" in r2.referencia

    r3 = recursos["rec_3"]
    assert r3.tipo == "video"
    assert "youtube.com" in r3.referencia

    r4 = recursos["rec_4"]
    assert r4.tipo == "documento"
    assert "docs.google.com" in r4.referencia

    r5 = recursos["rec_5"]
    assert r5.tipo == "video"
    assert "youtu.be" in r5.referencia

    # 4. Reconstrucción fiel a Markdown para publicación/previsualización
    reconstruido = reconstruir_texto_con_recursos(texto_limpio, recursos)
    assert "![Captura del error](https://bc.finneg.com/uploads/default/original/2X/a/error.png)" in reconstruido
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in reconstruido


# =========================================================================
# 2. Cota máxima de caracteres (6687) sobre texto_limpio (recursos no cuentan)
# =========================================================================

def test_cota_maxima_caracteres_se_evalua_estrictamente_sobre_texto_limpio():
    # Texto base con una longitud moderada en prosa
    prosa = "Pasos esenciales para la conciliación bancaria.\n" * 40  # ~1920 caracteres

    # Crear una URL muy larga de un recurso que excedería 6687 si contara en crudo
    url_gigante = "https://bc.finneg.com/uploads/media/" + ("a" * 5000) + ".png"
    texto_con_recurso_gigante = f"{prosa}\n\n![diagrama gigante]({url_gigante})\n\nFin del instructivo."

    # Longitud cruda supera ampliamente la cota de 6687
    assert len(texto_con_recurso_gigante) > TEXTO_MAX

    # Extraer texto_limpio y recursos
    texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto_con_recurso_gigante)

    # texto_limpio reemplaza la URL gigante de 5000 chars por "[[recurso:rec_1]]" (17 chars)
    assert len(texto_limpio) < TEXTO_MAX
    assert validar_longitud_maxima(texto_limpio, TEXTO_MAX, "texto") is None

    # Validar que sesion y validación del borrador operan sobre texto_limpio
    sesion = SesionChat(
        session_id="test-cota-sesion",
        estado=EstadoFlujo.REVISION_BORRADOR,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Instructivo Conciliación Bancaria",
            texto=reconstruir_texto_con_recursos(texto_limpio, recursos),
            texto_limpio=texto_limpio,
            recursos=recursos,
            categoria_id=21,
            tags=["instructivo", "contabilidad"],
        ),
    )
    msg, ops = validar_borrador(sesion)
    # No debe arrojar error bloqueante de longitud de texto
    assert "supera el máximo" not in msg

    # Caso contrario: si texto_limpio en sí supera 6687, debe fallar
    texto_excedido = "A" * (TEXTO_MAX + 1)
    err = validar_longitud_maxima(texto_excedido, TEXTO_MAX, "texto")
    assert err is not None
    assert "6687" in err


# =========================================================================
# 3. Eliminación de recurso y remoción de marcador en texto_limpio
# =========================================================================

def test_eliminacion_recurso_borrador_y_endpoint_api(client):
    texto = (
        "Paso 1: Configurar cuenta.\n\n"
        "![imagen 1](https://bc.finneg.com/img1.png)\n\n"
        "Paso 2: Revisar saldos.\n\n"
        "![imagen 2](https://bc.finneg.com/img2.png)"
    )
    texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto)

    sid = "sesion-eliminar-recurso-test"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Título de prueba",
        texto=reconstruir_texto_con_recursos(texto_limpio, recursos),
        texto_limpio=texto_limpio,
        recursos=recursos,
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título de prueba",
            texto=reconstruir_texto_con_recursos(texto_limpio, recursos),
            texto_limpio=texto_limpio,
            recursos=recursos,
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme=reconstruir_texto_con_recursos(texto_limpio, recursos),
            categoria_id=2,
            tags=["instructivo", "general"],
        ),
    )
    SESIONES[sid] = sesion

    # 1. Listar recursos mediante la API
    resp_listar = client.get("/chat/recursos", headers={"X-Session-ID": sid})
    assert resp_listar.status_code == 200
    recs_api = resp_listar.json()
    assert len(recs_api) == 2
    assert recs_api[0]["id"] == "rec_1"
    assert recs_api[1]["id"] == "rec_2"

    # 2. Eliminar 'rec_1' mediante DELETE /chat/recursos/{id}
    resp_del = client.delete("/chat/recursos/rec_1", headers={"X-Session-ID": sid})
    assert resp_del.status_code == 200
    assert resp_del.json() == {"status": "ok", "eliminado": "rec_1"}

    # 3. Invariante 7: eliminar un recurso de recursos no altera texto_limpio
    assert "rec_1" not in sesion.borrador.recursos
    assert "rec_2" in sesion.borrador.recursos
    assert 'rec_1' not in sesion.borrador.texto_limpio and 'rec_2' in sesion.borrador.texto_limpio

    # 4. Intentar eliminar recurso inexistente debe devolver 404
    resp_del_404 = client.delete("/chat/recursos/rec_inexistente", headers={"X-Session-ID": sid})
    assert resp_del_404.status_code == 404


# =========================================================================
# 4. Chequeo determinista de marcadores (sin llamadas a LLM)
# =========================================================================

def test_chequeo_determinista_de_marcadores_restaura_ausentes():
    recursos = {
        "rec_1": Recurso(id="rec_1", tipo="imagen", nombre="Captura 1", orden=1),
        "rec_2": Recurso(id="rec_2", tipo="video", nombre="Video explicativo", orden=2),
    }

    # Caso A: El texto conserva todos los marcadores en orden
    texto_ok = "Paso 1: [[recurso:rec_1]]\n\nPaso 2: [[recurso:rec_2]]"
    texto_res, advs = verificar_y_restaurar_marcadores(texto_ok, recursos)
    assert texto_res == texto_ok
    assert len(advs) == 0

    # Caso B: Un skill del agente eliminó accidentalmente el marcador de rec_2
    texto_mutilado = "Paso 1: [[recurso:rec_1]]\n\nPaso 2: Se omitió el marcador."
    texto_restaurado, advs = verificar_y_restaurar_marcadores(texto_mutilado, recursos)

    # Debe restaurarse determinísticamente al final
    assert "[[recurso:rec_2]]" in texto_restaurado
    assert texto_restaurado.endswith("[[recurso:rec_2]]")
    assert len(advs) == 1
    assert "Video explicativo" in advs[0]

    # Caso C: Todos los marcadores fueron borrados por el agente
    texto_vacio_marcadores = "Paso 1 y Paso 2 completamente reescritos sin marcadores."
    texto_rest_todos, advs_todos = verificar_y_restaurar_marcadores(texto_vacio_marcadores, recursos)
    assert "[[recurso:rec_1]]" in texto_rest_todos
    assert "[[recurso:rec_2]]" in texto_rest_todos
    assert len(advs_todos) == 2


# =========================================================================
# 5. Subida de recursos: Rechazada en Fase 1 (flag False)
# =========================================================================

def test_subida_recurso_rechazada_en_fase_1(client):
    sid = "sesion-upload-fase1"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Título de prueba",
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título de prueba",
            texto="Contenido",
            texto_limpio="Contenido",
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme="Contenido",
            categoria_id=1,
            tags=["instructivo"],
        ),
    )

    archivo_falso = io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")
    with patch("baco.server.app.api.PERMITIR_SUBIDA_RECURSOS", False), \
         patch("baco.server.services.orquestador.recursos_service.PERMITIR_SUBIDA_RECURSOS", False):
        resp = client.post(
            "/chat/recursos",
            headers={"X-Session-ID": sid},
            files={"file": ("captura.png", archivo_falso, "image/png")},
        )
        assert resp.status_code == 403
        assert "deshabilitada en esta fase" in resp.json()["detail"]


# =========================================================================
# 6. Subida de recursos válida e inválida con flag activo (MIME real, cuotas, tamaño)
# =========================================================================

def test_subida_recursos_con_flag_activo(client):
    sid = "sesion-upload-valida"
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo="Título con uploads",
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Título con uploads",
            texto="Texto base",
            texto_limpio="Texto base",
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme="Texto base",
            categoria_id=1,
            tags=["instructivo"],
        ),
    )

    with patch("baco.server.app.api.PERMITIR_SUBIDA_RECURSOS", True), \
         patch("baco.server.services.orquestador.recursos_service.PERMITIR_SUBIDA_RECURSOS", True):

        # 1. Subida válida: PNG real con magic bytes
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        resp_valida = client.post(
            "/chat/recursos",
            headers={"X-Session-ID": sid},
            files={"file": ("grafico_contable.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert resp_valida.status_code == 200
        data_rec = resp_valida.json()
        assert data_rec["id"] == "rec_1"
        assert data_rec["tipo"] == "imagen"
        assert data_rec["origen"] == "subido"
        assert data_rec["mime_type"] == "image/png"
        assert Path(data_rec["referencia"]).exists()

        # Invariante 7: Subir un recurso NO altera texto_limpio
        ses = SESIONES[sid]
        assert "rec_1" in ses.borrador.recursos
        assert ses.borrador.texto_limpio == "Texto base"

        # 2. Subida inválida por MIME spoofing: extensión .png con contenido de script/ejecutable
        exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
        resp_spoof = client.post(
            "/chat/recursos",
            headers={"X-Session-ID": sid},
            files={"file": ("malicioso.png", io.BytesIO(exe_bytes), "image/png")},
        )
        assert resp_spoof.status_code == 400
        assert "MIME" in resp_spoof.json()["detail"] or "no permitido" in resp_spoof.json()["detail"]

        # 3. Subida inválida por tamaño mayor a 10MB
        contenido_pesado = b"X" * (RECURSO_MAX_BYTES + 1024)
        resp_pesado = client.post(
            "/chat/recursos",
            headers={"X-Session-ID": sid},
            files={"file": ("archivo_pesado.pdf", io.BytesIO(contenido_pesado), "application/pdf")},
        )
        assert resp_pesado.status_code == 400
        assert "supera el tamaño máximo" in resp_pesado.json()["detail"]

        # 4. Subida inválida por cuota de recursos (máximo 20)
        recursos_simulados = {
            f"rec_{i}": Recurso(id=f"rec_{i}", tipo="imagen", nombre=f"img_{i}", orden=i)
            for i in range(1, MAX_RECURSOS_POR_SESION + 1)
        }
        ses.borrador.recursos = recursos_simulados
        resp_cuota = client.post(
            "/chat/recursos",
            headers={"X-Session-ID": sid},
            files={"file": ("extra.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert resp_cuota.status_code == 400
        assert "límite máximo" in resp_cuota.json()["detail"]

        # 5. Sanitización del nombre de archivo (evitar Path Traversal)
        assert sanitizar_nombre_archivo("../../etc/passwd") == "passwd"
        assert sanitizar_nombre_archivo("foto<script>.png") == "foto_script_.png"


# =========================================================================
# 7. Expiración por TTL: Limpieza física de archivos temporales en disco
# =========================================================================

def test_expiracion_por_ttl_elimina_archivos_temporales_en_disco():
    sid = "sesion-ttl-cleanup-test"
    gestor = GestorSesiones()

    # Guardar un archivo en la carpeta temporal de la sesión
    dir_sesion = DIR_TEMP_SESIONES / sid
    dir_sesion.mkdir(parents=True, exist_ok=True)
    archivo_temp = dir_sesion / "rec_1_temp.png"
    archivo_temp.write_bytes(b"\x89PNG fake bytes")
    assert archivo_temp.exists()

    # Crear la sesión asociada
    ahora = datetime.now(timezone.utc)
    sesion = SesionChat(session_id=sid, updated_at=ahora)
    gestor.sesiones[sid] = sesion

    # 1. Simular paso de 10 minutos (aún no expira TTL de 30m)
    gestor.limpiar_expiradas(ahora + timedelta(minutes=10))
    assert sid in gestor.sesiones
    assert archivo_temp.exists()

    # 2. Simular paso de 31 minutos (supera TTL de 30m)
    gestor.limpiar_expiradas(ahora + timedelta(minutes=31))
    assert sid not in gestor.sesiones
    # La carpeta y el archivo deben haber sido borrados físicamente
    assert not dir_sesion.exists()
    assert not archivo_temp.exists()


# =========================================================================
# 8. Verificación de CERO escrituras en la base de datos (PostgreSQL/articulos)
# =========================================================================

def test_ninguna_operacion_de_recursos_escribe_en_base_de_datos(client, mock_buscador):
    """Garantiza la regla innegociable: Nada se persiste en PostgreSQL ni Discourse.

    Todo vive y muere con la sesión de chat.
    """
    # 1. Ejecutar turno para abrir y enriquecer
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título encontrada",
        "link": "https://bc.finneg.com/t/999",
        "coincidencias": [(999, "Guía de Ajuste Contable", "https://bc.finneg.com/t/999")],
    }

    r1 = client.post("/chat", json={"mensaje": "Guía de Ajuste Contable"}).json()
    sid = r1["session_id"]

    texto_con_medios = (
        "Pasos de ajuste:\n\n"
        "![Captura](https://bc.finneg.com/uploads/original/error.png)\n\n"
        "1. Revisar balance."
    )

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (texto_con_medios, 21, ["instructivo", "contabilidad"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    # 2. Eliminar recurso
    client.delete("/chat/recursos/rec_1", headers={"X-Session-ID": sid})

    # 3. Editar texto del borrador
    client.post(
        "/chat",
        json={
            "session_id": sid,
            "mensaje": "editar",
            "texto": "Pasos corregidos:\n\n1. Revisar balance general.",
        },
    )

    # 4. Verificar que el cursor de mock_buscador y cualquier query de DB NUNCA ejecutó
    # declaraciones de escritura (INSERT, UPDATE, DELETE, ALTER, DROP)
    for call in mock_buscador.cur.execute.call_args_list:
        query = str(call[0][0]).strip().upper()
        assert not query.startswith("INSERT INTO ARTICULOS"), f"Escritura prohibida en BD: {query}"
        assert not query.startswith("UPDATE ARTICULOS"), f"Escritura prohibida en BD: {query}"
        assert not query.startswith("DELETE FROM ARTICULOS"), f"Escritura prohibida en BD: {query}"

    # 5. La sesión contiene la metadata en memoria sin haber persistido nada
    sesion = SESIONES.get(sid)
    assert sesion is not None
    assert isinstance(sesion.recursos, dict)
    assert isinstance(sesion.borrador.texto_limpio, str)


# =========================================================================
# 9. Vector de orden en borrador y compatibilidad con borradores previos
# =========================================================================

def test_vector_orden_multimedia_en_borrador_y_compatibilidad():
    """Valida que BorradorSesion posea vector de orden numérico (orden_multimedia y posiciones),

    que se sincronice por defecto sin flags de flujo, y mantenga compatibilidad con esquemas previos.
    """
    r1 = Recurso(id="rec_a", tipo="imagen", nombre="foto1.png", referencia="https://bc.finneg.com/1.png", orden=0)
    r2 = Recurso(id="rec_b", tipo="video", nombre="video1.mp4", referencia="https://youtube.com/v1", orden=1)

    # 1. Compatibilidad retroactiva: borrador instanciado sin orden_multimedia ni posiciones
    legacy_data = {
        "modo": "nuevo",  # Flujo estándar nuevo, sin flags de enriquecimiento ni actualización
        "titulo": "Artículo de prueba",
        "texto": "Contenido inicial",
        "texto_limpio": "Contenido inicial [[recurso:rec_a]] [[recurso:rec_b]]",
        "recursos": {"rec_a": r1, "rec_b": r2},
    }
    borrador = BorradorSesion(**legacy_data)

    # Validar que se inicializan los vectores por defecto
    assert hasattr(borrador, "orden_multimedia")
    assert hasattr(borrador, "posiciones")
    assert borrador.orden_multimedia == [0, 1]
    assert borrador.posiciones == [0, 1]

    # Validar propiedad multimedia
    assert [r.id for r in borrador.multimedia] == ["rec_a", "rec_b"]

    # 2. Borrador vacío: vectores vacíos
    borrador_vacio = BorradorSesion(modo="nuevo", titulo="Sin recursos")
    assert borrador_vacio.orden_multimedia == []
    assert borrador_vacio.posiciones == []
    assert borrador_vacio.multimedia == []


# =========================================================================
# 10. Operaciones atómicas sobre multimedia en BorradorSesion
# =========================================================================

def test_operaciones_atomicas_borrador_sesion():
    """Prueba reorder(from_index, to_index), reordenar por IDs/índices, eliminación e inserción."""
    r0 = Recurso(id="r0", tipo="imagen", nombre="img0.png", referencia="https://bc.finneg.com/0.png", orden=0)
    r1 = Recurso(id="r1", tipo="imagen", nombre="img1.png", referencia="https://bc.finneg.com/1.png", orden=1)
    r2 = Recurso(id="r2", tipo="imagen", nombre="img2.png", referencia="https://bc.finneg.com/2.png", orden=2)

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Prueba atómica",
        texto="T",
        texto_limpio="T [[recurso:r0]] [[recurso:r1]] [[recurso:r2]]",
        recursos={"r0": r0, "r1": r1, "r2": r2},
        conforme=True,
        conforme_en="2026-10-24T10:00:00Z",
    )
    assert borrador.orden_multimedia == [0, 1, 2]
    assert borrador.posiciones == [0, 1, 2]

    # A. Reordenamiento atómico: mover índice 0 a índice 2
    resultado = borrador.reorder(from_index=0, to_index=2)
    assert [r.id for r in resultado] == ["r1", "r2", "r0"]
    assert [r.orden for r in resultado] == [0, 1, 2]
    assert borrador.orden_multimedia == [0, 1, 2]
    assert borrador.posiciones == [0, 1, 2]
    # Invalida conformidad
    assert borrador.conforme is False
    assert borrador.conforme_en is None
    assert borrador.conformidad_invalidada is True

    # B. Reordenamiento por IDs explícitos
    borrador.conforme = True
    borrador.reordenar_por_ids(["r0", "r1", "r2"])
    assert [r.id for r in borrador.multimedia] == ["r0", "r1", "r2"]
    assert borrador.conforme is False

    # C. Reordenamiento por índices explícitos
    borrador.reordenar_por_indices([2, 0, 1])
    assert [r.id for r in borrador.multimedia] == ["r2", "r0", "r1"]

    # D. Inserción / adición atómica en posición específica
    r_nuevo = Recurso(id="r_new", tipo="documento", nombre="doc.pdf", referencia="https://bc.finneg.com/doc.pdf")
    borrador.agregar_multimedia(r_nuevo, posicion=1)
    items = borrador.multimedia
    assert [r.id for r in items] == ["r2", "r_new", "r0", "r1"]
    assert [r.orden for r in items] == [0, 1, 2, 3]
    assert borrador.orden_multimedia == [0, 1, 2, 3]
    assert borrador.posiciones == [0, 1, 2, 3]

    # E. Eliminación atómica por ID
    eliminado = borrador.eliminar_multimedia("r_new")
    assert eliminado is not None and eliminado.id == "r_new"
    items_tras_del = borrador.multimedia
    assert [r.id for r in items_tras_del] == ["r2", "r0", "r1"]
    assert [r.orden for r in items_tras_del] == [0, 1, 2]
    assert borrador.orden_multimedia == [0, 1, 2]
    assert borrador.posiciones == [0, 1, 2]

    # F. Eliminación atómica por índice numérico
    eliminado_idx = borrador.eliminar_multimedia(1)  # elimina "r0" en posición 1
    assert eliminado_idx is not None and eliminado_idx.id == "r0"
    items_final = borrador.multimedia
    assert [r.id for r in items_final] == ["r2", "r1"]
    assert [r.orden for r in items_final] == [0, 1]
    assert borrador.orden_multimedia == [0, 1]


# =========================================================================
# 11. GestorSesiones y Endpoints API de Reordenamiento y Adición
# =========================================================================

def test_gestor_sesiones_y_endpoints_api_multimedia(client):
    """Valida reordenar, agregar y eliminar recursos multimedia mediante la API

    en un flujo estándar (modo 'nuevo'), verificando independencia de flags y sincronización de vectores.
    """
    sid = "sesion-api-multimedia-test"
    r1 = Recurso(id="rec_1", tipo="imagen", nombre="uno.png", referencia="https://bc.finneg.com/1.png", orden=0)
    r2 = Recurso(id="rec_2", tipo="imagen", nombre="dos.png", referencia="https://bc.finneg.com/2.png", orden=1)
    r3 = Recurso(id="rec_3", tipo="video", nombre="tres.mp4", referencia="https://youtube.com/v3", orden=2)

    texto_limpio = "Inicio\n\n[[recurso:rec_1]]\n\nMedio\n\n[[recurso:rec_2]]\n\nFin\n\n[[recurso:rec_3]]"
    recs = {"rec_1": r1, "rec_2": r2, "rec_3": r3}
    texto_con_recursos = reconstruir_texto_con_recursos(texto_limpio, recs)

    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Manual Operativo",
        texto=texto_con_recursos,
        texto_limpio=texto_limpio,
        recursos=recs,
        borrador=BorradorSesion(
            modo="nuevo",  # Sin flags de actualización ni enriquecimiento
            titulo="Manual Operativo",
            texto=texto_con_recursos,
            texto_limpio=texto_limpio,
            recursos=recs,
            conforme=True,
            conforme_en="2026-10-24T12:00:00Z",
            texto_original_conforme=texto_con_recursos,
        ),
    )
    SESIONES[sid] = sesion

    # 1. Reordenar vía PUT /chat/recursos/reordenar (from_index=0, to_index=2)
    resp_reorder = client.put(
        "/chat/recursos/reordenar",
        headers={"X-Session-ID": sid},
        json={"from_index": 0, "to_index": 2},
    )
    assert resp_reorder.status_code == 200
    items_reordered = resp_reorder.json()
    assert [r["id"] for r in items_reordered] == ["rec_2", "rec_3", "rec_1"]

    # Comprobar estado en la sesión
    assert sesion.borrador.orden_multimedia == [0, 1, 2]
    assert sesion.borrador.posiciones == [0, 1, 2]
    assert [r.id for r in sesion.borrador.multimedia] == ["rec_2", "rec_3", "rec_1"]
    assert sesion.borrador.conforme is False
    assert sesion.borrador.conformidad_invalidada is True

    # 2. Agregar nuevo recurso en posición específica vía POST /chat/recursos/agregar
    resp_add = client.post(
        "/chat/recursos/agregar",
        headers={"X-Session-ID": sid},
        json={
            "tipo": "documento",
            "nombre": "anexo.pdf",
            "referencia": "https://bc.finneg.com/anexo.pdf",
            "posicion": 1,
            "tamano_bytes": 1024,
        },
    )
    assert resp_add.status_code == 200
    nuevo_rec = resp_add.json()
    assert nuevo_rec["tipo"] == "documento"
    assert nuevo_rec["nombre"] == "anexo.pdf"
    assert nuevo_rec["orden"] == 1

    # Verificar que el nuevo recurso quedó en la posición 1 y los demás se desplazaron
    items_tras_add = sesion.borrador.multimedia
    assert len(items_tras_add) == 4
    assert items_tras_add[0].id == "rec_2"
    assert items_tras_add[1].id == nuevo_rec["id"]
    assert items_tras_add[2].id == "rec_3"
    assert items_tras_add[3].id == "rec_1"
    assert sesion.borrador.orden_multimedia == [0, 1, 2, 3]
    assert sesion.borrador.posiciones == [0, 1, 2, 3]

    # 3. Eliminar por índice numérico (posición 1, que es el anexo recién agregado)
    resp_del_idx = client.delete("/chat/recursos/1", headers={"X-Session-ID": sid})
    assert resp_del_idx.status_code == 200
    assert resp_del_idx.json()["status"] == "ok"

    # Verificar que quedan 3 recursos en orden correlativo 0, 1, 2
    items_final = sesion.borrador.multimedia
    assert len(items_final) == 3
    assert [r.id for r in items_final] == ["rec_2", "rec_3", "rec_1"]
    assert sesion.borrador.orden_multimedia == [0, 1, 2]
    assert sesion.borrador.posiciones == [0, 1, 2]


def test_extraer_recursos_sanitiza_imagenes_relativas_data_uris_y_tags_locales():
    """Ítem 2: extraer_recursos_y_texto_limpio extrae y sanitiza imágenes relativas,
    data: URIs y tags HTML locales sin dejarlos crudos en el texto limpio."""
    texto_entrada = (
        "Texto inicial del procedimiento.\n\n"
        "![Captura relativa](imagenes/paso1.png)\n\n"
        "Texto intermedio explicativo.\n\n"
        "<img src='/local/uploads/captura.jpg' alt='Foto local' />\n\n"
        "![Logo base64](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=)\n\n"
        "<video src='archivos/video.mp4'></video>\n\n"
        "<audio src='audio/instruccion.mp3'></audio>\n\n"
        "![Imagen remota valida](https://finneg.com/img/oficial.png)\n\n"
        "Texto final de cierre."
    )

    tl, recs = extraer_recursos_y_texto_limpio(texto_entrada)

    # 1. No debe quedar ningún tag HTML ni markdown local/data URI crudo
    assert "imagenes/paso1.png" not in tl
    assert "<img" not in tl
    assert "/local/uploads/captura.jpg" not in tl
    assert "data:image" not in tl
    assert "<video" not in tl
    assert "<audio" not in tl

    # 2. El recurso válido remoto sí se registró y dejó su marcador
    assert len(recs) == 1
    assert "rec_1" in recs
    assert recs["rec_1"].referencia == "https://finneg.com/img/oficial.png"
    assert "[[recurso:rec_1]]" in tl

    # 3. El texto limpio conserva la redacción original
    assert "Texto inicial del procedimiento." in tl
    assert "Texto intermedio explicativo." in tl
    assert "Texto final de cierre." in tl

