from unittest.mock import MagicMock
import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.edicion import ejecutar_skill
from baco.server.services.orquestador.sesion import SesionChat, gestor_sesiones
from baco.server.services.orquestador.validaciones import validar_borrador


TEXTO_ORIGINAL_USUARIO = (
    "### Pasos de Configuración\n\n"
    "1. Abrir el menú principal de Ventas y seleccionar Facturación.\n"
    "2. Completar los parámetros del punto de venta electrónico.\n\n"
    "### Consideraciones\n\n"
    "Se requiere perfil de administrador activo para guardar los cambios."
)

RESULTADO_SKILL_PLANTILLA = (
    "### Pasos de Configuración\n\n"
    "1. Ingresar al módulo de Ventas y abrir Facturación.\n"
    "2. Configurar el punto de venta electrónico en Finnegans.\n"
    "3. Confirmar y guardar la parametrización.\n\n"
    "### Consideraciones\n\n"
    "El operador debe contar con permisos de administrador activo."
)

RESULTADO_SKILL_AUDITOR_RAW = (
    "Dictamen: El artículo cumple con las pautas editoriales.\n\n"
    "<<<VERSION_CORREGIDA>>>\n"
    "### Pasos de Configuración Auditados\n\n"
    "1. Ingresar al módulo de Ventas y seleccionar Facturación.\n"
    "2. Parametrizar el punto de venta electrónico en el sistema.\n"
    "3. Guardar y verificar los cambios aplicados.\n\n"
    "### Consideraciones\n\n"
    "Es indispensable contar con permisos de administrador activo.\n"
    "<<<FIN_VERSION>>>"
)

RESULTADO_SKILL_AUDITOR_LIMPIO = (
    "### Pasos de Configuración Auditados\n\n"
    "1. Ingresar al módulo de Ventas y seleccionar Facturación.\n"
    "2. Parametrizar el punto de venta electrónico en el sistema.\n"
    "3. Guardar y verificar los cambios aplicados.\n\n"
    "### Consideraciones\n\n"
    "Es indispensable contar con permisos de administrador activo."
)


def _crear_sesion_plantilla_validada(sid: str) -> SesionChat:
    gestor_sesiones.eliminar(sid)
    sesion, _, _ = gestor_sesiones.obtener_o_crear(sid)
    sesion.session_id = sid
    gestor_sesiones.sesiones[sid] = sesion
    sesion.estado = EstadoFlujo.REVISION_BORRADOR
    sesion.titulo = "Cómo Configurar Facturación Electrónica en Ventas"
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=sesion.titulo,
        bloques_texto=[TEXTO_ORIGINAL_USUARIO],
        tipo_plantilla="instructivo",
        tags=["instructivo"],
        revision_intermedia=True,
    )
    sesion.bloques_texto = [TEXTO_ORIGINAL_USUARIO]
    sesion.texto_limpio = TEXTO_ORIGINAL_USUARIO
    sesion.texto = TEXTO_ORIGINAL_USUARIO
    validar_borrador(sesion)
    return sesion


def _crear_sesion_revision_final(sid: str, texto_inicial: str = TEXTO_ORIGINAL_USUARIO) -> SesionChat:
    gestor_sesiones.eliminar(sid)
    sesion, _, _ = gestor_sesiones.obtener_o_crear(sid)
    sesion.session_id = sid
    gestor_sesiones.sesiones[sid] = sesion
    sesion.estado = EstadoFlujo.REVISION_BORRADOR
    sesion.titulo = "Cómo Configurar Facturación Electrónica en Ventas"
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=sesion.titulo,
        bloques_texto=[texto_inicial],
        tipo_plantilla="instructivo",
        categoria_id=20,
        categoria_nombre="Ventas",
        tags=["instructivo", "ventas"],
        revision_intermedia=False,
    )
    sesion.bloques_texto = [texto_inicial]
    sesion.texto_limpio = texto_inicial
    sesion.texto = texto_inicial
    sesion.categoria_id = 20
    sesion.categoria_nombre = "Ventas"
    sesion.tags = ["instructivo", "ventas"]
    validar_borrador(sesion)
    return sesion


@pytest.mark.anyio
async def test_plantillas_separa_texto_original_y_resultado_y_ofrece_solo_continuar_y_volver():
    """Al aplicar la skill de plantillas:
    - La respuesta incluye el texto original para el Editor y el resultado de la skill
      para la Vista previa como campos separados.
    - Ofrece únicamente 'Continuar' y 'Volver'.
    """
    sesion = _crear_sesion_plantilla_validada("test-plantilla-campos-y-botones")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=RESULTADO_SKILL_PLANTILLA)

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req._baco_agent = mock_agente
    resp = await manejar_turno(req, buscador)

    # Campos separados para Editor (texto_original / texto_editor) y Vista previa (texto_limpio / bloques_texto)
    assert resp.texto_original == TEXTO_ORIGINAL_USUARIO
    assert resp.texto_editor == TEXTO_ORIGINAL_USUARIO
    assert resp.borrador.texto_original == TEXTO_ORIGINAL_USUARIO
    assert resp.borrador.texto_editor == TEXTO_ORIGINAL_USUARIO

    assert resp.texto_limpio == RESULTADO_SKILL_PLANTILLA
    assert resp.borrador.texto_limpio == RESULTADO_SKILL_PLANTILLA
    assert resp.borrador.bloques_texto == [RESULTADO_SKILL_PLANTILLA]
    assert resp.texto_original != resp.texto_limpio

    # Únicamente "Continuar" y "Volver"
    labels = [b.label for b in resp.botones]
    assert labels == ["Continuar", "Volver"]
    assert resp.opciones == ["continuar_revision", "volver"]


@pytest.mark.anyio
async def test_plantillas_continuar_adopta_resultado_como_texto_vigente_y_avanza():
    """Al tocar 'Continuar' luego de aplicar plantillas, adopta el resultado de la skill
    como texto vigente y avanza de etapa.
    """
    sesion = _crear_sesion_plantilla_validada("test-plantilla-continuar-adopta")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=RESULTADO_SKILL_PLANTILLA)

    req_skill = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req_skill._baco_agent = mock_agente
    await manejar_turno(req_skill, buscador)

    req_cont = ChatOrquestadorRequest(session_id=sesion.session_id, accion="continuar_revision")
    resp_cont = await manejar_turno(req_cont, buscador)

    assert resp_cont.estado == EstadoFlujo.ESPERANDO_METADATOS
    # El resultado de la skill fue adoptado como texto vigente en borrador, sesión y respuesta
    assert resp_cont.texto_limpio == RESULTADO_SKILL_PLANTILLA
    assert resp_cont.texto_original == RESULTADO_SKILL_PLANTILLA
    assert resp_cont.borrador.texto_limpio == RESULTADO_SKILL_PLANTILLA
    assert resp_cont.borrador.bloques_texto == [RESULTADO_SKILL_PLANTILLA]
    assert resp_cont.borrador.texto_original == RESULTADO_SKILL_PLANTILLA
    assert resp_cont.borrador.texto_editor == RESULTADO_SKILL_PLANTILLA
    assert sesion.texto_limpio == RESULTADO_SKILL_PLANTILLA
    assert sesion.texto_original == RESULTADO_SKILL_PLANTILLA
    assert sesion.texto_editor == RESULTADO_SKILL_PLANTILLA
    assert resp_cont.borrador.resultado_skill_pendiente is False
    assert resp_cont.borrador.skill_pendiente is None


@pytest.mark.anyio
async def test_plantillas_volver_descarta_resultado_y_conserva_texto_original():
    """Al tocar 'Volver' luego de aplicar plantillas, descarta el resultado de la skill
    y conserva el texto_original.
    """
    sesion = _crear_sesion_plantilla_validada("test-plantilla-volver-descarta")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=RESULTADO_SKILL_PLANTILLA)

    req_skill = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req_skill._baco_agent = mock_agente
    await manejar_turno(req_skill, buscador)

    req_volver = ChatOrquestadorRequest(session_id=sesion.session_id, accion="volver")
    resp_volver = await manejar_turno(req_volver, buscador)

    assert resp_volver.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    # El resultado de la skill se descartó y se conservó texto_original
    assert resp_volver.texto_limpio == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.texto_original == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.borrador.texto_limpio == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.borrador.bloques_texto == [TEXTO_ORIGINAL_USUARIO]
    assert resp_volver.borrador.texto_original == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.borrador.texto_editor == TEXTO_ORIGINAL_USUARIO
    assert sesion.texto_limpio == TEXTO_ORIGINAL_USUARIO
    assert sesion.texto_original == TEXTO_ORIGINAL_USUARIO
    assert sesion.texto_editor == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.borrador.resultado_skill_pendiente is False
    assert resp_volver.borrador.skill_pendiente is None


@pytest.mark.anyio
async def test_auditor_funciona_exactamente_igual_campos_separados_y_botones():
    """Al aplicar la skill auditor:
    - La respuesta incluye el texto original para el Editor y el resultado de la skill
      para la Vista previa como campos separados.
    - Ofrece únicamente 'Continuar' y 'Volver'.
    """
    sesion = _crear_sesion_revision_final("test-auditor-campos-y-botones")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=RESULTADO_SKILL_AUDITOR_RAW)

    req = ChatOrquestadorRequest(session_id=sesion.session_id, accion="auditar")
    req._baco_agent = mock_agente
    resp = await manejar_turno(req, buscador)

    # Campos separados para Editor (texto_original / texto_editor) y Vista previa (texto_limpio / bloques_texto)
    assert resp.texto_original == TEXTO_ORIGINAL_USUARIO
    assert resp.texto_editor == TEXTO_ORIGINAL_USUARIO
    assert resp.borrador.texto_original == TEXTO_ORIGINAL_USUARIO
    assert resp.borrador.texto_editor == TEXTO_ORIGINAL_USUARIO

    assert resp.texto_limpio == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert resp.borrador.texto_limpio == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert resp.borrador.bloques_texto == [RESULTADO_SKILL_AUDITOR_LIMPIO]
    assert resp.texto_original != resp.texto_limpio

    # Únicamente "Continuar" y "Volver"
    labels = [b.label for b in resp.botones]
    assert labels == ["Continuar", "Volver"]
    assert resp.opciones == ["continuar", "volver"]


@pytest.mark.anyio
async def test_auditor_continuar_adopta_resultado_como_texto_vigente_y_avanza():
    """Al tocar 'Continuar' luego de aplicar auditor, adopta el resultado de la skill
    como texto vigente y avanza a FINALIZADO.
    """
    sesion = _crear_sesion_revision_final("test-auditor-continuar-adopta")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=RESULTADO_SKILL_AUDITOR_RAW)

    req_skill = ChatOrquestadorRequest(session_id=sesion.session_id, accion="auditar")
    req_skill._baco_agent = mock_agente
    await manejar_turno(req_skill, buscador)

    req_cont = ChatOrquestadorRequest(session_id=sesion.session_id, accion="continuar")
    resp_cont = await manejar_turno(req_cont, buscador)

    assert resp_cont.estado == EstadoFlujo.FINALIZADO
    assert resp_cont.borrador.finalizado is True
    # El resultado del auditor fue adoptado como texto vigente
    assert resp_cont.texto_limpio == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert resp_cont.texto_original == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert resp_cont.borrador.texto_limpio == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert resp_cont.borrador.bloques_texto == [RESULTADO_SKILL_AUDITOR_LIMPIO]
    assert resp_cont.borrador.texto_original == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert resp_cont.borrador.texto_editor == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert sesion.texto_limpio == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert sesion.texto_original == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert sesion.texto_editor == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert resp_cont.borrador.resultado_skill_pendiente is False
    assert resp_cont.borrador.skill_pendiente is None


@pytest.mark.anyio
async def test_auditor_volver_descarta_resultado_y_conserva_texto_original():
    """Al tocar 'Volver' luego de aplicar auditor, descarta el resultado de la skill
    y conserva el texto_original.
    """
    sesion = _crear_sesion_revision_final("test-auditor-volver-descarta")
    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=RESULTADO_SKILL_AUDITOR_RAW)

    req_skill = ChatOrquestadorRequest(session_id=sesion.session_id, accion="auditar")
    req_skill._baco_agent = mock_agente
    await manejar_turno(req_skill, buscador)

    req_volver = ChatOrquestadorRequest(session_id=sesion.session_id, accion="volver")
    resp_volver = await manejar_turno(req_volver, buscador)

    assert resp_volver.estado == EstadoFlujo.ESPERANDO_METADATOS
    # El resultado del auditor se descartó y se conservó texto_original
    assert resp_volver.texto_limpio == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.texto_original == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.borrador.texto_limpio == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.borrador.bloques_texto == [TEXTO_ORIGINAL_USUARIO]
    assert resp_volver.borrador.texto_original == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.borrador.texto_editor == TEXTO_ORIGINAL_USUARIO
    assert sesion.texto_limpio == TEXTO_ORIGINAL_USUARIO
    assert sesion.texto_original == TEXTO_ORIGINAL_USUARIO
    assert sesion.texto_editor == TEXTO_ORIGINAL_USUARIO
    assert resp_volver.borrador.resultado_skill_pendiente is False
    assert resp_volver.borrador.skill_pendiente is None


@pytest.mark.anyio
async def test_secuencia_plantilla_continuar_y_luego_auditor_usa_texto_vigente():
    """Si se aplica plantilla y se elige 'Continuar' (adoptando el resultado como texto vigente),
    al aplicar luego 'auditor' el texto_original para esa segunda skill es el texto adoptado de la plantilla.
    """
    sesion = _crear_sesion_plantilla_validada("test-secuencia-plantilla-auditor")
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. Aplicar plantilla y Continuar
    req_pl = ChatOrquestadorRequest(session_id=sesion.session_id, accion="aplicar_plantilla")
    req_pl._baco_agent = MagicMock(return_value=RESULTADO_SKILL_PLANTILLA)
    await manejar_turno(req_pl, buscador)

    req_cont_pl = ChatOrquestadorRequest(session_id=sesion.session_id, accion="continuar_revision")
    await manejar_turno(req_cont_pl, buscador)

    # 2. Completar metadatos para pasar a revisión final
    req_meta = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=20,
        tags=["instructivo", "ventas"],
    )
    resp_meta = await manejar_turno(req_meta, buscador)
    assert resp_meta.estado == EstadoFlujo.REVISION_BORRADOR

    # 3. Aplicar auditor: debe auditar RESULTADO_SKILL_PLANTILLA (el texto vigente adoptado)
    mock_auditor = MagicMock(return_value=RESULTADO_SKILL_AUDITOR_RAW)
    req_aud = ChatOrquestadorRequest(session_id=sesion.session_id, accion="auditar")
    req_aud._baco_agent = mock_auditor
    resp_aud = await manejar_turno(req_aud, buscador)

    prompt_auditor = mock_auditor.call_args[0][0]
    assert RESULTADO_SKILL_PLANTILLA in prompt_auditor
    assert resp_aud.texto_original == RESULTADO_SKILL_PLANTILLA
    assert resp_aud.borrador.texto_original == RESULTADO_SKILL_PLANTILLA
    assert resp_aud.borrador.texto_editor == RESULTADO_SKILL_PLANTILLA
    assert resp_aud.texto_limpio == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert resp_aud.borrador.texto_limpio == RESULTADO_SKILL_AUDITOR_LIMPIO
    assert [b.label for b in resp_aud.botones] == ["Continuar", "Volver"]
