import json
from unittest.mock import MagicMock

import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.sesion import gestor_sesiones
from baco.server.services.orquestador.validaciones import validar_borrador

TEXTO_ORIGINAL_USUARIO = (
    "### Pasos de Configuración\n\n"
    "1. Abrir el menú principal de Ventas y seleccionar Facturación.\n"
    "2. Completar los parámetros del punto de venta electrónico.\n\n"
    "### Consideraciones\n\n"
    "Se requiere perfil de administrador activo para guardar los cambios."
)

TEXTO_CON_MARCADOR = (
    "### Pasos de Configuración\n\n"
    "1. Ingresar al módulo de Ventas y abrir Facturación.\n"
    "2. Configurar la ruta del sistema en [Indicar ruta].\n"
    "3. Confirmar y guardar la parametrización.\n\n"
    "### Consideraciones\n\n"
    "El operador debe contar con permisos de administrador activo."
)

TEXTO_SIN_MARCADOR = (
    "### Pasos de Configuración\n\n"
    "1. Ingresar al módulo de Ventas y abrir Facturación.\n"
    "2. Configurar la ruta del sistema en C:\\Finnegans\\Config.\n"
    "3. Confirmar y guardar la parametrización.\n\n"
    "### Consideraciones\n\n"
    "El operador debe contar con permisos de administrador activo."
)


@pytest.mark.anyio
async def test_bug_marcadores_revision_tipo():
    # 1) Armar una sesión en REVISION_TIPO con resultado de skill visible cuyo texto tenga "[Indicar ruta]"
    sid = "test-bug-marcadores-sesion"
    gestor_sesiones.eliminar(sid)
    sesion, _, _ = gestor_sesiones.obtener_o_crear(sid)
    sesion.session_id = sid
    gestor_sesiones.sesiones[sid] = sesion
    sesion.estado = EstadoFlujo.REVISION_TIPO
    sesion.titulo = "Cómo Configurar Facturación Electrónica en Ventas"
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=sesion.titulo,
        bloques_texto=[TEXTO_ORIGINAL_USUARIO],
        tipo_plantilla="instructivo",
        tags=["instructivo"],
    )
    sesion.bloques_texto = [TEXTO_ORIGINAL_USUARIO]
    sesion.texto_limpio = TEXTO_ORIGINAL_USUARIO
    sesion.texto = TEXTO_ORIGINAL_USUARIO
    sesion.ultimas_opciones = ["aplicar_plantilla", "continuar"]
    validar_borrador(sesion)

    buscador = MagicMock(spec=BuscadorDuplicados)
    mock_agente = MagicMock(return_value=TEXTO_CON_MARCADOR)

    # Aplicar la skill de plantilla para dejar el resultado visible
    req_skill = ChatOrquestadorRequest(session_id=sid, accion="aplicar_plantilla")
    req_skill._baco_agent = mock_agente
    resp_skill = await manejar_turno(req_skill, buscador)
    assert resp_skill.borrador.resultado_skill_pendiente is True
    assert "[Indicar ruta]" in resp_skill.texto_limpio

    # 2) Simular el Continuar que bloquea
    req_cont = ChatOrquestadorRequest(session_id=sid, accion="continuar")
    resp_bloquea = await manejar_turno(req_cont, buscador)
    assert resp_bloquea.validacion is not None
    assert resp_bloquea.validacion.valido is False
    bloqueantes = [
        f for f in resp_bloquea.validacion.findings
        if (getattr(f, "severity", None) or (f.get("severity") if isinstance(f, dict) else None)) == "Bloqueante"
    ]
    assert any("[Indicar" in (getattr(f, "description", "") or "") for f in bloqueantes)

    # 3) Enviar un turno sin accion con `texto` = el mismo texto con el marcador reemplazado por un valor
    req_guardar = ChatOrquestadorRequest(session_id=sid, texto=TEXTO_SIN_MARCADOR)
    resp_guardar = await manejar_turno(req_guardar, buscador)

    # 4) Verifique que la respuesta tenga "continuar" en opciones Y que la respuesta SERIALIZADA (JSON)
    #    traiga `validacion.findings` SIN el hallazgo de marcadores pendientes.
    resp_json = json.loads(resp_guardar.model_dump_json())

    fallos = []
    if "continuar" not in resp_guardar.opciones:
        fallos.append(f"- 'continuar' no está en opciones: {resp_guardar.opciones}")

    val_json = resp_json.get("validacion")
    if val_json is None:
        fallos.append("- 'validacion' es None en la respuesta JSON serializada")
    else:
        findings = val_json.get("findings", [])
        findings_marcadores = [
            f for f in findings
            if "[Indicar" in f.get("description", "") or "marcadores" in f.get("description", "").lower()
        ]
        if findings_marcadores:
            fallos.append(f"- validacion.findings sigue conteniendo marcadores pendientes: {findings_marcadores}")

    assert not fallos, "Fallo en validación post-guardado:\n" + "\n".join(fallos)
