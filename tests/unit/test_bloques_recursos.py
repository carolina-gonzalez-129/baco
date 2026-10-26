import io
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from baco.server.app.api import get_baco_agent, get_buscador_duplicados
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.config_limites import (
    MAX_RECURSOS_POR_SESION,
    MAX_RECURSOS_TOTAL_BYTES,
    RECURSO_MAX_BYTES,
)
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    EstadoFlujo,
)
from baco.server.schemas.recurso import (
    BloqueItem,
    ConfirmarBloquesRequest,
    ConfirmarBloquesResponse,
    Recurso,
    RecursoBloqueInput,
    sanitizar_url_recurso,
)
from baco.server.services.agente_service import ejecutar_skill_plantillas
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.recursos_service import (
    RecursoInvalidoError,
    componer_texto_publicable,
    derivar_desde_bloques,
    guardar_recurso_temporal_sesion,
    reindexar_marcadores_tras_eliminar,
    reindexar_marcadores_tras_reordenar,
)
from baco.server.services.orquestador.sesion import (
    SESIONES,
    GestorSesiones,
    SesionChat,
    gestor_sesiones,
)


@pytest.fixture(autouse=True)
def limpiar_sesiones():
    SESIONES.clear()
    yield
    SESIONES.clear()


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
# 1. Función pura derivar_desde_bloques: derivación, marcadores e idempotencia
# =========================================================================

def test_derivar_desde_bloques_funcion_pura_y_marcadores():
    """Verifica que derivar_desde_bloques derive texto_limpio con marcadores [[R1]], [[R2]]...

    y la lista aislada de recursos sin mutar entradas ni incluir recursos en el texto.
    """
    bloques = [
        BloqueItem(tipo="texto", contenido="Primer párrafo explicativo."),
        BloqueItem(
            tipo="recurso",
            recurso=RecursoBloqueInput(
                url="https://finneg.com/captura1.png",
                nombre="Captura de pantalla",
                tipo="imagen",
            ),
        ),
        BloqueItem(tipo="texto", contenido="Segundo párrafo con instrucciones intermedias."),
        BloqueItem(
            tipo="recurso",
            recurso=RecursoBloqueInput(
                url="https://finneg.com/manual.pdf",
                nombre="Manual PDF",
                tipo="documento",
            ),
        ),
    ]

    # Copia de control para verificar inmutabilidad
    bloques_len_original = len(bloques)

    texto_limpio, recursos, aviso = derivar_desde_bloques(bloques)

    # Inmutabilidad
    assert len(bloques) == bloques_len_original

    # Marcadores correlativos en texto_limpio
    esperado = (
        "Primer párrafo explicativo.\n\n"
        "[[recurso:rec_1]]\n\n"
        "Segundo párrafo con instrucciones intermedias.\n\n"
        "[[recurso:rec_2]]"
    )
    assert texto_limpio == esperado

    # Recursos en diccionario aislado con orden y metadatos
    assert len(recursos) == 2
    r1 = recursos["rec_1"]
    r2 = recursos["rec_2"]
    assert r1.id == "rec_1"
    assert r1.orden == 0
    assert r1.referencia == "https://finneg.com/captura1.png"
    assert r1.tipo == "imagen"

    assert r2.id == "rec_2"
    assert r2.orden == 1
    assert r2.referencia == "https://finneg.com/manual.pdf"
    assert r2.tipo == "documento"

    # Ninguna URL ni objeto de recurso reside en texto_limpio
    assert "https://finneg.com/captura1.png" not in texto_limpio
    assert "https://finneg.com/manual.pdf" not in texto_limpio

    # Aviso con solo tipo y cantidad
    assert aviso is not None
    assert "2 recursos" in aviso
    assert "1 imagen" in aviso
    assert "1 documento" in aviso
    # No contiene URLs ni paths
    assert "http" not in aviso


def test_derivar_desde_bloques_idempotencia_e_ids_estables():
    """Verifica que ejecutar repetidamente derivar_desde_bloques con los mismos bloques

    reutilice los IDs estables y no genere recursos duplicados.
    """
    bloques = [
        BloqueItem(tipo="texto", contenido="Paso 1"),
        BloqueItem(
            tipo="recurso",
            recurso=RecursoBloqueInput(url="https://finneg.com/diagrama.png", tipo="imagen"),
        ),
    ]

    # Pasada 1
    t1, recs1, _ = derivar_desde_bloques(bloques)
    assert "rec_1" in recs1
    assert t1 == "Paso 1\n\n[[recurso:rec_1]]"

    # Pasada 2 (idempotencia pasando recs1 como recursos_previos)
    t2, recs2, _ = derivar_desde_bloques(bloques, recursos_previos=recs1)
    assert t2 == t1
    assert len(recs2) == 1
    assert "rec_1" in recs2
    assert recs2["rec_1"].referencia == "https://finneg.com/diagrama.png"
    assert recs2["rec_1"].orden == 0


# =========================================================================
# 2. Agregar, reordenar y eliminar recursos sin alterar el resto de texto_limpio
# =========================================================================

def test_agregar_recurso_no_altera_texto_limpio():
    """Agregar un recurso intermedio preserva intactos los bloques de texto existentes."""
    bloques_iniciales = [
        BloqueItem(tipo="texto", contenido="Párrafo A"),
        BloqueItem(tipo="texto", contenido="Párrafo B"),
    ]
    t_orig, _, _ = derivar_desde_bloques(bloques_iniciales)
    assert t_orig == "Párrafo A\n\nPárrafo B"

    # Se agrega un recurso entre A y B
    bloques_nuevos = [
        BloqueItem(tipo="texto", contenido="Párrafo A"),
        BloqueItem(tipo="recurso", recurso=RecursoBloqueInput(url="https://finneg.com/foto.jpg")),
        BloqueItem(tipo="texto", contenido="Párrafo B"),
    ]
    t_nuevo, recs, _ = derivar_desde_bloques(bloques_nuevos)
    assert t_nuevo == "Párrafo A\n\n[[recurso:rec_1]]\n\nPárrafo B"
    # Los párrafos A y B no sufrieron alteraciones
    assert "Párrafo A" in t_nuevo
    assert "Párrafo B" in t_nuevo


def test_reordenar_y_eliminar_recursos_sin_alterar_texto():
    """Verifica reindexar marcadores al eliminar o reordenar recursos sin modificar el texto circundante."""
    texto_con_marcadores = (
        "Sección 1: Inicio de operaciones.\n\n"
        "[[R1]]\n\n"
        "Sección 2: Detalle del proceso.\n\n"
        "[[R2]]\n\n"
        "Sección 3: Consideraciones finales.\n\n"
        "[[R3]]"
    )

    # 1. Eliminar recurso R2 (orden_eliminado=1)
    texto_tras_del = reindexar_marcadores_tras_eliminar(texto_con_marcadores, orden_eliminado=1)
    # R2 desaparece y R3 se reindexa a R2
    assert "[[R2]]" in texto_tras_del
    assert "[[R3]]" not in texto_tras_del
    assert "Sección 1: Inicio de operaciones." in texto_tras_del
    assert "Sección 2: Detalle del proceso." in texto_tras_del
    assert "Sección 3: Consideraciones finales." in texto_tras_del

    # 2. Reordenar marcadores: invertir R1 y R2
    # mapa_orden: 0->1, 1->0
    mapa = {0: 1, 1: 0}
    texto_reordenado = reindexar_marcadores_tras_reordenar(texto_tras_del, mapa)
    assert "[[R1]]" in texto_reordenado
    assert "[[R2]]" in texto_reordenado
    # El texto de las secciones permanece exactamente igual
    assert "Sección 1: Inicio de operaciones." in texto_reordenado
    assert "Sección 2: Detalle del proceso." in texto_reordenado


# =========================================================================
# 3. Sanitización de URLs y rechazo de parámetros sensibles / SVG / marcadores
# =========================================================================

def test_sanitizar_url_recurso_elimina_query_fragmento_y_credenciales():
    """sanitizar_url_recurso debe eliminar parámetros sensibles, fragmentos y credenciales embebidas, conservando query no sensible."""
    url_con_todo = "https://usuario:token_secreto@dominio.com:8443/archivos/reporte.pdf?auth=xyz&id=10#pagina=2"
    url_limpia = sanitizar_url_recurso(url_con_todo)

    assert url_limpia == "https://dominio.com:8443/archivos/reporte.pdf?id=10"
    assert "token_secreto" not in url_limpia
    assert "usuario" not in url_limpia
    assert "auth=xyz" not in url_limpia
    assert "id=10" in url_limpia
    assert "#pagina=2" not in url_limpia


def test_rechazo_svg_estricto_en_url_y_mime():
    """El sistema rechaza estrictamente cualquier archivo SVG tanto por extensión como por MIME."""
    # 1. En sanitizar_url_recurso
    with pytest.raises(ValueError, match="SVG"):
        sanitizar_url_recurso("https://finneg.com/logo.svg")

    # 2. En RecursoBloqueInput por MIME
    with pytest.raises(ValidationError, match="SVG"):
        RecursoBloqueInput(url="https://finneg.com/vector.png", mime_type="image/svg+xml")

    # 3. En RecursoBloqueInput por extensión .svg
    with pytest.raises(ValidationError, match="SVG"):
        RecursoBloqueInput(url="https://finneg.com/dibujo.svg")

    # 4. En derivar_desde_bloques como salvaguarda directa
    item_svg = BloqueItem.model_construct(
        tipo="recurso",
        recurso=RecursoBloqueInput.model_construct(
            url="https://finneg.com/vector.svg",
            nombre="SVG",
            tipo="imagen",
            mime_type=None,
            tamano_bytes=None,
        ),
    )
    with pytest.raises(RecursoInvalidoError, match="SVG"):
        derivar_desde_bloques([item_svg])

    # 5. En guardar_recurso_temporal_sesion con magic bytes de SVG
    svg_bytes = b"<svg xmlns='http://www.w3.org/2000/svg'><circle/></svg>"
    with pytest.raises(RecursoInvalidoError, match="SVG"):
        with patch("baco.server.services.orquestador.recursos_service.PERMITIR_SUBIDA_RECURSOS", True):
            guardar_recurso_temporal_sesion(
                "sesion_svg", "archivo.svg", svg_bytes, "image/svg+xml", {}
            )


def test_rechazo_marcadores_inyectados_por_el_usuario():
    """Si el usuario escribe manualmente [[R1]] o [[recurso:rec_1]] en un bloque de texto, debe ser rechazado."""
    # 1. En el schema BloqueItem
    with pytest.raises(ValidationError, match="marcadores reservados"):
        BloqueItem(tipo="texto", contenido="Intentando inyectar [[R1]] manualmente en el texto.")

    # 2. En derivar_desde_bloques como salvaguarda
    item = BloqueItem(tipo="texto", contenido="Texto legítimo")
    item.contenido = "Texto modificado con [[R2]]"
    with pytest.raises(RecursoInvalidoError, match="marcadores reservados"):
        derivar_desde_bloques([item])


def test_rechazo_url_duplicada_y_limites_tamano_en_request():
    """ConfirmarBloquesRequest permite reutilizar la misma URL (ambos marcadores al mismo rec_id) y valida límites de tamaño y cantidad."""
    # 1. URL repetida en la misma petición reutiliza su rec_id
    req_rep = ConfirmarBloquesRequest(
        bloques=[
            BloqueItem(tipo="texto", contenido="A"),
            BloqueItem(tipo="recurso", recurso=RecursoBloqueInput(url="https://finneg.com/doc.pdf")),
            BloqueItem(tipo="texto", contenido="B"),
            BloqueItem(tipo="recurso", recurso=RecursoBloqueInput(url="https://finneg.com/doc.pdf?token=secret")),
        ]
    )
    tl_rep, recs_rep, _ = derivar_desde_bloques(req_rep.bloques)
    assert len(recs_rep) == 1
    assert tl_rep.count("[[recurso:rec_1]]") == 2

    # 2. Supera tamaño individual (>10 MB)
    with pytest.raises(ValidationError, match="tamaño máximo"):
        RecursoBloqueInput(
            url="https://finneg.com/pesado.zip",
            tamano_bytes=RECURSO_MAX_BYTES + 1,
        )

    # 3. Supera tamaño acumulado total (>50 MB) con recursos individuales válidos (9 MB cada uno)
    bloques_pesados = [BloqueItem(tipo="texto", contenido="Inicio")]
    for i in range(6):  # 6 * 9 MB = 54 MB > 50 MB
        bloques_pesados.append(
            BloqueItem(
                tipo="recurso",
                recurso=RecursoBloqueInput(
                    url=f"https://finneg.com/archivo_{i}.zip",
                    tamano_bytes=9 * 1024 * 1024,
                ),
            )
        )
    with pytest.raises(ValidationError, match="acumulado"):
        ConfirmarBloquesRequest(bloques=bloques_pesados)

    # 4. Supera cantidad máxima de recursos por sesión
    bloques_exceso = [BloqueItem(tipo="texto", contenido="Inicio")]
    for i in range(MAX_RECURSOS_POR_SESION + 1):
        bloques_exceso.append(
            BloqueItem(
                tipo="recurso",
                recurso=RecursoBloqueInput(url=f"https://finneg.com/archivo_{i}.png"),
            )
        )
    with pytest.raises(ValidationError, match="límite máximo"):
        ConfirmarBloquesRequest(bloques=bloques_exceso)


def test_hide_input_in_errors_y_validacion_cruzada():
    """Las excepciones de validación en BloqueItem y ConfirmarBloquesRequest deben ocultar los inputs."""
    try:
        BloqueItem(tipo="texto", contenido="", recurso=None)
    except ValidationError as e:
        error_str = str(e)
        # hide_input_in_errors=True oculta el valor de input ingresado
        assert "input_value" not in error_str

    # Bloque de tipo texto no puede tener recurso
    with pytest.raises(ValidationError, match="no debe incluir el campo 'recurso'"):
        BloqueItem(
            tipo="texto",
            contenido="Texto válido",
            recurso=RecursoBloqueInput(url="https://finneg.com/img.png"),
        )


# =========================================================================
# 4. Política frente a skills: descarte determinista si marcadores no coinciden
# =========================================================================

def test_skill_plantillas_descarta_respuesta_si_marcadores_no_coinciden():
    """Si la skill altera, elimina o agrega marcadores, se descarta su respuesta y se conserva el borrador."""
    texto_original = "Introducción al sistema.\n\n[[recurso:rec_1]]\n\nPasos finales.\n\n[[recurso:rec_2]]"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Guía de Instalación",
        texto_limpio=texto_original,
        recursos={
            "rec_1": Recurso(id="rec_1", tipo="imagen", nombre="Captura 1", referencia="https://finneg.com/1.png", orden=0),
            "rec_2": Recurso(id="rec_2", tipo="imagen", nombre="Captura 2", referencia="https://finneg.com/2.png", orden=1),
        },
        tipo_plantilla="instructivo",
    )

    mock_agente = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        ejecutar_skill_plantillas("sesion_skill_test", borrador, mock_agente)

    assert exc_info.value.status_code == 400
    assert "recursos multimedia" in exc_info.value.detail
    mock_agente.assert_not_called()


def test_skill_plantillas_acepta_cuando_no_hay_recursos():
    """Si el borrador no tiene recursos, la skill plantillas procesa el texto puro sin requerir marcadores."""
    texto_original = "Párrafo A descriptivo del sistema.\n\nPárrafo B con las instrucciones de instalación."
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Guía de Instalación",
        texto_limpio=texto_original,
        recursos={},
        tipo_plantilla="instructivo",
    )

    texto_maquetado = (
        "## Guía de Instalación\n\n"
        "### Introducción\nPárrafo A maquetado profesionalmente por BACO.\n\n"
        "### Procedimiento\nPárrafo B detallado paso a paso según estándar corporativo."
    )
    mock_agente_ok = MagicMock(return_value=texto_maquetado)

    with patch("baco.server.services.agente_service.actualizar_borrador_texto"):
        resultado = ejecutar_skill_plantillas("sesion_skill_ok", borrador, mock_agente_ok)

    assert resultado == texto_maquetado
    mock_agente_ok.assert_called_once()


# =========================================================================
# 5. Endpoint único POST /chat/bloques
# =========================================================================

def test_endpoint_post_chat_bloques(client):
    """Prueba el endpoint POST /chat/bloques: recepción de bloques, derivación y respuesta."""
    sid = "sesion-endpoint-bloques"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Artículo desde Bloques",
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Artículo desde Bloques",
            texto_limpio="Texto previo",
            conforme=True,
            conforme_en="2026-10-25T10:00:00Z",
        ),
    )
    SESIONES[sid] = sesion

    payload = {
        "session_id": sid,
        "bloques": [
            {"tipo": "texto", "contenido": "Sección inicial del artículo."},
            {
                "tipo": "recurso",
                "recurso": {
                    "url": "https://finneg.com/imagen.png?token=secret123#view",
                    "nombre": "Diagrama de flujo",
                    "tipo": "imagen",
                },
            },
            {"tipo": "texto", "contenido": "Sección secundaria posterior al diagrama."},
        ],
    }

    resp = client.post("/chat/bloques", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["session_id"] == sid
    assert data["texto_limpio"] == "Sección inicial del artículo.\n\n[[recurso:rec_1]]\n\nSección secundaria posterior al diagrama."
    assert len(data["recursos"]) == 1
    rec = data["recursos"][0]
    assert rec["id"] == "rec_1"
    assert rec["referencia"] == "https://finneg.com/imagen.png"
    assert "token=secret123" not in rec["referencia"]
    assert "1 imagen" in data["aviso"]

    # Verifica que la conformidad previa fue invalidada debido al cambio de contenido
    assert sesion.borrador.conforme is False
    assert sesion.borrador.conformidad_invalidada is True


def test_endpoint_post_chat_bloques_autosanitiza_pii_y_avisa(client):
    """Verifica que POST /chat/bloques autosanitiza PII y secretos inmediatamente,

    actualiza la sesión y borrador sin datos sensibles, y emite el aviso de privacidad.
    """
    sid = "sesion-endpoint-bloques-pii"
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_BORRADOR,
        titulo="Artículo con PII en bloques",
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Artículo con PII en bloques",
            texto_limpio="Texto previo",
        ),
    )
    SESIONES[sid] = sesion

    payload = {
        "session_id": sid,
        "bloques": [
            {
                "tipo": "texto",
                "contenido": "Configuración para el usuario con CUIL: 20-30405060-9 y mail personal juan@empresa.com.",
            },
            {
                "tipo": "recurso",
                "recurso": {
                    "url": "https://finneg.com/archivos/guia.png",
                    "nombre": "Diagrama de Configuración",
                    "tipo": "imagen",
                },
            },
        ],
    }

    resp = client.post("/chat/bloques", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["session_id"] == sid
    assert "20-30405060-9" not in data["texto_limpio"]
    assert "juan@empresa.com" not in data["texto_limpio"]
    assert "[CUIT_OCULTO]" in data["texto_limpio"]
    assert "usuario@ejemplo.com" in data["texto_limpio"]
    assert "[[recurso:rec_1]]" in data["texto_limpio"]

    # Aviso debe contener advertencia de privacidad y conteo de recursos
    assert "preservarte" in data["aviso"]
    assert "1 imagen" in data["aviso"]

    # La sesión y el borrador deben reflejar el texto sanitizado
    assert "20-30405060-9" not in sesion.borrador.texto_limpio
    assert "[CUIT_OCULTO]" in sesion.borrador.texto_limpio
    assert "[CUIT_OCULTO]" in sesion.texto_limpio
    assert "[CUIT_OCULTO]" in sesion.texto


# =========================================================================
# 6. Test de lectura en fila real de la Base de Datos (articulos.texto)
# =========================================================================

def test_real_db_recursos_nunca_en_columna_texto(clean_db):
    """Verifica directamente sobre la base de datos PostgreSQL real que la columna `texto`

    de la tabla `articulos` NUNCA almacena recursos, objetos de recursos ni marcadores internos.
    """
    # 1. Simular la derivación de texto_limpio y recursos
    bloques = [
        BloqueItem(tipo="texto", contenido="Paso 1: Iniciar sesión en el portal."),
        BloqueItem(
            tipo="recurso",
            recurso=RecursoBloqueInput(
                url="https://finneg.com/captura.png",
                nombre="Captura Login",
                tipo="imagen",
            ),
        ),
        BloqueItem(tipo="texto", contenido="Paso 2: Confirmar las credenciales."),
    ]
    texto_limpio, recursos, _ = derivar_desde_bloques(bloques)

    # 2. Generar el texto publicable para persistencia / publicación
    texto_publicable = componer_texto_publicable(texto_limpio, recursos)

    # 3. Insertar fila real en la tabla articulos de la base de prueba
    articulo_id = 99901
    titulo = "Procedimiento de Acceso Seguro"
    url_articulo = "https://bc.finneg.com/t/acceso-seguro/99901"

    with clean_db.cursor() as cur:
        # Asegurar categoría existente para foreign key
        cur.execute("INSERT INTO categorias (id, nombre) VALUES (1, 'General') ON CONFLICT (id) DO NOTHING;")
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, categoria_id, url, texto)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (articulo_id, titulo, 1, url_articulo, texto_publicable),
        )
    clean_db.commit()

    # 4. Leer la fila directamente desde la base de datos real
    with clean_db.cursor() as cur:
        cur.execute(
            """
            SELECT id, titulo, texto, texto_sin_headers, normalizar_texto(texto)
            FROM articulos
            WHERE id = %s;
            """,
            (articulo_id,),
        )
        fila = cur.fetchone()

    assert fila is not None
    db_id, db_titulo, db_texto, db_sin_headers, db_normalizado = fila

    assert db_id == articulo_id
    assert db_titulo == titulo

    # Aserciones sobre la persistencia en la columna texto:
    # (a) No contiene objetos serializados de recursos, JSON crudo ni tags internos tipo [[recurso:rec_X]]
    assert "[[recurso:" not in db_texto
    assert '"tamano_bytes"' not in db_texto
    assert '"mime_type"' not in db_texto
    assert 'class="Recurso"' not in db_texto

    # (b) Contiene el texto con el recurso Markdown inline en su posición exacta (sin sección ## Recursos)
    assert "Paso 1: Iniciar sesión en el portal." in db_texto
    assert "Paso 2: Confirmar las credenciales." in db_texto
    assert "## Recursos" not in db_texto
    assert "![Captura Login](https://finneg.com/captura.png)" in db_texto

    # (c) Limpieza
    with clean_db.cursor() as cur:
        cur.execute("DELETE FROM articulos WHERE id = %s;", (articulo_id,))
    clean_db.commit()
