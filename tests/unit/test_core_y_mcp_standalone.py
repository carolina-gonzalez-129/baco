"""Tests de la fachada baco.server.core, servidor MCP standalone, paridad y entorno demo."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from baco.server.config_limites import TEXTO_MAX, TEXTO_MIN, TITULO_MAX, TITULO_MIN
from baco.server.core.facade import buscar_duplicados as core_buscar_duplicados
from baco.server.core.facade import validar_formato as core_validar_formato
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.schemas.duplicados import (
    ArticuloSimilarTool,
    BuscarDuplicadosToolOutput,
    NivelCoincidenciaEnum,
)
from baco.server.schemas.validacion import StatusValidacionEnum, ValidarFormatoToolOutput
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.validar_articulo import (
    sanitizar_borrador,
    validar_texto_y_estructura_post_duplicados,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# 1. Aislamiento de imports y limpieza de stdout
# ============================================================================


def test_mcp_server_no_importa_fastapi_ni_app_main():
    """baco.server.mcp_server debe poder importarse sin arrastrar baco.server.app.main ni importar FastAPI."""
    import ast

    for rel_path in ("baco/server/mcp_server.py", "baco/server/core/facade.py"):
        tree = ast.parse((PROJECT_ROOT / rel_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("fastapi"), f"{rel_path} importa fastapi"
                    assert not alias.name.startswith("baco.server.app"), f"{rel_path} importa {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("fastapi"), f"{rel_path} importa de fastapi"
                assert not node.module.startswith("baco.server.app.main"), f"{rel_path} importa de app.main"

    codigo = (
        "import sys\n"
        "import baco.server.mcp_server\n"
        "for mod_prohibido in ('baco.server.app.main', 'baco.server.app.api', 'baco.server.app.lifespan'):\n"
        "    assert mod_prohibido not in sys.modules, f'Importó {mod_prohibido}'\n"
        "print('AISLAMIENTO_OK', file=sys.stderr)\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"Fallo en aislamiento: stderr={res.stderr}"
    assert "AISLAMIENTO_OK" in res.stderr
    assert res.stdout == "", f"Se ensució stdout al importar mcp_server: {res.stdout!r}"


def test_stdout_limpio_durante_ejecucion_de_tools():
    """Importar y ejecutar las tools del MCP no debe escribir absolutamente nada en stdout."""
    codigo = (
        "from baco.server.mcp_server import validar_formato\n"
        "res = validar_formato(\n"
        "    titulo='Configurar un punto de venta electrónico en facturación',\n"
        "    texto='# Consulta\\nTexto de consulta suficientemente largo.\\n\\n# Pasos a seguir\\n1. Primer paso detallado.'\n"
        ")\n"
        "assert res.status is not None\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"Error ejecutando tool: {res.stderr}"
    assert res.stdout == "", f"stdout debe estar 100% limpio para stdio JSON-RPC, pero recibió: {res.stdout!r}"


def test_cero_log_de_argumentos_en_tools(caplog):
    """Los logs de la fachada y del MCP jamás deben incluir el título ni el texto enviado."""
    secreto_titulo = "TITULO_SECRETO_CONFIDENCIAL_991122"
    secreto_texto = (
        "# Consulta\n"
        "TEXTO_SECRETO_CONFIDENCIAL_887766 con longitud suficiente para pasar validación.\n\n"
        "# Pasos a seguir\n"
        "1. Ejecutar acción de prueba."
    )

    with caplog.at_level(logging.DEBUG):
        core_validar_formato(titulo=secreto_titulo, texto=secreto_texto)

        @contextmanager
        def fake_conn():
            conn = MagicMock()
            yield conn

        class FakeBuscador:
            def __init__(self, cur):
                pass

            def evaluar_coincidencias(self, titulo, headers=True, texto=None, limite=3):
                return {
                    "encontrado": False,
                    "mensaje": "No se encontraron coincidencias.",
                    "coincidencias": [],
                    "link": None,
                }

        core_buscar_duplicados(
            titulo=secreto_titulo,
            texto=secreto_texto,
            limite=3,
            _get_ro_conn=fake_conn,
            _buscador_cls=FakeBuscador,
        )

    mensajes_log = " ".join(r.getMessage() for r in caplog.records)
    assert secreto_titulo not in mensajes_log
    assert "TEXTO_SECRETO_CONFIDENCIAL_887766" not in mensajes_log


# ============================================================================
# 2. Límites de entrada y manejo de ArticuloSchema inválido sin excepción
# ============================================================================


@pytest.mark.parametrize(
    "titulo,texto,limite,fragmento_esperado",
    [
        ("", None, 3, "No se proporcionó ni título ni borrador"),
        ("   ", None, 3, "No se proporcionó ni título ni borrador"),
        ("Corto", None, 3, f"entre {TITULO_MIN} y {TITULO_MAX}"),
        ("A" * (TITULO_MAX + 1), None, 3, f"entre {TITULO_MIN} y {TITULO_MAX}"),
        ("Título válido para búsqueda de duplicados", "Corto", 3, f"entre {TEXTO_MIN} y {TEXTO_MAX}"),
        ("Título válido para búsqueda de duplicados", "X" * (TEXTO_MAX + 1), 3, f"entre {TEXTO_MIN} y {TEXTO_MAX}"),
        ("Título válido para búsqueda de duplicados", None, 0, "entre 1 y 10"),
        ("Título válido para búsqueda de duplicados", None, -5, "entre 1 y 10"),
        ("Título válido para búsqueda de duplicados", None, 11, "entre 1 y 10"),
        ("Título válido para búsqueda de duplicados", None, True, "entre 1 y 10"),
    ],
)
def test_buscar_duplicados_entradas_invalidas_no_lanzan_excepcion_ni_tocan_db(
    titulo, texto, limite, fragmento_esperado
):
    """Entradas fuera de cota en buscar_duplicados devuelven respuesta controlada sin abrir conexión."""
    conn_llamada = False

    @contextmanager
    def fail_if_called():
        nonlocal conn_llamada
        conn_llamada = True
        yield MagicMock()

    out = core_buscar_duplicados(
        titulo=titulo,
        texto=texto,
        limite=limite,
        _get_ro_conn=fail_if_called,
    )
    assert isinstance(out, BuscarDuplicadosToolOutput)
    assert out.hay_duplicados is False
    assert out.nivel == NivelCoincidenciaEnum.NINGUNO
    assert out.articulos_similares == []
    assert fragmento_esperado in out.mensaje
    assert conn_llamada is False


@pytest.mark.parametrize(
    "titulo,texto",
    [
        ("", "Texto suficientemente largo para probar título vacío en validación."),
        ("Corto", "Texto suficientemente largo para probar título corto en validación."),
        ("T" * (TITULO_MAX + 5), "Texto suficientemente largo para probar título largo."),
        ("Título válido de prueba para validación", ""),
        ("Título válido de prueba para validación", "Corto"),
        ("Título válido de prueba para validación", "B" * (TEXTO_MAX + 5)),
        (None, None),
    ],
)
def test_validar_formato_entradas_invalidas_no_lanzan_excepcion(titulo, texto):
    """validar_formato captura cualquier error de cota o ArticuloSchema y devuelve status=Pendiente."""
    out = core_validar_formato(titulo=titulo, texto=texto)
    assert isinstance(out, ValidarFormatoToolOutput)
    assert out.valido is False
    assert out.status == StatusValidacionEnum.PENDIENTE
    assert len(out.hallazgos) >= 1


# ============================================================================
# 3. Niveles exacto/similar/ninguno, score=1.0 en exactos y privacidad
# ============================================================================


def test_buscar_duplicados_exacto_fija_nivel_exacto_y_score_uno_sin_texto():
    """En coincidencias exactas, nivel debe ser 'exacto', score=1.0 y jamás exponer el cuerpo."""
    @contextmanager
    def fake_conn():
        yield MagicMock()

    class FakeBuscadorExacto:
        def __init__(self, cur):
            pass

        def evaluar_coincidencias(self, titulo, headers=True, texto=None, limite=3):
            return {
                "encontrado": True,
                "mensaje": "Ya existe un artículo con exactamente este título.",
                "link": "https://conocimiento.ejemplo.local/t/1001",
                "coincidencias": [
                    {
                        "id": 1001,
                        "titulo": "Cómo configurar un punto de venta electrónico",
                        "url": "https://conocimiento.ejemplo.local/t/1001",
                        "texto": "CUERPO_PRIVADO_QUE_NO_DEBE_SALIR",
                        "score": None,
                    }
                ],
            }

    out = core_buscar_duplicados(
        titulo="Cómo configurar un punto de venta electrónico",
        limite=3,
        _get_ro_conn=fake_conn,
        _buscador_cls=FakeBuscadorExacto,
    )
    assert out.hay_duplicados is True
    assert out.nivel == NivelCoincidenciaEnum.EXACTO
    assert len(out.articulos_similares) == 1
    assert out.articulos_similares[0].score == 1.0
    dumped = out.articulos_similares[0].model_dump()
    assert "texto" not in dumped
    assert "CUERPO_PRIVADO_QUE_NO_DEBE_SALIR" not in str(out.model_dump())


def test_buscar_duplicados_similar_fija_nivel_similar():
    """En coincidencias semánticas o por trigramas, nivel debe ser 'similar' y preservar score."""
    @contextmanager
    def fake_conn():
        yield MagicMock()

    class FakeBuscadorSimilar:
        def __init__(self, cur):
            pass

        def evaluar_coincidencias(self, titulo, headers=True, texto=None, limite=3):
            return {
                "encontrado": True,
                "mensaje": "Se encontraron artículos semánticamente similares.",
                "link": "https://conocimiento.ejemplo.local/t/1002",
                "coincidencias": [
                    {
                        "id": 1002,
                        "titulo": "Error de certificado digital vencido al autorizar comprobantes",
                        "url": "https://conocimiento.ejemplo.local/t/1002",
                        "score_total": 0.912,
                    }
                ],
            }

    out = core_buscar_duplicados(
        titulo="Certificado digital expirado en facturación electrónica",
        limite=3,
        _get_ro_conn=fake_conn,
        _buscador_cls=FakeBuscadorSimilar,
    )
    assert out.hay_duplicados is True
    assert out.nivel == NivelCoincidenciaEnum.SIMILAR
    assert out.articulos_similares[0].score == pytest.approx(0.912)


def test_validar_formato_sanitiza_cuit_y_email_real():
    """validar_formato aplica la sanitización determinista de CUITs y correos reales."""
    titulo = "Cómo configurar un punto de venta electrónico en el sistema"
    texto_con_pii = (
        "# Consulta\n"
        "El cliente con CUIT 20-12345678-6 reportó un problema desde juan.perez@empresa.com.ar al emitir su factura.\n\n"
        "# Pasos a seguir\n"
        "1. Verificar los datos fiscales en el padrón antes de reemitir."
    )
    out = core_validar_formato(titulo=titulo, texto=texto_con_pii)
    assert "20-12345678-6" not in (out.texto_sanitizado or "")
    assert "juan.perez@empresa.com.ar" not in (out.texto_sanitizado or "")
    assert "Cómo " not in (out.titulo_sanitizado or "")


# ============================================================================
# 4. Paridad entre la fachada (core) y los services que usa el orquestador
# ============================================================================


@pytest.mark.parametrize(
    "titulo,texto,tags,categoria_id",
    [
        (
            "Configurar un punto de venta electrónico en el módulo de facturación",
            "# Consulta\nSe necesita dar de alta un nuevo punto de venta electrónico en el sistema.\n\n"
            "# Pasos a seguir\n1. Ingresar a Configuración > Puntos de Venta.\n2. Presionar Nuevo y guardar.",
            ["facturacion", "instructivo"],
            10,
        ),
        (
            "Error de certificado digital vencido al autorizar comprobantes",
            "# Causa\nEl certificado digital superó su fecha de expiración anual.\n\n"
            "# Solución\n1. Renovar el certificado y subirlo en Configuración > Seguridad.",
            ["facturacion", "solucion"],
            10,
        ),
        (
            "Artículo incompleto sin las secciones obligatorias de la plantilla",
            "Este texto tiene longitud suficiente pero no contiene ningún encabezado markdown válido.",
            [],
            None,
        ),
    ],
)
def test_paridad_validar_formato_fachada_vs_services_orquestador(titulo, texto, tags, categoria_id):
    """La fachada validar_formato debe dar el mismo resultado que validar_texto_y_estructura_post_duplicados."""
    out_fachada = core_validar_formato(
        titulo=titulo,
        texto=texto,
        tags=tags,
        categoria_id=categoria_id,
    )

    tags_obj = [Tag(name=t) for t in tags]
    esquema = ArticuloSchema(
        id=0,
        titulo=titulo,
        texto=texto,
        tags=tags_obj,
        categoria_id=categoria_id,
    )
    res_service = validar_texto_y_estructura_post_duplicados(esquema)

    assert out_fachada.status.value == res_service["status"]
    assert out_fachada.valido == (res_service["status"] != "Pendiente")
    assert out_fachada.titulo_sanitizado == res_service["titulo_sanitizado"]
    assert out_fachada.texto_sanitizado == res_service["texto_sanitizado"]
    assert out_fachada.longitud_texto == res_service["longitud_texto"]
    assert out_fachada.tags_count == res_service["tags_count"]
    assert [h.descripcion for h in out_fachada.hallazgos] == [
        f.get("description", "") for f in res_service.get("findings", [])
    ]


def test_paridad_buscar_duplicados_fachada_vs_buscador_service():
    """La fachada buscar_duplicados produce los mismos artículos y estado que BuscadorDuplicados."""
    respuesta_simulada = {
        "encontrado": True,
        "mensaje": "Se encontraron artículos semánticamente similares.",
        "link": "https://conocimiento.ejemplo.local/t/1010",
        "coincidencias": [
            {
                "id": 1010,
                "titulo": "Asiento contable desbalanceado al contabilizar liquidación de impuestos",
                "url": "https://conocimiento.ejemplo.local/t/1010",
                "score_total": 0.94,
            }
        ],
    }

    class FakeBuscador(BuscadorDuplicados):
        def __init__(self, cur):
            self.cur = cur

        def evaluar_coincidencias(self, titulo, headers=True, texto=None, limite=3):
            return respuesta_simulada

    @contextmanager
    def fake_conn():
        yield MagicMock()

    titulo = "Asiento contable desbalanceado en liquidación impositiva"
    texto = "# Causa\nFalta cuenta contable en la matriz.\n\n# Solución\n1. Asignar cuenta en configuración."

    res_service = FakeBuscador(MagicMock()).evaluar_coincidencias(
        titulo=titulo, headers=True, texto=texto, limite=3
    )
    res_fachada = core_buscar_duplicados(
        titulo=titulo,
        texto=texto,
        limite=3,
        _get_ro_conn=fake_conn,
        _buscador_cls=FakeBuscador,
    )

    assert res_fachada.hay_duplicados == res_service["encontrado"]
    assert res_fachada.mensaje == res_service["mensaje"]
    assert res_fachada.url_principal == res_service["link"]
    assert [a.id for a in res_fachada.articulos_similares] == [
        c["id"] for c in res_service["coincidencias"]
    ]
    assert [a.titulo for a in res_fachada.articulos_similares] == [
        c["titulo"] for c in res_service["coincidencias"]
    ]
    assert [a.url for a in res_fachada.articulos_similares] == [
        c["url"] for c in res_service["coincidencias"]
    ]


# ============================================================================
# 5. Equivalencia de schema_completo.sql y auditoría de seed.sql sin PII
# ============================================================================


def test_equivalencia_schema_completo_con_duplicados_schema_y_sin_password_hardcodeada():
    """schema_completo.sql debe incluir íntegramente duplicados_schema.sql y no tener contraseñas fijas."""
    ruta_completo = PROJECT_ROOT / "baco" / "server" / "db" / "schema_completo.sql"
    ruta_duplicados = PROJECT_ROOT / "baco" / "server" / "db" / "duplicados_schema.sql"

    sql_completo = ruta_completo.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    sql_duplicados = ruta_duplicados.read_text(encoding="utf-8").replace("\r\n", "\n").strip()

    assert sql_duplicados in sql_completo, (
        "El bloque del schema duplicados en schema_completo.sql no coincide exactamente con duplicados_schema.sql"
    )
    assert "current_setting('baco.ro_password'" in sql_completo
    assert not re.search(
        r"CREATE\s+ROLE\s+baco_readonly\s+WITH\s+LOGIN\s+PASSWORD\s+'[^']+'",
        sql_completo,
        re.IGNORECASE,
    ), "No debe haber contraseña literal hardcodeada para baco_readonly en schema_completo.sql"


def test_seed_sql_tiene_entre_30_y_50_articulos_con_embeddings_y_sin_pii():
    """seed.sql debe tener 30-50 artículos sintéticos, embeddings precalculados y cero PII real."""
    ruta_seed = PROJECT_ROOT / "baco" / "server" / "db" / "seed.sql"
    assert ruta_seed.exists(), "Falta el archivo baco/server/db/seed.sql"

    contenido = ruta_seed.read_text(encoding="utf-8")
    inserts_articulos = re.findall(
        r"INSERT\s+INTO\s+public\.articulos\s*\(",
        contenido,
        flags=re.IGNORECASE,
    )
    cantidad = len(inserts_articulos)
    assert 30 <= cantidad <= 50, f"Se esperaban entre 30 y 50 artículos en seed.sql, pero hay {cantidad}"

    # Verificar que cada artículo tenga dos vectores precalculados (384 dims y 768 dims)
    vectores = re.findall(r"'\[([-0-9.,eE]+)\]'\:\:public\.vector", contenido)
    assert len(vectores) == cantidad * 2, (
        f"Cada artículo debe tener embedding_titulo y embedding_texto precalculados ({cantidad * 2} vectores)"
    )
    dims_primer_par = [len(vectores[0].split(",")), len(vectores[1].split(","))]
    assert dims_primer_par == [384, 768]

    # Extraer el texto sin los vectores numéricos y verificar ausencia total de PII (CUITs, emails, CBUs, tarjetas, etc.)
    contenido_sin_vectores = re.sub(r"'\[[-0-9.,eE]+\]'\:\:public\.vector", "''", contenido)
    sanitizado = sanitizar_borrador(
        texto=contenido_sin_vectores,
        titulo="Auditoría de seed",
        sanitizar_redundancia_titulo=False,
    )
    assert sanitizado["aviso_privacidad"] is None, (
        f"Se detectaron datos sensibles en seed.sql: {sanitizado['aviso_privacidad']}"
    )
    assert sanitizado["texto_sanitizado"] == contenido_sin_vectores.strip()


def test_facade_mide_cotas_y_reporta_con_texto_efectivo_sin_marcadores():
    """Ítem 3: facade.py mide cotas de texto (buscar_duplicados y validar_formato),
    genera el mensaje de error y reporta longitud_texto siempre con texto_efectivo_sin_marcadores()."""
    # 1. buscar_duplicados rechaza texto con longitud efectiva menor a TEXTO_MIN aunque con marcadores supere 20
    # "Hola mundo" (10 chars) + marcador "[[recurso:rec_1]]" (17 chars) = 27 chars brutos, pero 10 efectivos
    texto_corto_con_marcador = "Hola mundo [[recurso:rec_1]]"
    res_dup = core_buscar_duplicados(texto=texto_corto_con_marcador)
    assert res_dup.hay_duplicados is False
    assert f"El texto debe tener entre {TEXTO_MIN} y {TEXTO_MAX} caracteres." in res_dup.mensaje

    # 2. validar_formato reporta longitud_texto efectiva y mensaje de error con longitud efectiva
    res_val = core_validar_formato(
        titulo="Título de prueba para validación",
        texto=texto_corto_con_marcador,
        tags=["manual", "soporte"],
        categoria_id=1,
    )
    assert res_val.valido is False
    assert res_val.longitud_texto == 10
    hallazgo_texto = next(h for h in res_val.hallazgos if h.campo == "texto")
    assert "recibidos: 10" in hallazgo_texto.descripcion
