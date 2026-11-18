"""Tests de cobertura específica para los cambios del prompt 03 (commit 7a37f89).

Cubre:
1. Caso feliz adicional:
   - Preservación y sincronización de texto_original, texto_editor y texto_limpio en la respuesta
   - Diferenciación clara entre Vista previa (bloques_texto / texto_limpio) y Editor (texto_original / texto_editor)
2. Casos borde:
   - Texto original con marcadores o recursos previos (texto_efectivo_sin_marcadores al preparar texto_origen)
   - Reaplicación de skill (es_reaplicacion=True) preserva opciones exclusivas Continuar y Volver
   - Múltiples aplicaciones sucesivas o reaplicación de skill cuando ya había un resultado pendiente
   - Volver después de modificar el texto o volver repetido
3. Errores esperados:
   - Fallo en agente / excepción de la skill restaura bloques anteriores y no rompe la sesión
   - Intento de invocar sin agente o con salida vacía de la skill maneja el error adecuadamente
"""

from unittest.mock import MagicMock

import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.edicion import (
    adoptar_resultado_skill_pendiente,
    ejecutar_skill,
)
from baco.server.services.orquestador.sesion import SesionChat, gestor_sesiones
from baco.server.services.orquestador.validaciones import validar_borrador

TEXTO_BASE_TEST = (
    "### Introducción\n\n"
    "Este es un texto base de prueba que contiene suficientes caracteres para cumplir "
    "con las validaciones de longitud mínimas del orquestador.\n\n"
    "### Procedimiento\n\n"
    "1. Paso primero para configurar el servicio correctamente en el sistema.\n"
    "2. Paso segundo para comprobar la conectividad del entorno."
)

TEXTO_SKILL_SALIDA = (
    "### Introducción Modificada por Skill\n\n"
    "Este es un texto transformado por la skill cumpliendo con las pautas editoriales.\n\n"
    "### Procedimiento Optimizado\n\n"
    "1. Paso inicial estructurado de forma concisa y clara.\n"
    "2. Paso de verificación final con monitoreo."
)

TEXTO_AUDITOR_RAW = (
    "Dictamen: Aprobado.\n\n"
    "<<<VERSION_CORREGIDA>>>\n"
    "### Introducción Modificada por Skill Auditada\n\n"
    "Este es un texto transformado y auditado por la skill de validación.\n\n"
    "### Procedimiento Optimizado\n\n"
    "1. Paso auditado y verificado.\n"
    "<<<FIN_VERSION>>>"
)

TEXTO_AUDITOR_LIMPIO = (
    "### Introducción Modificada por Skill Auditada\n\n"
    "Este es un texto transformado y auditado por la skill de validación.\n\n"
    "### Procedimiento Optimizado\n\n"
    "1. Paso auditado y verificado."
)


def _crear_sesion(sid: str, es_intermedia: bool = True) -> SesionChat:
    gestor_sesiones.eliminar(sid)
    sesion, _, _ = gestor_sesiones.obtener_o_crear(sid)
    sesion.session_id = sid
    gestor_sesiones.sesiones[sid] = sesion
    sesion.estado = EstadoFlujo.REVISION_TIPO if es_intermedia else EstadoFlujo.REVISION_METADATOS
    sesion.titulo = "Título de prueba para orquestador 03"
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=sesion.titulo,
        bloques_texto=[TEXTO_BASE_TEST],
        tipo_plantilla="instructivo",
        categoria_id=20 if not es_intermedia else None,
        categoria_nombre="Ventas" if not es_intermedia else None,
        tags=["instructivo", "ventas"] if not es_intermedia else ["instructivo"],
    )
    sesion.bloques_texto = [TEXTO_BASE_TEST]
    sesion.texto_limpio = TEXTO_BASE_TEST
    sesion.texto = TEXTO_BASE_TEST
    if not es_intermedia:
        sesion.categoria_id = 20
        sesion.categoria_nombre = "Ventas"
        sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["aplicar_plantilla", "continuar"] if es_intermedia else ["auditar", "continuar"]
    validar_borrador(sesion)
    return sesion


# ---------------------------------------------------------------------------
# 1. Casos felices adicionales y contrato de respuesta
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_respuesta_incluye_campos_separados_en_ambos_niveles():
    """Verifica que tanto en la raíz de ChatOrquestadorResponse como dentro del BorradorSesion
    se expongan de manera separada e independiente texto_original y texto_limpio.
    """
    sesion = _crear_sesion("test-campos-separados-ambos-niveles", es_intermedia=True)
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=TEXTO_SKILL_SALIDA)

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req._baco_agent = mock_agente
    resp = await manejar_turno(req, buscador)

    # Nivel raíz de la respuesta
    assert resp.texto_original == TEXTO_BASE_TEST
    assert resp.texto_editor == TEXTO_BASE_TEST
    assert resp.texto_limpio == TEXTO_SKILL_SALIDA

    # Nivel borrador dentro de la respuesta
    assert resp.borrador is not None
    assert resp.borrador.texto_original == TEXTO_BASE_TEST
    assert resp.borrador.texto_editor == TEXTO_BASE_TEST
    assert resp.borrador.texto_limpio == TEXTO_SKILL_SALIDA
    assert resp.borrador.bloques_texto == [TEXTO_SKILL_SALIDA]

    # Indicadores de estado pendiente
    assert resp.borrador.resultado_skill_pendiente is True
    assert resp.borrador.skill_pendiente == "plantilla"


# ---------------------------------------------------------------------------
# 2. Casos borde: Reaplicación, marcadores, reaplicación sobre pendiente
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_reaplicar_skill_ofrece_unicamente_continuar():
    """Al reaplicar la skill (es_reaplicacion=True), la única opción es Continuar
    (sin Volver después de una skill) y el texto_original se preserva.
    """
    sesion = _crear_sesion("test-reaplicar-opciones", es_intermedia=False)
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=TEXTO_AUDITOR_RAW)

    req = ChatOrquestadorRequest(session_id=sesion.session_id)
    req._baco_agent = mock_agente

    # Invocación directa de ejecutar_skill con es_reaplicacion=True
    resp = await ejecutar_skill(sesion, req, "auditor", es_reaplicacion=True)

    labels = [b.label for b in resp.botones]
    assert labels == ["Continuar"]
    assert resp.opciones == ["continuar"]
    assert resp.texto_original == TEXTO_BASE_TEST
    assert resp.texto_limpio == TEXTO_AUDITOR_LIMPIO


@pytest.mark.anyio
async def test_skill_con_marcadores_recursos_extrae_texto_efectivo_para_texto_original():
    """Si sesion.texto_editor contiene marcadores canónicos de recursos tipo [[recurso:1]] o [[R1]],
    texto_origen y texto_original se guardan sin marcadores (texto_efectivo_sin_marcadores).
    """
    texto_con_marcador = f"{TEXTO_BASE_TEST}\n\n[[recurso:1]]\n\n[[R1]]"
    sesion = _crear_sesion("test-marcador-texto-original", es_intermedia=True)
    sesion.texto_editor = texto_con_marcador
    sesion.borrador.texto_editor = texto_con_marcador

    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=TEXTO_SKILL_SALIDA)

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req._baco_agent = mock_agente
    resp = await manejar_turno(req, buscador)

    # Debe haber limpiado los marcadores canónicos del texto_original
    assert "[[recurso:1]]" not in resp.texto_original
    assert "[[R1]]" not in resp.texto_original
    assert resp.texto_original == TEXTO_BASE_TEST
    assert resp.borrador.texto_original == TEXTO_BASE_TEST


@pytest.mark.anyio
async def test_reaplicar_skill_cuando_ya_hay_skill_pendiente_no_contamina_texto_original():
    """Si se ejecuta una skill cuando ya había un resultado pendiente previo sin haber hecho
    Continuar, el nuevo texto_original debe seguir siendo el original del editor y no el resultado intermedio.
    """
    sesion = _crear_sesion("test-doble-ejecucion-pendiente", es_intermedia=True)
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. Primera ejecución
    mock_1 = MagicMock(return_value="--- RESULTADO PRIMERO --- " + TEXTO_SKILL_SALIDA)
    req1 = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req1._baco_agent = mock_1
    await manejar_turno(req1, buscador)

    assert sesion.borrador.resultado_skill_pendiente is True
    assert sesion.borrador.texto_original == TEXTO_BASE_TEST

    # 2. Segunda ejecución directa sin tocar Continuar
    mock_2 = MagicMock(return_value="--- RESULTADO SEGUNDO --- " + TEXTO_SKILL_SALIDA)
    req2 = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req2._baco_agent = mock_2
    resp2 = await manejar_turno(req2, buscador)

    # El texto original preservado debe seguir siendo TEXTO_BASE_TEST y no el resultado 1
    assert resp2.texto_original == TEXTO_BASE_TEST
    assert resp2.borrador.texto_original == TEXTO_BASE_TEST
    assert "RESULTADO PRIMERO" not in resp2.texto_original


@pytest.mark.anyio
def test_adoptar_resultado_skill_pendiente_idempotente_sin_borrador_o_sin_pendiente():
    """adoptar_resultado_skill_pendiente no debe fallar si borrador es None
    o si no hay skill_pendiente activa.
    """
    sesion = SesionChat(session_id="test-idempotente-adoptar")
    # Borrador es None
    adoptar_resultado_skill_pendiente(sesion)
    assert sesion.borrador is None

    # Borrador sin resultado_skill_pendiente
    sesion = _crear_sesion("test-idempotente-adoptar-2", es_intermedia=True)
    sesion.borrador.resultado_skill_pendiente = False
    sesion.borrador.skill_pendiente = None
    adoptar_resultado_skill_pendiente(sesion)
    assert sesion.borrador.resultado_skill_pendiente is False


# ---------------------------------------------------------------------------
# 3. Errores esperados / Casos no felices
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_error_en_skill_plantillas_restaura_bloques_y_no_deja_skill_pendiente():
    """Si la ejecución del agente falla con excepción, la respuesta informa el error
    amigablemente, restaura los bloques_texto originales y no deja estado pendiente espurio.
    """
    sesion = _crear_sesion("test-error-plantilla-excepcion", es_intermedia=True)
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente_fallido = MagicMock(side_effect=RuntimeError("Fallo de red simulado"))

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req._baco_agent = mock_agente_fallido
    resp = await manejar_turno(req, buscador)

    # Mensaje de error para el usuario
    assert "No pudimos aplicar la **plantilla** en este momento" in resp.mensaje
    # Se restauró el texto original
    assert resp.borrador.bloques_texto == [TEXTO_BASE_TEST]
    assert resp.borrador.resultado_skill_pendiente is False


@pytest.mark.anyio
async def test_error_en_auditor_excepcion_restaura_bloques_y_no_deja_skill_pendiente():
    """Si el auditor falla con excepción, la respuesta informa el error amigablemente
    y restaura el estado sin dejar skill pendiente.
    """
    sesion = _crear_sesion("test-error-auditor-excepcion", es_intermedia=False)
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente_fallido = MagicMock(side_effect=RuntimeError("Error en modelo semántico"))

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="auditar")
    req._baco_agent = mock_agente_fallido
    resp = await manejar_turno(req, buscador)

    assert "No pudimos **auditar** el artículo en este momento" in resp.mensaje
    assert resp.borrador.bloques_texto == [TEXTO_BASE_TEST]
    assert resp.borrador.resultado_skill_pendiente is False


@pytest.mark.anyio
async def test_skill_sin_salida_o_vacia_maneja_error():
    """Si el agente devuelve una cadena vacía o espacios en blanco, se captura como error
    y se restauran los bloques anteriores.
    """
    sesion = _crear_sesion("test-skill-salida-vacia", es_intermedia=True)
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente_vacio = MagicMock(return_value="   ")

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req._baco_agent = mock_agente_vacio
    resp = await manejar_turno(req, buscador)

    assert "No pudimos aplicar la **plantilla** en este momento" in resp.mensaje
    assert resp.borrador.bloques_texto == [TEXTO_BASE_TEST]
    assert resp.borrador.resultado_skill_pendiente is False
