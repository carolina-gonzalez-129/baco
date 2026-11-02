import pytest
from unittest.mock import MagicMock

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.continuar import continuar_desde_revision
from baco.server.services.orquestador.mensajes import (
    MSG_EDICION_FINAL,
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
        estado=EstadoFlujo.REVISION_BORRADOR,
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
            revision_intermedia=False,
            finalizado=False,
        ),
    )
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
            revision_intermedia=False,
            finalizado=False,
        ),
    )
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
async def test_2_edicion_final_botones_y_volver_a_revision_final():
    """2. EDICION_FINAL muestra solo Finalizar y Volver. Volver regresa a revisión final."""
    sesion = _crear_sesion_edicion_final("test-volver-ef")
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="volver")
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.revision_intermedia is False


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

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert resp.borrador.finalizado is False


@pytest.mark.anyio
async def test_4_cambio_plantilla_con_skill_la_reaplica_automaticamente_desde_texto_original():
    """4. Si en EDICION_FINAL cambia el tipo de plantilla y había una skill aplicada,
    handlers.py la reaplica automáticamente desde texto_original."""
    sesion = _crear_sesion_edicion_final("test-reaplicar-ef")
    sesion.texto_original = "Texto original base para skill"
    sesion.borrador.texto_original = "Texto original base para skill"
    sesion.borrador.bloques_texto = ["## Pasos\n1. Formato anterior de plantilla instructivo"]
    sesion.borrador.skill_aplicada = "plantilla"
    sesion.skill_aplicada = "plantilla"

    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value="## Solución\nNueva plantilla aplicada desde texto_original")

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="soluciones",
    )
    req._baco_agent = mock_agente

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.borrador.tipo_plantilla == "soluciones"
    assert "Nueva plantilla aplicada desde texto_original" in resp.borrador.bloques_texto[0]
    assert resp.opciones == OPCIONES_EDICION_FINAL


@pytest.mark.anyio
async def test_4_texto_editado_despues_de_skill_es_nuevo_original():
    """4. Si el texto se editó después de aplicar la skill, ese texto editado es el nuevo original."""
    sesion = _crear_sesion_edicion_final("test-edit-luego-skill")
    sesion.borrador.skill_aplicada = "plantilla"
    sesion.skill_aplicada = "plantilla"
    buscador = MagicMock(spec=BuscadorDuplicados)

    texto_editado = "Nuevo texto editado por el usuario en el Editor con suficientes caracteres válidos."
    mock_agente = MagicMock(return_value="## Resultado con nuevo original")

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_editado,
        tipo_plantilla="soluciones",
    )
    req._baco_agent = mock_agente

    resp = await manejar_turno(req, buscador)

    assert sesion.texto_original == texto_editado
    assert sesion.borrador.texto_original == texto_editado
    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert resp.opciones == OPCIONES_EDICION_FINAL


@pytest.mark.anyio
async def test_4_sin_texto_original_no_lo_crea_y_se_detiene():
    """4. Si texto_original no existe en la sesión, no lo crees: detenete y reportalo."""
    sesion = _crear_sesion_edicion_final("test-sin-texto-orig")
    sesion.texto_original = None
    sesion.borrador.texto_original = None
    sesion.borrador.skill_aplicada = "plantilla"

    buscador = MagicMock(spec=BuscadorDuplicados)
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="soluciones",
    )

    with pytest.raises(ValueError, match="texto_original no existe en la sesión"):
        await manejar_turno(req, buscador)

    assert sesion.texto_original is None


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
