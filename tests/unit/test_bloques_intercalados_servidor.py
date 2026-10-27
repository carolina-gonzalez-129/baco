import hashlib
import random
import re
import unicodedata
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.config_limites import (
    MAX_BLOQUES_TEXTO,
    MAX_RECURSOS_POR_SESION,
    TEXTO_MAX,
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
)
from baco.server.schemas.chat_orquestado import BorradorSesion, EstadoFlujo
from baco.server.schemas.recurso import BloqueItem, ConfirmarBloquesRequest, Recurso
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.embeddings import limpiar_suave, truncar_1000
from baco.server.services.orquestador.recursos_service import (
    extraer_recursos_y_bloques_texto,
)
from baco.server.services.orquestador.sesion import SESIONES, SesionChat, gestor_sesiones


@pytest.fixture(autouse=True)
def limpiar_sesiones_fixture():
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


def _normalizar_texto_sql_equivalente(texto: str) -> str:
    """Equivalente exacto de public.normalizar_texto(texto) en PostgreSQL."""
    s = (texto or "").lower()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# =========================================================================
# 1. Fuente de verdad única y autosanitización sobre bloques_texto
# =========================================================================

def test_req1_fuente_verdad_unica_y_autosanitizacion_dni_token_en_bloques():
    """Verifica que bloques_texto es la fuente de verdad persistida, texto_limpio es derivado
    (computed_field) y la autosanitización de DNI/token sobre bloques_texto impide que
    aparezcan en texto_limpio y en texto_alineado_discourse.
    """
    assert "bloques_texto" in BorradorSesion.model_fields
    assert "texto_limpio" not in BorradorSesion.model_fields
    assert "texto_limpio" in BorradorSesion.model_computed_fields
    assert "texto_alineado_discourse" in BorradorSesion.model_computed_fields

    dni_sensible = "34.567.890"
    token_sensible = "sk-live-9876543210abcdef1234567890"
    jwt_sensible = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Instructivo de configuración de credenciales",
        bloques_texto=[
            f"Paso 1: Validar identidad del operador con DNI {dni_sensible} en el padrón.",
            f"Paso 2: Configurar Authorization: Bearer {token_sensible} y token={jwt_sensible} en el cliente.",
        ],
        recursos={
            "rec_1": Recurso(
                id="rec_1",
                tipo="imagen",
                nombre="Pantalla de configuración",
                referencia="https://bc.finneg.com/uploads/config.png",
                posicion=0,
                orden=0,
            )
        },
    )

    # Ningún dato sensible permanece en bloques_texto, texto_limpio ni texto_alineado_discourse
    for b in borrador.bloques_texto:
        assert dni_sensible not in b
        assert token_sensible not in b
        assert jwt_sensible not in b

    assert dni_sensible not in borrador.texto_limpio
    assert token_sensible not in borrador.texto_limpio
    assert jwt_sensible not in borrador.texto_limpio

    assert dni_sensible not in borrador.texto_alineado_discourse
    assert token_sensible not in borrador.texto_alineado_discourse
    assert jwt_sensible not in borrador.texto_alineado_discourse
    assert "[DOCUMENTO_OCULTO]" in borrador.texto_alineado_discourse
    assert "[TOKEN_OCULTO]" in borrador.texto_alineado_discourse
    assert "![Pantalla de configuración](https://bc.finneg.com/uploads/config.png)" in borrador.texto_alineado_discourse


# =========================================================================
# 2. Borrado de recurso y fusión condicional de bloques_texto
# =========================================================================

def test_req2_borrado_recurso_fusion_condicional_de_bloques():
    """Verifica la regla de fusión al borrar un recurso:
    - Fusiona bloques_texto[i] y bloques_texto[i+1] SOLO si ningún otro recurso queda con posicion == i.
    - Si otro recurso queda en posicion == i, NO fusiona.
    - Si posicion == -1 (o al final del último bloque), NO fusiona.
    """
    # Caso A y B: dos recursos en posicion=0 (entre bloque 0 y bloque 1) y uno en posicion=1 (entre bloque 1 y bloque 2)
    r_prev = Recurso(id="rec_0", tipo="imagen", nombre="Portada", referencia="https://bc.finneg.com/0.png", posicion=-1, orden=0)
    r_a = Recurso(id="rec_1", tipo="imagen", nombre="Img A", referencia="https://bc.finneg.com/a.png", posicion=0, orden=1)
    r_b = Recurso(id="rec_2", tipo="imagen", nombre="Img B", referencia="https://bc.finneg.com/b.png", posicion=0, orden=2)
    r_c = Recurso(id="rec_3", tipo="imagen", nombre="Img C", referencia="https://bc.finneg.com/c.png", posicion=1, orden=3)

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Prueba de fusión condicional de bloques",
        bloques_texto=["Bloque 0 inicio.", "Bloque 1 medio.", "Bloque 2 final."],
        recursos={"rec_0": r_prev, "rec_1": r_a, "rec_2": r_b, "rec_3": r_c},
    )

    # 1. Borrar recurso en posicion == -1 -> NO fusiona bloques
    borrador.eliminar_multimedia("rec_0")
    assert borrador.bloques_texto == ["Bloque 0 inicio.", "Bloque 1 medio.", "Bloque 2 final."]
    assert borrador.recursos["rec_1"].posicion == 0
    assert borrador.recursos["rec_2"].posicion == 0
    assert borrador.recursos["rec_3"].posicion == 1

    # 2. Borrar rec_1 en posicion == 0 mientras rec_2 sigue en posicion == 0 -> NO fusiona bloques
    borrador.eliminar_multimedia("rec_1")
    assert borrador.bloques_texto == ["Bloque 0 inicio.", "Bloque 1 medio.", "Bloque 2 final."]
    assert borrador.recursos["rec_2"].posicion == 0
    assert borrador.recursos["rec_3"].posicion == 1

    # 3. Borrar rec_2 (último recurso en posicion == 0) -> SÍ fusiona bloques_texto[0] y bloques_texto[1]
    # y decrementa la posicion de rec_3 de 1 a 0
    borrador.eliminar_multimedia("rec_2")
    assert len(borrador.bloques_texto) == 2
    assert borrador.bloques_texto[0] == "Bloque 0 inicio.\n\nBloque 1 medio."
    assert borrador.bloques_texto[1] == "Bloque 2 final."
    assert borrador.recursos["rec_3"].posicion == 0
    assert borrador.recursos["rec_3"].orden == 0

    # 4. Borrar rec_3 (ahora único en posicion == 0) -> fusiona los dos bloques restantes en uno solo
    borrador.eliminar_multimedia("rec_3")
    assert borrador.bloques_texto == ["Bloque 0 inicio.\n\nBloque 1 medio.\n\nBloque 2 final."]
    assert borrador.recursos == {}


# =========================================================================
# 3. PUT /chat/recursos/reordenar e invariantes con secuencias aleatorias
# =========================================================================

def _verificar_invariantes_borrador(borrador: BorradorSesion) -> None:
    items = borrador.multimedia
    n = len(items)
    max_pos = len(borrador.bloques_texto) - 1
    # 1. posicion en [-1, len(bloques_texto) - 1]
    for r in items:
        assert -1 <= r.posicion <= max_pos, f"posicion fuera de rango: {r.posicion} (max_pos={max_pos})"
    # 2. orden único y contiguo 0..N-1
    assert [r.orden for r in items] == list(range(n)), f"orden no contiguo: {[r.orden for r in items]}"
    assert borrador.orden_multimedia == list(range(n))
    # 3. recursos ordenados por (posicion, orden)
    pares = [(r.posicion, r.orden) for r in items]
    assert pares == sorted(pares), f"recursos no ordenados por (posicion, orden): {pares}"


def test_req3_endpoint_reordenar_semantica_posicion_y_orden(client):
    """Verifica PUT /chat/recursos/reordenar moviendo un recurso por id o índice a un nuevo (posicion, orden)."""
    sid = "sesion-reordenar-semantica"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Guía de reordenamiento",
        bloques_texto=["Bloque 0", "Bloque 1", "Bloque 2"],
        recursos={
            "rec_1": Recurso(id="rec_1", tipo="imagen", nombre="1.png", referencia="https://bc.finneg.com/1.png", posicion=0, orden=0),
            "rec_2": Recurso(id="rec_2", tipo="imagen", nombre="2.png", referencia="https://bc.finneg.com/2.png", posicion=1, orden=1),
            "rec_3": Recurso(id="rec_3", tipo="imagen", nombre="3.png", referencia="https://bc.finneg.com/3.png", posicion=2, orden=2),
        },
    )
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Guía de reordenamiento",
        bloques_texto=list(borrador.bloques_texto),
        recursos=dict(borrador.recursos),
        borrador=borrador,
    )

    # Mover rec_3 a posicion=-1 (antes del primer bloque), orden=0
    resp = client.put(
        "/chat/recursos/reordenar",
        headers={"X-Session-ID": sid},
        json={"id": "rec_3", "posicion": -1, "orden": 0},
    )
    assert resp.status_code == 200
    estado = resp.json()
    datos = estado["recursos"]
    assert [r["id"] for r in datos] == ["rec_3", "rec_1", "rec_2"]
    assert [r["posicion"] for r in datos] == [-1, 0, 1]
    assert [r["orden"] for r in datos] == [0, 1, 2]
    _verificar_invariantes_borrador(SESIONES[sid].borrador)


def test_req3_propiedades_secuencias_aleatorias_agregar_borrar_reordenar():
    """Test de propiedades con secuencias aleatorias de agregar, eliminar y reordenar recursos."""
    rng = random.Random(20261026)

    for seed_iter in range(60):
        num_bloques = rng.randint(1, 8)
        borrador = BorradorSesion(
            modo="nuevo",
            titulo=f"Prueba aleatoria {seed_iter}",
            bloques_texto=[f"Contenido del bloque {i}." for i in range(num_bloques)],
        )
        _verificar_invariantes_borrador(borrador)

        contador = 0
        for _ in range(30):
            op = rng.choice(["agregar", "eliminar", "reordenar_pos_ord", "reorder_idx"])
            n_actual = len(borrador.recursos)

            if op == "agregar" or n_actual == 0:
                if n_actual >= MAX_RECURSOS_POR_SESION:
                    continue
                contador += 1
                rid = f"rec_{contador}"
                pos_random = rng.randint(-3, len(borrador.bloques_texto) + 2)
                ord_random = rng.choice([None, rng.randint(-1, n_actual + 2)])
                rec = Recurso(
                    id=rid,
                    tipo="imagen",
                    nombre=f"img_{contador}.png",
                    referencia=f"https://bc.finneg.com/{contador}.png",
                    posicion=pos_random,
                    orden=0,
                )
                borrador.agregar_multimedia(rec, posicion=pos_random, orden=ord_random)
            elif op == "eliminar":
                victima = rng.choice( [r.id for r in borrador.multimedia] + [rng.randint(0, n_actual - 1)] )
                borrador.eliminar_multimedia(victima)
            elif op == "reordenar_pos_ord":
                elem = rng.choice([r.id for r in borrador.multimedia] + [rng.randint(0, n_actual - 1)])
                nueva_pos = rng.choice([None, rng.randint(-2, len(borrador.bloques_texto) + 2)])
                nuevo_ord = rng.choice([None, rng.randint(-1, n_actual + 2)])
                borrador.reordenar_recurso(elem, nueva_posicion=nueva_pos, nuevo_orden=nuevo_ord)
            elif op == "reorder_idx":
                f_idx = rng.randint(0, n_actual - 1)
                t_idx = rng.randint(0, n_actual - 1)
                nueva_pos = rng.choice([None, rng.randint(-1, len(borrador.bloques_texto) - 1)])
                borrador.reorder(f_idx, t_idx, nueva_posicion=nueva_pos)

            _verificar_invariantes_borrador(borrador)


# =========================================================================
# 4. Paridad con el detector (normalizar_texto, hash_texto y embeddings)
# =========================================================================

def test_req4_paridad_con_detector_imagen_en_medio_de_parrafo_hash_y_embeddings():
    """Verifica que texto_limpio construido desde bloques coincide tras normalizar con el
    texto original sin las imágenes (incluyendo una imagen en medio de un párrafo),
    y que hash_texto y el texto para embeddings no cambian.
    """
    mitad_1 = (
        "Para configurar la retención de ganancias en el módulo impositivo es necesario abrir "
        "la solapa de parámetros fiscales"
    )
    mitad_2 = (
        "y seleccionar el régimen vigente según la resolución de AFIP antes de grabar el comprobante."
    )
    parrafo_2 = (
        "En el segundo paso se debe verificar la alícuota aplicable al proveedor y asociar la cuenta "
        "contable de pasivo correspondiente para que el asiento automático se genere sin diferencias."
    )

    # Texto original sin imágenes (el párrafo 1 es continuo)
    texto_original_sin_imagenes = f"{mitad_1} {mitad_2}\n\n{parrafo_2}"

    # Texto con una imagen intercalada en medio del primer párrafo (que parte el bloque en dos) y otra al final
    texto_con_imagenes_intercaladas = (
        f"{mitad_1}\n\n"
        "![Captura solapa fiscal](https://bc.finneg.com/uploads/solapa_fiscal.png)\n\n"
        f"{mitad_2}\n\n"
        f"{parrafo_2}\n\n"
        "![Captura alícuota](https://bc.finneg.com/uploads/alicuota.png)"
    )

    bloques, recursos = extraer_recursos_y_bloques_texto(texto_con_imagenes_intercaladas)
    assert len(bloques) == 2
    assert len(recursos) == 2

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Configuración de Retención de Ganancias",
        bloques_texto=[mitad_1, mitad_2, parrafo_2],
        recursos=recursos,
    )

    # 1. Paridad en normalizar_texto y hash_texto = md5(normalizar_texto(texto))
    norm_original = _normalizar_texto_sql_equivalente(texto_original_sin_imagenes)
    norm_bloques = _normalizar_texto_sql_equivalente(borrador.texto_limpio)
    assert norm_bloques == norm_original

    hash_original = hashlib.md5(norm_original.encode("utf-8")).hexdigest()
    hash_bloques = hashlib.md5(norm_bloques.encode("utf-8")).hexdigest()
    assert hash_bloques == hash_original

    # 2. Paridad en el texto preparado para embeddings (limpiar_suave + truncar_1000)
    emb_txt_original = truncar_1000(limpiar_suave(texto_original_sin_imagenes))
    emb_txt_bloques = truncar_1000(limpiar_suave(borrador.texto_limpio))
    assert emb_txt_bloques == emb_txt_original


# =========================================================================
# 5. Sin alias `texto` en BorradorSesion (solo `texto_alineado_discourse`)
# =========================================================================

def test_req5_sin_alias_texto_en_borrador_solo_texto_alineado_discourse():
    """Verifica que BorradorSesion no expone el atributo ni campo serializado `texto`."""
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Título de prueba sin alias texto",
        bloques_texto=["Contenido único del bloque."],
    )
    assert not hasattr(borrador, "texto")
    dumped = borrador.model_dump()
    assert "texto" not in dumped
    assert "texto_alineado_discourse" in dumped
    assert dumped["texto_alineado_discourse"] == "Contenido único del bloque."


# =========================================================================
# 6. Adiciones por chat al último bloque y reemplazo por skill
# =========================================================================

def test_req6_adiciones_por_chat_al_ultimo_bloque_y_skill_reemplaza_con_bloque_unico(client, mock_buscador):
    """Verifica que:
    - Las adiciones breves por chat con bloques existentes se agregan al final del último bloque de texto.
    - Cuando una skill devuelve texto, bloques_texto = [resultado].
    """
    texto_api = (
        "Primer bloque del artículo existente en la base de conocimientos oficial.\n\n"
        "![Captura Base](https://bc.finneg.com/uploads/base.png)\n\n"
        "Segundo bloque del artículo con instrucciones detalladas de cierre contable."
    )
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia exacta",
        "link": "https://bc.finneg.com/t/801",
        "coincidencias": [(801, "Cierre Contable de Ejercicio", "https://bc.finneg.com/t/801")],
    }

    r1 = client.post("/chat", json={"mensaje": "Cierre Contable de Ejercicio"}).json()
    sid = r1["session_id"]

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = (texto_api, 21, ["instructivo", "contabilidad"])
        r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()

    assert len(r2["borrador"]["bloques_texto"]) == 2
    assert r2["borrador"]["multimedia"][0]["posicion"] == 0

    # Adición breve por chat -> se agrega al final del último bloque de texto
    aporte = "Nota 2026: verificar cotización de cierre."
    r3 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": aporte}).json()
    assert r3["estado"] == EstadoFlujo.REVISION_BORRADOR
    bloques_tras_aporte = r3["borrador"]["bloques_texto"]
    assert len(bloques_tras_aporte) == 2
    assert bloques_tras_aporte[0] == "Primer bloque del artículo existente en la base de conocimientos oficial."
    assert bloques_tras_aporte[1].endswith(aporte)
    assert r3["borrador"]["multimedia"][0]["posicion"] == 0

    # Cuando una skill devuelve texto (sobre un borrador sin recursos), bloques_texto = [resultado]
    gestor_sesiones.eliminar_recurso_multimedia(sid, "rec_1")
    resultado_skill = "## Objetivo\nDocumentar el cierre.\n\n## Pasos\n1. Ejecutar asiento de refundición."
    gestor_sesiones.actualizar_borrador_texto(sid, resultado_skill)
    assert SESIONES[sid].borrador.bloques_texto == [resultado_skill]


# =========================================================================
# 7. Cotas sobre texto_limpio unido y máximo de bloques = máx. recursos + 1
# =========================================================================

def test_req7_cotas_y_maximo_de_bloques():
    """Verifica que MAX_BLOQUES_TEXTO = MAX_RECURSOS_POR_SESION + 1 (21) se valida en BorradorSesion y ConfirmarBloquesRequest."""
    assert MAX_BLOQUES_TEXTO == MAX_RECURSOS_POR_SESION + 1

    # Exactamente MAX_BLOQUES_TEXTO es válido
    b_ok = BorradorSesion(
        modo="nuevo",
        titulo="Prueba tope de bloques",
        bloques_texto=[f"Bloque {i}" for i in range(MAX_BLOQUES_TEXTO)],
    )
    assert len(b_ok.bloques_texto) == MAX_BLOQUES_TEXTO

    # MAX_BLOQUES_TEXTO + 1 falla con ValidationError
    with pytest.raises(ValidationError, match="bloques de texto"):
        BorradorSesion(
            modo="nuevo",
            titulo="Prueba exceso de bloques",
            bloques_texto=[f"Bloque {i}" for i in range(MAX_BLOQUES_TEXTO + 1)],
        )

    with pytest.raises(ValidationError, match="bloques de texto"):
        ConfirmarBloquesRequest(
            bloques=[BloqueItem(tipo="texto", contenido=f"Bloque {i}") for i in range(MAX_BLOQUES_TEXTO + 1)]
        )


# =========================================================================
# 8. skills_habilitadas y HTTP 422 con recursos cargados
# =========================================================================

def test_req8_skills_habilitadas_y_422_con_recursos_cargados(client):
    """Verifica que skills_habilitadas es False con recursos cargados y los endpoints de skills devuelven 422."""
    sid = "sesion-skills-422-recursos"
    texto_valido = "Paso 1: Configurar el módulo de tesorería.\n\nPaso 2: Emitir orden de pago electrónica."
    r1 = Recurso(id="rec_1", tipo="imagen", nombre="op.png", referencia="https://bc.finneg.com/op.png", posicion=0, orden=0)
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Emisión de Orden de Pago Electrónica",
        bloques_texto=["Paso 1: Configurar el módulo de tesorería.", "Paso 2: Emitir orden de pago electrónica."],
        recursos={"rec_1": r1},
        conforme=True,
        conforme_en="2026-10-26T12:00:00Z",
        texto_original_conforme=f"Paso 1: Configurar el módulo de tesorería.\n\n![op.png](https://bc.finneg.com/op.png)\n\nPaso 2: Emitir orden de pago electrónica.",
        tipo_plantilla="instructivo",
        categoria_id=22,
        tags=["instructivo", "tesoreria"],
    )
    assert borrador.skills_habilitadas is False
    assert borrador.skills_motivo is not None

    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.CONFORMIDAD_USUARIO,
        titulo=borrador.titulo,
        bloques_texto=list(borrador.bloques_texto),
        recursos=dict(borrador.recursos),
        borrador=borrador,
    )

    mock_agente = MagicMock()
    app.dependency_overrides[get_baco_agent] = lambda: mock_agente
    try:
        resp_p = client.post("/chat/aplicar-plantilla", headers={"X-Session-ID": sid})
        resp_a = client.post("/chat/auditar-semantica", headers={"X-Session-ID": sid})
    finally:
        app.dependency_overrides.pop(get_baco_agent, None)

    assert resp_p.status_code == 422
    assert resp_a.status_code == 422
    mock_agente.assert_not_called()


# =========================================================================
# 9. Contratos unificados, partición atómica, sanitización PII y rutas internas
# =========================================================================

import io
import json
from baco.server.schemas.recurso import RecursoBloqueInput, sanitizar_url_recurso
from baco.server.services.orquestador.recursos_service import (
    DIR_TEMP_SESIONES,
    derivar_desde_bloques,
    limpiar_archivos_temporales_sesion,
    obtener_ruta_fisica_recurso,
)

PNG_VALIDO = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
CAMPOS_ESTADO_RECURSOS = {
    "bloques_texto",
    "recursos",
    "texto_limpio",
    "multimedia_habilitada",
    "skills_habilitadas",
    "skills_motivo",
}


def test_contrato_a_respuesta_unificada_en_endpoints_recursos(client):
    """(a) GET /chat/recursos, POST /chat/recursos, POST /chat/recursos/agregar,
    PUT /chat/recursos/reordenar y DELETE /chat/recursos/{id} devuelven el esquema unificado.
    """
    sid = "sesion-estado-unificado"
    texto_b0 = "Primer párrafo del procedimiento contable con suficiente longitud para superar validaciones."
    texto_b1 = "Segundo párrafo del procedimiento contable con detalles del asiento de apertura."
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Procedimiento de Apertura Contable",
        bloques_texto=[texto_b0, texto_b1],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Procedimiento de Apertura Contable",
            bloques_texto=[texto_b0, texto_b1],
        ),
    )
    h = {"X-Session-ID": sid}

    try:
        # 1. GET /chat/recursos sin recursos
        r_get = client.get("/chat/recursos", headers=h)
        assert r_get.status_code == 200
        d_get = r_get.json()
        assert set(d_get.keys()) == CAMPOS_ESTADO_RECURSOS
        assert d_get["bloques_texto"] == [texto_b0, texto_b1]
        assert d_get["recursos"] == []
        assert d_get["multimedia_habilitada"] is True
        assert d_get["skills_habilitadas"] is True
        assert d_get["skills_motivo"] is None

        # 2. POST /chat/recursos (subida de imagen en posicion=0, entre bloque 0 y bloque 1)
        r_post = client.post(
            "/chat/recursos",
            headers=h,
            files={"file": ("captura_1.png", io.BytesIO(PNG_VALIDO), "image/png")},
            data={"posicion": "0"},
        )
        assert r_post.status_code == 200
        d_post = r_post.json()
        assert set(d_post.keys()) == CAMPOS_ESTADO_RECURSOS
        assert len(d_post["recursos"]) == 1
        assert d_post["recursos"][0]["posicion"] == 0
        assert d_post["recursos"][0]["orden"] == 0
        assert d_post["skills_habilitadas"] is False
        assert d_post["skills_motivo"] is not None
        id_subido = d_post["recursos"][0]["id"]

        # 3. POST /chat/recursos/agregar (URL en posicion=1)
        r_add = client.post(
            "/chat/recursos/agregar",
            headers=h,
            json={"referencia": "https://bc.finneg.com/uploads/captura_2.png", "posicion": 1},
        )
        assert r_add.status_code == 200
        d_add = r_add.json()
        assert set(d_add.keys()) == CAMPOS_ESTADO_RECURSOS
        assert len(d_add["recursos"]) == 2
        id_url = d_add["recursos"][1]["id"]

        # 4. PUT /chat/recursos/reordenar (mover id_url a posicion=-1, orden=0)
        r_put = client.put(
            "/chat/recursos/reordenar",
            headers=h,
            json={"id": id_url, "posicion": -1, "orden": 0},
        )
        assert r_put.status_code == 200
        d_put = r_put.json()
        assert set(d_put.keys()) == CAMPOS_ESTADO_RECURSOS
        assert [x["id"] for x in d_put["recursos"]] == [id_url, id_subido]
        assert [x["posicion"] for x in d_put["recursos"]] == [-1, 0]
        assert [x["orden"] for x in d_put["recursos"]] == [0, 1]

        # 5. DELETE /chat/recursos/{id_subido} -> fusiona bloques_texto[0] y bloques_texto[1] y devuelve estado
        r_del = client.delete(f"/chat/recursos/{id_subido}", headers=h)
        assert r_del.status_code == 200
        d_del = r_del.json()
        assert set(d_del.keys()) == CAMPOS_ESTADO_RECURSOS
        assert len(d_del["bloques_texto"]) == 1
        assert d_del["bloques_texto"][0] == f"{texto_b0}\n\n{texto_b1}"
        assert [x["id"] for x in d_del["recursos"]] == [id_url]

        # 6. DELETE del último recurso reactiva skills_habilitadas
        r_del_2 = client.delete(f"/chat/recursos/{id_url}", headers=h)
        assert r_del_2.status_code == 200
        d_del_2 = r_del_2.json()
        assert d_del_2["recursos"] == []
        assert d_del_2["skills_habilitadas"] is True
        assert d_del_2["skills_motivo"] is None
    finally:
        limpiar_archivos_temporales_sesion(sid)


def test_contrato_b_particion_atomica_y_rollback_en_post_recursos(client):
    """(b) POST /chat/recursos acepta bloques_texto partidos por el cursor + posicion de forma atómica,
    y hace rollback completo (ni texto ni recurso ni archivo temporal) si algo falla.
    """
    sid = "sesion-particion-atomica"
    bloque_inicial = (
        "En este instructivo explicamos cómo parametrizar la cuenta bancaria en el módulo de tesorería. "
        "Luego de guardar el formulario se debe verificar el saldo inicial."
    )
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Parametrización de Cuenta Bancaria",
        bloques_texto=[bloque_inicial],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Parametrización de Cuenta Bancaria",
            bloques_texto=[bloque_inicial],
        ),
    )
    h = {"X-Session-ID": sid}

    mitad_1 = "En este instructivo explicamos cómo parametrizar la cuenta bancaria en el módulo de tesorería."
    mitad_2 = "Luego de guardar el formulario se debe verificar el saldo inicial y texto no confirmado aún."

    try:
        # 1. Caso exitoso: envía bloques_texto partidos + posicion=0
        r_ok = client.post(
            "/chat/recursos",
            headers=h,
            files={"file": ("intercalada.png", io.BytesIO(PNG_VALIDO), "image/png")},
            data={
                "posicion": "0",
                "bloques_texto": json.dumps([mitad_1, mitad_2]),
            },
        )
        assert r_ok.status_code == 200, r_ok.text
        estado_ok = r_ok.json()
        assert estado_ok["bloques_texto"] == [mitad_1, mitad_2]
        assert len(estado_ok["recursos"]) == 1
        assert estado_ok["recursos"][0]["posicion"] == 0

        # 2. Fallo por archivo inválido (ejecutable disfrazado de PNG): rollback del texto partido
        mitad_2_parte_a = "Luego de guardar el formulario"
        mitad_2_parte_b = "se debe verificar el saldo inicial."
        exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
        r_fail_file = client.post(
            "/chat/recursos",
            headers=h,
            files={"file": ("falso.png", io.BytesIO(exe_bytes), "image/png")},
            data={
                "posicion": "1",
                "bloques_texto": json.dumps([mitad_1, mitad_2_parte_a, mitad_2_parte_b]),
            },
        )
        assert r_fail_file.status_code == 400
        # El estado en sesión NO cambió
        assert SESIONES[sid].borrador.bloques_texto == [mitad_1, mitad_2]
        assert len(SESIONES[sid].borrador.recursos) == 1

        # 3. Fallo por posicion fuera de rango (posicion=5 cuando hay 3 bloques): rollback del texto y archivo
        r_fail_pos = client.post(
            "/chat/recursos",
            headers=h,
            files={"file": ("valida_pero_pos_invalida.png", io.BytesIO(PNG_VALIDO), "image/png")},
            data={
                "posicion": "5",
                "bloques_texto": json.dumps([mitad_1, mitad_2_parte_a, mitad_2_parte_b]),
            },
        )
        assert r_fail_pos.status_code in (400, 422)
        assert SESIONES[sid].borrador.bloques_texto == [mitad_1, mitad_2]
        assert len(SESIONES[sid].borrador.recursos) == 1

        # 4. Fallo por texto unido demasiado corto (< TEXTO_MIN): rollback completo
        r_fail_cota = client.post(
            "/chat/recursos",
            headers=h,
            files={"file": ("valida.png", io.BytesIO(PNG_VALIDO), "image/png")},
            data={
                "posicion": "0",
                "bloques_texto": json.dumps(["Corto", "Texto"]),
            },
        )
        assert r_fail_cota.status_code in (400, 422)
        assert SESIONES[sid].borrador.bloques_texto == [mitad_1, mitad_2]
        assert len(SESIONES[sid].borrador.recursos) == 1
    finally:
        limpiar_archivos_temporales_sesion(sid)


def test_contrato_c_sanitizacion_pii_en_bloques_partidos_al_subir(client):
    """(c) Texto con PII/secretos en los bloques partidos enviados a POST /chat/recursos
    se sanitiza antes de guardarse en bloques_texto, texto_limpio y texto_alineado_discourse.
    """
    sid = "sesion-pii-particion"
    texto_inicial = (
        "Procedimiento inicial para dar de alta un operador en el sistema de gestión comercial Finnegans."
    )
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Alta de Operador en Sistema",
        bloques_texto=[texto_inicial],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Alta de Operador en Sistema",
            bloques_texto=[texto_inicial],
        ),
    )
    h = {"X-Session-ID": sid}

    dni_crudo = "30.123.456"
    token_crudo = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    b0_con_pii = f"Paso 1: Ingresar el documento del operador DNI {dni_crudo} en la ficha de alta."
    b1_con_secret = f"Paso 2: Configurar la credencial api_key={token_crudo} en el conector externo."

    try:
        r = client.post(
            "/chat/recursos",
            headers=h,
            files={"file": ("paso_intermedio.png", io.BytesIO(PNG_VALIDO), "image/png")},
            data={
                "posicion": "0",
                "bloques_texto": json.dumps([b0_con_pii, b1_con_secret]),
            },
        )
        assert r.status_code == 200, r.text
        estado = r.json()

        for b in estado["bloques_texto"]:
            assert dni_crudo not in b
            assert token_crudo not in b
        assert dni_crudo not in estado["texto_limpio"]
        assert token_crudo not in estado["texto_limpio"]

        borrador = SESIONES[sid].borrador
        assert dni_crudo not in borrador.texto_alineado_discourse
        assert token_crudo not in borrador.texto_alineado_discourse
        assert "[DOCUMENTO_OCULTO]" in borrador.texto_alineado_discourse
        assert "[TOKEN_OCULTO]" in borrador.texto_alineado_discourse
    finally:
        limpiar_archivos_temporales_sesion(sid)


def test_req_a_ninguna_respuesta_ni_storage_json_contiene_rutas_absolutas(client):
    """(a) Ninguna respuesta de la API ni el JSON de storage (model_dump_json)
    contiene rutas absolutas en disco ni backslashes de Windows.
    """
    sid = "sesion-sin-rutas-absolutas"
    texto_b0 = "Párrafo inicial del procedimiento de validación y control administrativo."
    texto_b1 = "Párrafo de cierre con instrucciones detalladas para el archivo de constancias."
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Control Administrativo",
        bloques_texto=[texto_b0, texto_b1],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Control Administrativo",
            bloques_texto=[texto_b0, texto_b1],
        ),
    )
    h = {"X-Session-ID": sid}

    try:
        # 1. Subida vía POST /chat/recursos
        r_post = client.post(
            "/chat/recursos",
            headers=h,
            files={"file": ("evidencia.png", io.BytesIO(PNG_VALIDO), "image/png")},
            data={"posicion": "0"},
        )
        assert r_post.status_code == 200
        post_json_str = r_post.text

        # Ninguna ruta absoluta (C:\ o disco base) ni backslashes en la respuesta
        assert ":\\" not in post_json_str
        assert ":\\\\" not in post_json_str
        assert str(DIR_TEMP_SESIONES) not in post_json_str
        id_rec = r_post.json()["recursos"][0]["id"]
        ref_rec = r_post.json()["recursos"][0]["referencia"]
        assert ref_rec.startswith(f"/api/recursos-temp/{sid}/")

        # 2. GET /chat/recursos
        r_get = client.get("/chat/recursos", headers=h)
        assert r_get.status_code == 200
        assert ":\\" not in r_get.text
        assert str(DIR_TEMP_SESIONES) not in r_get.text

        # 3. POST /chat/bloques identificando el recurso subido por id
        r_bloques = client.post(
            "/chat/bloques",
            headers=h,
            json={
                "bloques": [
                    {"tipo": "texto", "contenido": texto_b0},
                    {"tipo": "recurso", "recurso": {"id": id_rec}},
                    {"tipo": "texto", "contenido": texto_b1},
                ]
            },
        )
        assert r_bloques.status_code == 200
        assert ":\\" not in r_bloques.text
        assert str(DIR_TEMP_SESIONES) not in r_bloques.text

        # 4. JSON de storage (borrador.model_dump_json() y recurso.model_dump_json())
        sesion = SESIONES[sid]
        json_borrador = sesion.borrador.model_dump_json()
        json_recurso = sesion.borrador.recursos[id_rec].model_dump_json()

        for j_str in (json_borrador, json_recurso):
            assert ":\\" not in j_str
            assert ":\\\\" not in j_str
            assert str(DIR_TEMP_SESIONES) not in j_str
            # No expone archivo_disco porque tiene exclude=True
            assert '"archivo_disco"' not in j_str

        # 5. La ruta física en disco se compone con la configuración del servidor sin estar en el JSON
        rec_obj = sesion.borrador.recursos[id_rec]
        p_fisica = obtener_ruta_fisica_recurso(rec_obj, session_id=sid)
        assert p_fisica is not None
        assert p_fisica.exists()
        assert p_fisica.name == f"{id_rec}_evidencia.png"
    finally:
        limpiar_archivos_temporales_sesion(sid)


def test_req_b_id_inexistente_o_de_otra_sesion_da_422_en_chat_bloques(client):
    """(b) Un id inexistente o de otra sesión en POST /chat/bloques da 422
    aunque la URL enviada parezca válida.
    """
    sid_a = "sesion_propietaria_a"
    sid_b = "sesion_ajena_b"
    texto_a = "Procedimiento completo de apertura de cuenta y parametrización de medios de pago."
    texto_b = "Procedimiento diferente para la parametrización contable del plan de cuentas."

    for s_id, t in ((sid_a, texto_a), (sid_b, texto_b)):
        SESIONES[s_id] = SesionChat(
            session_id=s_id,
            estado=EstadoFlujo.REVISION_BORRADOR,
            titulo="Instructivo General",
            bloques_texto=[t],
            borrador=BorradorSesion(
                modo="nuevo",
                titulo="Instructivo General",
                bloques_texto=[t],
            ),
        )

    try:
        # Subir un archivo en sesion_a
        r_up = client.post(
            "/chat/recursos",
            headers={"X-Session-ID": sid_a},
            files={"file": ("captura.png", io.BytesIO(PNG_VALIDO), "image/png")},
            data={"posicion": "0"},
        )
        assert r_up.status_code == 200
        id_a = r_up.json()["recursos"][0]["id"]
        url_preview_a = r_up.json()["recursos"][0]["referencia"]

        # 1. Caso id inexistente en la sesión actual -> 422
        r_inexistente = client.post(
            "/chat/bloques",
            headers={"X-Session-ID": sid_a},
            json={
                "bloques": [
                    {"tipo": "texto", "contenido": texto_a},
                    {
                        "tipo": "recurso",
                        "recurso": {
                            "id": "rec_9999",
                            "url": "https://bc.finneg.com/valida.png",
                        },
                    },
                ]
            },
        )
        assert r_inexistente.status_code == 422
        assert "no existe en la sesión" in r_inexistente.json()["detail"]

        # 2. Caso id de otra sesión (id_a enviado desde sesion_b) -> 422
        r_otra_sesion = client.post(
            "/chat/bloques",
            headers={"X-Session-ID": sid_b},
            json={
                "bloques": [
                    {"tipo": "texto", "contenido": texto_b},
                    {
                        "tipo": "recurso",
                        "recurso": {
                            "id": id_a,
                            "url": url_preview_a,
                        },
                    },
                ]
            },
        )
        assert r_otra_sesion.status_code == 422
        assert "no existe en la sesión" in r_otra_sesion.json()["detail"]

        # 3. Caso URL interna enviada sin id a sesion_b -> 422 (sanitizar_url_recurso solo acepta http/https)
        r_url_interna = client.post(
            "/chat/bloques",
            headers={"X-Session-ID": sid_b},
            json={
                "bloques": [
                    {"tipo": "texto", "contenido": texto_b},
                    {
                        "tipo": "recurso",
                        "recurso": {
                            "url": url_preview_a,
                        },
                    },
                ]
            },
        )
        assert r_url_interna.status_code == 422

        # 4. Caso válido en sesion_a: cliente envía id: id_a (incluso si envía una URL diferente, el servidor la ignora)
        r_ok = client.post(
            "/chat/bloques",
            headers={"X-Session-ID": sid_a},
            json={
                "bloques": [
                    {"tipo": "texto", "contenido": texto_a},
                    {
                        "tipo": "recurso",
                        "recurso": {
                            "id": id_a,
                            "url": "https://url-que-el-servidor-debe-ignorar.com/test.png",
                        },
                    },
                ]
            },
        )
        assert r_ok.status_code == 200
        rec_final = r_ok.json()["recursos"][0]
        assert rec_final["id"] == id_a
        assert rec_final["origen"] == "subido"
        assert rec_final["referencia"] == url_preview_a
        assert "url-que-el-servidor-debe-ignorar" not in rec_final["referencia"]
    finally:
        limpiar_archivos_temporales_sesion(sid_a)
        limpiar_archivos_temporales_sesion(sid_b)


def test_req_c_imagen_al_principio_medio_y_final_con_bloques_vacios(client):
    """(c) Imagen al principio, en el medio y al final, con bloques vacíos,
    produce la posicion y orden correctos.
    """
    sid = "sesion-bloques-vacios-posiciones"
    texto_parrafo_1 = "Primer párrafo explicativo detallando la parametrización de la cuenta contable."
    texto_parrafo_2 = "Segundo párrafo con consideraciones adicionales respecto a la moneda de registración."
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Parametrización Contable",
        bloques_texto=[texto_parrafo_1, texto_parrafo_2],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Parametrización Contable",
            bloques_texto=[texto_parrafo_1, texto_parrafo_2],
        ),
    )
    h = {"X-Session-ID": sid}

    url_img = "https://bc.finneg.com/uploads/diagrama.png"

    # Caso C.1: Imagen al PRINCIPIO con bloques vacíos antes y después
    # ["", "   ", img, "", texto_parrafo_1]
    # Esperado: bloques_texto = [texto_parrafo_1], recurso con posicion = -1, orden = 0
    bloques_principio = [
        {"tipo": "texto", "contenido": ""},
        {"tipo": "texto", "contenido": "   "},
        {"tipo": "recurso", "recurso": {"url": url_img, "tipo": "imagen", "nombre": "Diagrama"}},
        {"tipo": "texto", "contenido": ""},
        {"tipo": "texto", "contenido": texto_parrafo_1},
    ]
    r_prin = client.post("/chat/bloques", headers=h, json={"bloques": bloques_principio})
    assert r_prin.status_code == 200, r_prin.text
    d_prin = r_prin.json()
    assert d_prin["bloques_texto"] == [texto_parrafo_1]
    assert len(d_prin["recursos"]) == 1
    assert d_prin["recursos"][0]["posicion"] == -1
    assert d_prin["recursos"][0]["orden"] == 0

    # Caso C.2: Imagen en el MEDIO con bloques vacíos intercalados
    # [texto_parrafo_1, "", img, "   ", texto_parrafo_2]
    # Esperado: bloques_texto = [texto_parrafo_1, texto_parrafo_2], recurso con posicion = 0, orden = 0
    bloques_medio = [
        {"tipo": "texto", "contenido": texto_parrafo_1},
        {"tipo": "texto", "contenido": ""},
        {"tipo": "recurso", "recurso": {"url": url_img, "tipo": "imagen", "nombre": "Diagrama"}},
        {"tipo": "texto", "contenido": "   "},
        {"tipo": "texto", "contenido": texto_parrafo_2},
    ]
    r_med = client.post("/chat/bloques", headers=h, json={"bloques": bloques_medio})
    assert r_med.status_code == 200, r_med.text
    d_med = r_med.json()
    assert d_med["bloques_texto"] == [texto_parrafo_1, texto_parrafo_2]
    assert len(d_med["recursos"]) == 1
    assert d_med["recursos"][0]["posicion"] == 0
    assert d_med["recursos"][0]["orden"] == 0

    # Caso C.3: Imagen al FINAL con bloques vacíos después
    # [texto_parrafo_1, texto_parrafo_2, "", img, "   ", ""]
    # Esperado: bloques_texto = [texto_parrafo_1, texto_parrafo_2], recurso con posicion = 1, orden = 0
    bloques_final = [
        {"tipo": "texto", "contenido": texto_parrafo_1},
        {"tipo": "texto", "contenido": texto_parrafo_2},
        {"tipo": "texto", "contenido": ""},
        {"tipo": "recurso", "recurso": {"url": url_img, "tipo": "imagen", "nombre": "Diagrama"}},
        {"tipo": "texto", "contenido": "   "},
        {"tipo": "texto", "contenido": ""},
    ]
    r_fin = client.post("/chat/bloques", headers=h, json={"bloques": bloques_final})
    assert r_fin.status_code == 200, r_fin.text
    d_fin = r_fin.json()
    assert d_fin["bloques_texto"] == [texto_parrafo_1, texto_parrafo_2]
    assert len(d_fin["recursos"]) == 1
    assert d_fin["recursos"][0]["posicion"] == 1
    assert d_fin["recursos"][0]["orden"] == 0


def test_req_d_varios_recursos_seguidos_con_bloques_vacios_en_el_medio(client):
    """(d) Varios recursos seguidos con bloques vacíos en el medio conservan
    su misma posicion y su orden contiguo correlativo.
    """
    sid = "sesion-recursos-consecutivos-vacios"
    t1 = "Sección inicial del manual con los requisitos previos para operar en tesorería."
    t2 = "Sección posterior del manual donde se valida el comprobante emitido por el sistema."
    SESIONES[sid] = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Manual Tesorería",
        bloques_texto=[t1, t2],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Manual Tesorería",
            bloques_texto=[t1, t2],
        ),
    )
    h = {"X-Session-ID": sid}

    url_1 = "https://bc.finneg.com/img1.png"
    url_2 = "https://bc.finneg.com/img2.png"
    url_3 = "https://bc.finneg.com/img3.png"

    bloques = [
        {"tipo": "texto", "contenido": t1},
        {"tipo": "recurso", "recurso": {"url": url_1, "tipo": "imagen", "nombre": "Img 1"}},
        {"tipo": "texto", "contenido": ""},
        {"tipo": "recurso", "recurso": {"url": url_2, "tipo": "imagen", "nombre": "Img 2"}},
        {"tipo": "texto", "contenido": "   "},
        {"tipo": "recurso", "recurso": {"url": url_3, "tipo": "imagen", "nombre": "Img 3"}},
        {"tipo": "texto", "contenido": t2},
    ]

    r = client.post("/chat/bloques", headers=h, json={"bloques": bloques})
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["bloques_texto"] == [t1, t2]
    recs = data["recursos"]
    assert len(recs) == 3

    # Los 3 recursos van tras el bloque 0 (t1) y tienen orden contiguo 0, 1, 2
    assert [r["posicion"] for r in recs] == [0, 0, 0]
    assert [r["orden"] for r in recs] == [0, 1, 2]
    assert [r["referencia"] for r in recs] == [url_1, url_2, url_3]

