from unittest.mock import MagicMock

import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.mensajes import (
    MSG_EDICION_FINAL,
    MSG_OPCION_NO_DISPONIBLE,
    OPCIONES_CONFIRMAR_PLANTILLA,
    OPCIONES_EDICION_FINAL,
)
from baco.server.services.orquestador.sesion import SesionChat, gestor_sesiones

TEXTO_VALIDO = (
    "Este es un texto completo y válido que cumple con todas las cotas requeridas "
    "para la redacción de artículos técnicos en la base de conocimiento de la empresa."
)


def _crear_sesion_revision_final(sid: str = "test-ef-rev") -> SesionChat:
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.REVISION_METADATOS,
        titulo="Configurar Punto de Venta en Ventas",
        texto=TEXTO_VALIDO,
        texto_limpio=TEXTO_VALIDO,
        texto_editor=TEXTO_VALIDO,
        texto_original=TEXTO_VALIDO,
        categoria_id=1,
        categoria_nombre="General",
        tags=["instructivo", "ventas"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta en Ventas",
            bloques_texto=[TEXTO_VALIDO],
            texto_base_limpio=TEXTO_VALIDO,
            texto_editor=TEXTO_VALIDO,
            texto_original=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            finalizado=False,
        ),
    )
    # Regla única de aceptación: solo valen las opciones que el back emitió en el turno anterior.
    sesion.ultimas_opciones = ["auditar", "continuar"]
    gestor_sesiones._sesiones[sid] = sesion
    return sesion


def _crear_sesion_edicion_final(sid: str = "test-ef-edit") -> SesionChat:
    sesion = SesionChat(
        session_id=sid,
        estado=EstadoFlujo.EDICION_FINAL,
        titulo="Configurar Punto de Venta en Ventas",
        texto=TEXTO_VALIDO,
        texto_limpio=TEXTO_VALIDO,
        texto_editor=TEXTO_VALIDO,
        texto_original=TEXTO_VALIDO,
        categoria_id=1,
        categoria_nombre="General",
        tags=["instructivo", "ventas"],
        borrador=BorradorSesion(
            modo="nuevo",
            titulo="Configurar Punto de Venta en Ventas",
            bloques_texto=[TEXTO_VALIDO],
            texto_base_limpio=TEXTO_VALIDO,
            texto_editor=TEXTO_VALIDO,
            texto_original=TEXTO_VALIDO,
            tipo_plantilla="instructivo",
            categoria_id=1,
            categoria_nombre="General",
            tags=["instructivo", "ventas"],
            finalizado=False,
        ),
    )
    sesion.ultimas_opciones = list(OPCIONES_EDICION_FINAL)
    gestor_sesiones._sesiones[sid] = sesion
    return sesion


@pytest.mark.anyio
async def test_1_continuar_desde_revision_final_lleva_a_edicion_final():
    """1. En revisión final (revision_intermedia == False), Continuar ya no finaliza:
    lleva al nuevo estado EDICION_FINAL."""
    sesion = _crear_sesion_revision_final("test-cont-ef")
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="continuar")
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert sesion.estado == EstadoFlujo.EDICION_FINAL
    assert resp.opciones == OPCIONES_EDICION_FINAL
    assert resp.mensaje == MSG_EDICION_FINAL
    assert resp.borrador.finalizado is False


@pytest.mark.anyio
async def test_2_edicion_final_sin_volver():
    """2. EDICION_FINAL muestra solo Finalizar (los estados de revisión no ofrecen Volver)
    y una acción `volver` se rechaza sin cambiar de estado."""
    sesion = _crear_sesion_revision_final("test-volver-ef")
    buscador = MagicMock(spec=BuscadorDuplicados)

    resp = await manejar_turno(
        ChatOrquestadorRequest(session_id=sesion.session_id, accion="continuar"), buscador
    )
    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.opciones == OPCIONES_EDICION_FINAL
    assert resp.navegacion == []

    resp = await manejar_turno(
        ChatOrquestadorRequest(session_id=sesion.session_id, accion="volver"), buscador
    )
    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert sesion.estado == EstadoFlujo.EDICION_FINAL


@pytest.mark.anyio
async def test_3_solo_finalizar_de_edicion_final_llama_registrar_finalizado():
    """3. Solo Finalizar de EDICION_FINAL llama a _registrar_finalizado."""
    sesion = _crear_sesion_edicion_final("test-fin-ef")
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="finalizar")
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.FINALIZADO
    assert sesion.estado == EstadoFlujo.FINALIZADO
    assert resp.borrador.finalizado is True


@pytest.mark.anyio
async def test_3_eliminar_manejo_finalizar_en_handle_revision_borrador():
    """3. Finalizar en handle_revision_borrador ya no se maneja ni finaliza."""
    sesion = _crear_sesion_revision_final("test-fin-rev-ignorado")
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="finalizar")
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_METADATOS
    assert sesion.estado == EstadoFlujo.REVISION_METADATOS
    assert resp.borrador.finalizado is False


async def _pedir_cambio_plantilla(sesion, buscador, agente, **campos):
    req = ChatOrquestadorRequest(session_id=sesion.session_id, tipo_plantilla="soluciones", **campos)
    req._baco_agent = agente
    return await manejar_turno(req, buscador)


async def _accion(sesion, buscador, agente, accion):
    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion=accion)
    req._baco_agent = agente
    return await manejar_turno(req, buscador)


@pytest.mark.anyio
async def test_4_cambio_plantilla_pide_confirmacion_y_al_confirmar_reaplica_desde_texto_original():
    """4. En EDICION_FINAL el cambio de tipo queda pendiente hasta confirmar; al confirmar se reaplica la skill."""
    sesion = _crear_sesion_edicion_final("test-reaplicar-ef")
    sesion.texto_original = "Texto original base para skill"
    sesion.borrador.texto_original = "Texto original base para skill"
    sesion.borrador.bloques_texto = ["## Pasos\n1. Formato anterior de plantilla instructivo"]
    sesion.borrador.skill_aplicada = "plantilla"
    sesion.skill_aplicada = "plantilla"
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## Solución\nNueva plantilla aplicada desde texto_original")

    resp = await _pedir_cambio_plantilla(sesion, buscador, mock_agente)
    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.opciones == OPCIONES_CONFIRMAR_PLANTILLA
    assert "CUIDADO" in resp.mensaje
    assert resp.borrador.tipo_plantilla == "instructivo"
    assert sesion.plantilla_pendiente == "soluciones"
    mock_agente.assert_not_called()

    resp = await _accion(sesion, buscador, mock_agente, "confirmar_plantilla")
    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.borrador.tipo_plantilla == "soluciones"
    assert "Nueva plantilla aplicada desde texto_original" in resp.borrador.bloques_texto[0]
    # Opción A: lo editado (texto vigente) pasa a ser el nuevo original.
    assert "Formato anterior de plantilla instructivo" in mock_agente.call_args[0][0]
    assert resp.opciones == OPCIONES_EDICION_FINAL
    assert sesion.plantilla_pendiente is None


@pytest.mark.anyio
async def test_4_cancelar_cambio_plantilla_deja_todo_igual():
    sesion = _crear_sesion_edicion_final("test-cancelar-plantilla")
    bloques_previos = list(sesion.borrador.bloques_texto)
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## No debería usarse")

    await _pedir_cambio_plantilla(sesion, buscador, mock_agente)
    resp = await _accion(sesion, buscador, mock_agente, "cancelar_plantilla")

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.borrador.tipo_plantilla == "instructivo"
    assert resp.borrador.bloques_texto == bloques_previos
    assert resp.opciones == OPCIONES_EDICION_FINAL
    assert sesion.plantilla_pendiente is None
    mock_agente.assert_not_called()


@pytest.mark.anyio
async def test_4_finalizar_con_cambio_plantilla_no_finaliza_sin_confirmar():
    sesion = _crear_sesion_edicion_final("test-finalizar-con-cambio")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## No debería usarse")

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="finalizar", tipo_plantilla="soluciones")
    req._baco_agent = mock_agente
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.opciones == OPCIONES_CONFIRMAR_PLANTILLA
    assert resp.borrador.finalizado is False
    mock_agente.assert_not_called()


@pytest.mark.anyio
async def test_4_texto_editado_junto_al_cambio_se_aplica_y_es_el_nuevo_original():
    """4. El texto editado en el mismo turno se aplica ya; al confirmar, la skill parte de él."""
    sesion = _crear_sesion_edicion_final("test-edit-luego-skill")
    sesion.borrador.skill_aplicada = "plantilla"
    sesion.skill_aplicada = "plantilla"
    buscador = MagicMock(spec=BuscadorDuplicados)
    texto_editado = "Nuevo texto editado por el usuario en el Editor con suficientes caracteres válidos."
    mock_agente = MagicMock(return_value="## Resultado con nuevo original")

    await _pedir_cambio_plantilla(sesion, buscador, mock_agente, texto=texto_editado)
    assert sesion.texto_original == texto_editado
    resp = await _accion(sesion, buscador, mock_agente, "confirmar_plantilla")

    assert sesion.texto_original == texto_editado
    assert texto_editado in mock_agente.call_args[0][0]
    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.opciones == OPCIONES_EDICION_FINAL


@pytest.mark.anyio
async def test_4_sin_texto_original_reaplica_desde_el_editor():
    """4. Sin texto_original (p. ej. artículo enriquecido) no se corta: se reaplica desde el Editor."""
    sesion = _crear_sesion_edicion_final("test-sin-texto-orig")
    sesion.texto_original = None
    sesion.borrador.texto_original = None
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## Resultado desde el Editor")

    await _pedir_cambio_plantilla(sesion, buscador, mock_agente)
    resp = await _accion(sesion, buscador, mock_agente, "confirmar_plantilla")

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.borrador.tipo_plantilla == "soluciones"
    assert "Resultado desde el Editor" in resp.borrador.bloques_texto[0]
    mock_agente.assert_called_once()


@pytest.mark.anyio
async def test_5_editar_titulo_no_dispara_busqueda_duplicados():
    """5. Editar el título no dispara búsqueda de duplicados."""
    sesion = _crear_sesion_edicion_final("test-edit-titulo-no-dedup")
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo="Nuevo Título Modificado en Edición Final",
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.borrador.titulo == "Nuevo Título Modificado en Edición Final"
    buscador.evaluar_titulo.assert_not_called()
    buscador.evaluar_texto.assert_not_called()
    assert resp.opciones == OPCIONES_EDICION_FINAL


# --- Bug: quitar/cambiar el tipo de plantilla desde las etiquetas (el front no envía tipo_plantilla) ---

async def _guardar_tags(sesion, buscador, agente, tags, **campos):
    req = ChatOrquestadorRequest(session_id=sesion.session_id, tags=tags, **campos)
    req._baco_agent = agente
    return await manejar_turno(req, buscador)


@pytest.mark.anyio
async def test_bug_quitar_plantilla_de_tags_avisa_obligatoria_y_guarda_lo_demas():
    sesion = _crear_sesion_edicion_final("test-bug-quitar-plantilla")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## No debería usarse")

    resp = await _guardar_tags(
        sesion, buscador, mock_agente, ["ventas", "facturacion"],
        titulo="Configurar Punto de Venta en Facturación",
    )

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert "obligatorio" in resp.mensaje
    assert resp.frenar_finalizar is True
    assert resp.borrador.tipo_plantilla == "instructivo"
    assert "instructivo" in resp.borrador.tags
    assert "facturacion" in [t.lower() for t in resp.borrador.tags]
    assert resp.borrador.titulo == "Configurar Punto de Venta en Facturación"
    assert sesion.plantilla_pendiente is None
    mock_agente.assert_not_called()


@pytest.mark.anyio
async def test_bug_dos_plantillas_en_tags_pide_elegir_una_sola():
    sesion = _crear_sesion_edicion_final("test-bug-dos-plantillas")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## No debería usarse")

    resp = await _guardar_tags(sesion, buscador, mock_agente, ["instructivo", "soluciones", "ventas"])

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert "uno solo" in resp.mensaje
    assert resp.frenar_finalizar is True
    assert resp.borrador.tipo_plantilla == "instructivo"
    assert "soluciones" not in resp.borrador.tags
    assert sesion.plantilla_pendiente is None
    mock_agente.assert_not_called()


@pytest.mark.anyio
async def test_bug_cambiar_plantilla_en_tags_pide_confirmacion():
    sesion = _crear_sesion_edicion_final("test-bug-cambio-tags")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## Consulta\nResultado soluciones")

    resp = await _guardar_tags(sesion, buscador, mock_agente, ["soluciones", "ventas"])
    assert resp.opciones == OPCIONES_CONFIRMAR_PLANTILLA
    assert "CUIDADO" in resp.mensaje
    assert resp.borrador.tipo_plantilla == "instructivo"
    assert sesion.plantilla_pendiente == "soluciones"
    mock_agente.assert_not_called()

    resp = await _accion(sesion, buscador, mock_agente, "confirmar_plantilla")
    assert resp.borrador.tipo_plantilla == "soluciones"
    assert "soluciones" in resp.borrador.tags and "instructivo" not in resp.borrador.tags
    assert "ventas" in resp.borrador.tags
    mock_agente.assert_called_once()


@pytest.mark.anyio
async def test_bug_tags_con_misma_plantilla_no_pide_confirmacion():
    sesion = _crear_sesion_edicion_final("test-bug-misma-plantilla")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## No debería usarse")

    resp = await _guardar_tags(sesion, buscador, mock_agente, ["instructivo", "ventas", "caja"])
    assert resp.opciones == OPCIONES_EDICION_FINAL
    assert resp.frenar_finalizar is False
    assert "caja" in [t.lower() for t in resp.borrador.tags]
    assert sesion.plantilla_pendiente is None
    mock_agente.assert_not_called()


@pytest.mark.anyio
async def test_bug_confirmar_limpia_estructura_de_plantilla_anterior():
    sesion = _crear_sesion_edicion_final("test-bug-limpieza")
    texto_con_plantilla = (
        "# ¿Para qué sirve?\n\n> Permite configurar el punto de venta para emitir comprobantes.\n\n"
        "## Antes de empezar\n\n### Configuraciones iniciales en el sistema\n\n"
        "- **[Nombre del maestro o componente]:** [Indicar la configuración requerida].\n\n"
        "## Modo de uso\n\n**Ruta:** Menú → Ventas → Puntos de venta\n\n"
        "1. Completar el número de punto de venta y guardar."
    )
    sesion.borrador.bloques_texto = [texto_con_plantilla]
    sesion.borrador.skill_aplicada = "plantilla"
    sesion.skill_aplicada = "plantilla"
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## Consulta\nResultado soluciones")

    await _guardar_tags(sesion, buscador, mock_agente, ["soluciones", "ventas"])
    await _accion(sesion, buscador, mock_agente, "confirmar_plantilla")

    prompt = mock_agente.call_args[0][0]
    # Solo el contenido del usuario: el prompt también trae la plantilla de referencia
    # (soluciones tiene su propia línea **Ruta:**) y las instrucciones nombran la etiqueta.
    apertura = "<borrador_contenido>\n"
    entrada = prompt[prompt.rindex(apertura) + len(apertura):prompt.rindex("</borrador_contenido>")]
    for estructura in ("¿Para qué sirve?", "Antes de empezar", "Modo de uso", "**Ruta:**",
                       "[Nombre del maestro o componente]", "Configuraciones iniciales"):
        assert estructura not in entrada
    assert "Permite configurar el punto de venta para emitir comprobantes." in entrada
    assert "Menú → Ventas → Puntos de venta" in entrada
    assert "Completar el número de punto de venta y guardar." in entrada


def test_limpiar_estructura_no_toca_texto_sin_plantilla():
    from baco.server.services.orquestador.edicion import (
        limpiar_estructura_plantilla,
        texto_tiene_estructura_plantilla,
    )
    texto = "## Pasos\n1. Abrir el módulo [opcional] y guardar."
    assert texto_tiene_estructura_plantilla(texto, "instructivo") is False
    assert limpiar_estructura_plantilla(texto, "instructivo") == texto


async def _mensaje(sesion, buscador, agente, texto):
    req = ChatOrquestadorRequest(session_id=sesion.session_id, mensaje=texto)
    req._baco_agent = agente
    return await manejar_turno(req, buscador)


@pytest.mark.anyio
@pytest.mark.parametrize("texto", ["soluciones", "instructivo"])
async def test_chat_tipo_plantilla_escrito_no_cambia_nada(texto):
    """En EDICION_FINAL el tipo de plantilla se cambia solo desde el panel (toggle):
    escribirlo en el chat no lo cambia ni lo deja pendiente."""
    sesion = _crear_sesion_edicion_final(f"test-chat-plantilla-{texto}")
    bloques_previos = list(sesion.borrador.bloques_texto)
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## No debería usarse")

    resp = await _mensaje(sesion, buscador, mock_agente, texto)
    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.mensaje == MSG_OPCION_NO_DISPONIBLE
    assert resp.borrador.tipo_plantilla == "instructivo"
    assert resp.borrador.bloques_texto == bloques_previos
    assert resp.plantilla_pendiente is None
    assert sesion.plantilla_pendiente is None
    mock_agente.assert_not_called()
