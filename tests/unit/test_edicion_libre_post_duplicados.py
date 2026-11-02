import pytest
from unittest.mock import MagicMock, patch

from baco.server.config_limites import (
    TEXTO_MAX,
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador import manejar_turno
from baco.server.services.orquestador.edicion import (
    ESTADOS_EDICION_LIBRE,
    aplicar_edicion_campos,
    procesar_edicion_texto,
    procesar_edicion_titulo,
)
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos


TITULO_VALIDO = "Cómo configurar el punto de venta electrónico AFIP"
TEXTO_VALIDO = (
    "Para configurar el punto de venta electrónico en el sistema Finnegans ERP es necesario ingresar "
    "al maestro de puntos de venta dentro del módulo de Ventas, asociar el certificado digital vigente "
    "otorgado por AFIP y verificar que el tipo de emisión esté habilitado para comprobantes electrónicos."
)


@pytest.fixture(autouse=True)
def limpiar_estado():
    SESIONES.clear()
    limpiar_cache_catalogos()
    yield
    SESIONES.clear()
    limpiar_cache_catalogos()


def test_estados_edicion_libre_constante():
    assert ESTADOS_EDICION_LIBRE == {
        EstadoFlujo.ESPERANDO_PLANTILLA,
        EstadoFlujo.ESPERANDO_METADATOS,
        EstadoFlujo.REVISION_BORRADOR,
        EstadoFlujo.SUBSANANDO_BORRADOR,
    }


def _crear_sesion_en_estado(estado: EstadoFlujo, session_id: str = "test-edicion") -> SesionChat:
    sesion = SesionChat(
        session_id=session_id,
        estado=estado,
        titulo=TITULO_VALIDO,
        texto_limpio=TEXTO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        ultimas_opciones=["instructivo", "soluciones", "volver"] if estado == EstadoFlujo.ESPERANDO_PLANTILLA else ["volver"],
    )
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        texto_limpio=TEXTO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo" if estado in (EstadoFlujo.ESPERANDO_METADATOS, EstadoFlujo.REVISION_BORRADOR) else None,
    )
    SESIONES[session_id] = sesion
    return sesion


@pytest.mark.anyio
async def test_edicion_silenciosa_en_esperando_plantilla():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA)
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_titulo = "Configuración avanzada del punto de venta AFIP"
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=nuevo_titulo,
    )

    resp = await manejar_turno(req, buscador)

    # Estado no cambia
    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    # Mismas opciones
    assert resp.opciones == ["instructivo", "soluciones", "volver"]
    # Sin mensaje nuevo en el chat (silencioso)
    assert resp.mensaje == ""
    # Título actualizado
    assert resp.titulo == nuevo_titulo
    assert sesion.titulo == nuevo_titulo
    assert sesion.borrador.titulo == nuevo_titulo

    # Búsqueda de duplicados NUNCA se relanza
    buscador.evaluar_titulo.assert_not_called()
    buscador.evaluar_texto.assert_not_called()


@pytest.mark.anyio
async def test_edicion_silenciosa_en_esperando_metadatos():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS)
    sesion.ultimas_opciones = ["volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_texto = (
        "Texto modificado durante la etapa de metadatos. "
        "Verifica que el orquestador no intente parsear este texto como categorías o etiquetas temáticas."
    )
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=nuevo_texto,
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.opciones == ["volver"]
    assert resp.mensaje == ""
    assert resp.texto_limpio == nuevo_texto
    assert sesion.borrador.texto_limpio == nuevo_texto

    buscador.evaluar_titulo.assert_not_called()
    buscador.evaluar_texto.assert_not_called()


@pytest.mark.anyio
async def test_edicion_silenciosa_en_revision_borrador():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.ultimas_opciones = ["finalizar", "editar", "rechazar"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_texto = (
        "Texto editado en revisión de borrador. Debe actualizar silenciosamente sin mensaje en chat "
        "cuando viene sin opción ni acción."
    )
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=nuevo_texto,
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert resp.opciones == ["finalizar", "editar", "rechazar"]
    assert resp.mensaje == ""
    assert resp.texto_limpio == nuevo_texto
    assert sesion.borrador.texto_limpio == nuevo_texto


@pytest.mark.anyio
async def test_error_validacion_titulo_corto_no_cambia_estado():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA)
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo="Corto",  # < 15 caracteres
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert resp.opciones == ["instructivo", "soluciones", "volver"]
    assert f"{TITULO_MIN} caracteres" in resp.mensaje
    # Título original no se corrompe
    assert sesion.borrador.titulo == TITULO_VALIDO


@pytest.mark.anyio
async def test_error_validacion_texto_corto_no_cambia_estado():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS)
    sesion.ultimas_opciones = ["volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto="Muy breve",  # < 20 caracteres
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.opciones == ["volver"]
    assert f"{TEXTO_MIN} caracteres" in resp.mensaje
    assert sesion.borrador.texto_limpio == TEXTO_VALIDO


@pytest.mark.anyio
async def test_error_marcadores_prohibidos_en_texto():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA)
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=TEXTO_VALIDO + " [[R1]]",
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert resp.opciones == ["instructivo", "soluciones", "volver"]
    assert "marcadores no válidos" in resp.mensaje


@pytest.mark.anyio
async def test_solo_se_valida_el_campo_editado():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA)
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Si el texto de la sesión tuviese algún detalle o fuese ignorado, solo validamos el título editado
    nuevo_titulo = "Título completamente nuevo y válido para el artículo"
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=nuevo_titulo,
    )

    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert resp.titulo == nuevo_titulo
    assert resp.mensaje == ""


@pytest.mark.anyio
async def test_recalculo_skills_habilitadas():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.ultimas_opciones = ["volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Texto que supera TEXTO_MAX pero no TEXTO_MAX_PERCENTIL_99
    texto_largo = "Palabra " * ((TEXTO_MAX // 8) + 10)
    assert len(texto_largo) > TEXTO_MAX
    assert len(texto_largo) < TEXTO_MAX_PERCENTIL_99

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_largo,
    )

    resp = await manejar_turno(req, buscador)
    assert resp.skills_habilitadas is False
    assert sesion.borrador.skills_habilitadas is False


@pytest.mark.anyio
async def test_aviso_estructura_plantilla_con_marcador_indicar():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.ultimas_opciones = ["finalizar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    texto_con_indicar = TEXTO_VALIDO + " [Indicar configuración faltante]"
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_con_indicar,
    )

    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert resp.opciones == ["finalizar", "volver"]
    # Se muestra como aviso en el chat
    assert "Aviso sobre la estructura de la plantilla" in resp.mensaje
    assert "[Indicar...]" in resp.mensaje
    # Pero el texto quedó actualizado
    assert sesion.borrador.texto_limpio == texto_con_indicar


@pytest.mark.anyio
async def test_etapas_duplicados_no_usan_edicion_libre():
    # En ESPERANDO_TITULO, enviar mensaje dispara evaluar_titulo
    sesion = SesionChat(
        session_id="test-dup",
        estado=EstadoFlujo.ESPERANDO_TITULO,
    )
    SESIONES[sesion.session_id] = sesion
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.evaluar_titulo.return_value = None

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        mensaje="Configuración de Punto de Venta AFIP",
    )

    resp = await manejar_turno(req, buscador)
    buscador.evaluar_titulo.assert_called_once()
    assert resp.estado == EstadoFlujo.ESPERANDO_TEXTO


@pytest.mark.anyio
async def test_edicion_en_subsanando_borrador():
    sesion = _crear_sesion_en_estado(EstadoFlujo.SUBSANANDO_BORRADOR)
    sesion.ultimas_opciones = ["editar", "rechazar"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_texto = "Texto subsanado directamente sin mensajes ruidosos en el chat."
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=nuevo_texto,
    )

    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.SUBSANANDO_BORRADOR
    assert resp.opciones == ["editar", "rechazar"]
    assert resp.mensaje == ""
    assert resp.texto_limpio == nuevo_texto


@pytest.mark.anyio
async def test_edicion_simultanea_titulo_y_texto():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA)
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_tit = "Nuevo Título Válido para el Flujo"
    nuevo_txt = "Nuevo texto con longitud suficiente para superar el mínimo requerido por la regla."

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=nuevo_tit,
        texto=nuevo_txt,
    )

    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert resp.titulo == nuevo_tit
    assert resp.texto_limpio == nuevo_txt
    assert resp.mensaje == ""


@pytest.mark.anyio
async def test_edicion_con_opcion_sigue_flujo_normal():
    # En ESPERANDO_PLANTILLA, el usuario edita el título Y selecciona la plantilla "instructivo"
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA)
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_tit = "Título Editado Junto con Opción"
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=nuevo_tit,
        accion="instructivo",
    )

    resp = await manejar_turno(req, buscador)
    # Título se actualizó
    assert sesion.borrador.titulo == nuevo_tit
    # Y el flujo avanzó con la plantilla elegida
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert resp.estado in (EstadoFlujo.REVISION_BORRADOR, EstadoFlujo.ESPERANDO_METADATOS)



@pytest.mark.anyio
async def test_reenvio_mismo_texto_previo_sin_validacion_ni_mensaje():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.ultimas_opciones = ["continuar", "editar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Reenviar el mismo texto devuelto por el back en el turno previo
    texto_previo = sesion.borrador.texto_limpio
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_previo,
    )

    with patch(
        "baco.server.services.orquestador.coordinador.aplicar_edicion_campos",
        wraps=aplicar_edicion_campos,
    ) as spy_aplicar:
        resp = await manejar_turno(req, buscador)
        assert spy_aplicar.call_count == 1

    # Sin mensaje y con el mismo estado y opciones
    assert resp.mensaje == ""
    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert resp.opciones == ["continuar", "editar", "volver"]

    # También con saltos de línea Windows CRLF
    req_crlf = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_previo.replace("\n", "\r\n"),
    )
    with patch(
        "baco.server.services.orquestador.coordinador.aplicar_edicion_campos",
        wraps=aplicar_edicion_campos,
    ) as spy_aplicar:
        resp_crlf = await manejar_turno(req_crlf, buscador)
        assert spy_aplicar.call_count == 1
    assert resp_crlf.mensaje == ""


@pytest.mark.anyio
async def test_edicion_texto_con_opcion_continuar_procesa_una_sola_vez():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.borrador.revision_intermedia = True
    sesion.borrador.categoria_id = None
    sesion.borrador.tags = ["instructivo"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_texto = (
        "Nuevo texto con contenido técnico suficiente para pasar las validaciones mínimas "
        "en el estado de revisión intermedia sin violar ninguna cota o longitud requerida."
    )
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=nuevo_texto,
        accion="continuar",
    )

    with patch("baco.server.services.orquestador.handlers.procesar_edicion_texto") as mock_proc_handler:
        resp = await manejar_turno(req, buscador)
        # _aplicar_mutaciones_borrador NO debe volver a procesar el texto (0 llamadas desde el handler)
        mock_proc_handler.assert_not_called()

    # El texto fue aplicado correctamente
    assert sesion.borrador.texto_limpio == nuevo_texto
    # Y la opción continuar se ejecutó: avanzó a ESPERANDO_METADATOS
    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS


@pytest.mark.anyio
async def test_editar_con_resultado_pendiente_activa_flag_y_opcion_reaplicar():
    from baco.server.services.agente_service import ejecutar_skill_plantillas

    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.borrador.tipo_plantilla = "instructivo"
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. Aplicar la plantilla inicialmente
    baco_mock = MagicMock(return_value="### Paso 1\nConfigurar opciones iniciales del sistema Finnegans.")
    resultado_plantilla = ejecutar_skill_plantillas(sesion.session_id, sesion.borrador, baco_mock)
    assert "Paso 1" in resultado_plantilla
    assert "Paso 1" in sesion.borrador.texto_limpio
    assert sesion.borrador.resultado_skill_pendiente is True
    assert sesion.borrador.resultado_skill_desactualizado is False

    # 2. La persona edita el texto del Editor
    texto_editado_usuario = (
        "Texto personalizado por el usuario después de aplicar la plantilla con detalles "
        "operativos específicos de la empresa para la configuración."
    )
    req_edicion = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_editado_usuario,
    )
    resp_edicion = await manejar_turno(req_edicion, buscador)

    # No reaplica automáticamente y no borra el resultado de Vista previa
    assert "Paso 1" in resp_edicion.texto_limpio
    assert sesion.borrador.texto_editor == texto_editado_usuario

    # Flag activo
    assert sesion.borrador.resultado_skill_desactualizado is True
    assert sesion.borrador.skill_desactualizada is True

    # Aviso breve en el chat y opción Reaplicar agregada (Continuar y Volver se mantienen)
    assert "Editaste el texto, así que la versión de la Vista previa quedó desactualizada." in resp_edicion.mensaje
    assert "reaplicar" in resp_edicion.opciones
    assert "continuar" in resp_edicion.opciones
    assert "volver" in resp_edicion.opciones


@pytest.mark.anyio
async def test_reaplicar_ejecuta_skill_sobre_texto_editado_y_limpia_flag():
    from baco.server.services.agente_service import ejecutar_skill_plantillas

    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.borrador.tipo_plantilla = "instructivo"
    buscador = MagicMock(spec=BuscadorDuplicados)

    baco_mock = MagicMock(return_value="### Paso 1\nConfigurar opciones iniciales.")
    ejecutar_skill_plantillas(sesion.session_id, sesion.borrador, baco_mock)

    texto_editado_usuario = (
        "Texto personalizado por el usuario después de aplicar la plantilla con detalles "
        "operativos específicos de la empresa para la configuración."
    )
    req_edicion = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_editado_usuario,
    )
    await manejar_turno(req_edicion, buscador)
    assert sesion.borrador.resultado_skill_desactualizado is True

    # Usuario presiona "Reaplicar"
    prompt_recibido = None

    def baco_reaplicar(prompt):
        nonlocal prompt_recibido
        prompt_recibido = prompt
        return "### Paso 1 Reaplicado\nContenido actualizado con el nuevo texto del editor."

    req_reaplicar = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        accion="reaplicar",
    )
    setattr(req_reaplicar, "_baco_agent", baco_reaplicar)

    resp_reap = await manejar_turno(req_reaplicar, buscador)

    # Skill corre sobre el texto editado (nuevo original)
    assert prompt_recibido is not None
    assert texto_editado_usuario in prompt_recibido

    # Limpia el flag
    assert sesion.borrador.resultado_skill_desactualizado is False
    assert sesion.borrador.skill_desactualizada is False

    # No cambia el estado
    assert resp_reap.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR

    # Vista previa actualizada con el nuevo resultado
    assert "Paso 1 Reaplicado" in sesion.borrador.texto_limpio


@pytest.mark.anyio
async def test_editar_sin_resultado_pendiente_sin_aviso():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.borrador.resultado_skill_pendiente = False
    sesion.borrador.skill_pendiente = None
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_texto = (
        "Texto modificado normalmente en el editor sin ninguna skill previa ejecutada "
        "para el borrador actual en curso."
    )
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=nuevo_texto,
    )
    resp = await manejar_turno(req, buscador)

    # Sin aviso de skill desactualizada
    assert resp.mensaje == ""
    assert "reaplicar" not in resp.opciones
    assert sesion.borrador.resultado_skill_desactualizado is False


@pytest.mark.anyio
async def test_continuar_con_resultado_desactualizado_no_bloquea():
    from baco.server.services.agente_service import ejecutar_skill_plantillas

    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.borrador.tags = ["instructivo"]
    sesion.borrador.revision_intermedia = True
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. Aplicar skill y luego editar texto
    baco_mock = MagicMock(return_value="### Paso 1\nConfigurar opciones iniciales.")
    ejecutar_skill_plantillas(sesion.session_id, sesion.borrador, baco_mock)

    req_edit = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto="Texto con modificaciones adicionales en el editor que deja desactualizada la vista previa.",
    )
    await manejar_turno(req_edit, buscador)
    assert sesion.borrador.resultado_skill_desactualizado is True

    # 2. Usuario elige 'Continuar' con el resultado desactualizado
    req_cont = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        accion="continuar",
    )
    resp_cont = await manejar_turno(req_cont, buscador)

    # No se bloquea: avanza según la lógica de continuar (a ESPERANDO_METADATOS)
    assert resp_cont.estado == EstadoFlujo.ESPERANDO_METADATOS


@pytest.mark.anyio
async def test_continuar_desactualizado_usa_texto_editor():
    from baco.server.services.agente_service import ejecutar_skill_plantillas

    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.borrador.tags = ["instructivo"]
    sesion.borrador.revision_intermedia = True
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. Aplicar skill: resultado visible en Vista previa
    baco_mock = MagicMock(return_value="### Paso 1 Formato Plantilla\nContenido viejo de la plantilla.")
    ejecutar_skill_plantillas(sesion.session_id, sesion.borrador, baco_mock)
    assert sesion.borrador.resultado_skill_pendiente is True
    assert "Contenido viejo de la plantilla" in sesion.borrador.texto_limpio

    # 2. El usuario edita el texto en el editor
    texto_editado_usuario = (
        "Texto modificado manualmente por el usuario en el editor. "
        "Esta edición nunca debe perderse al continuar hacia metadatos o conformidad."
    )
    req_edit = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_editado_usuario,
    )
    await manejar_turno(req_edit, buscador)
    assert sesion.borrador.resultado_skill_desactualizado is True
    assert sesion.borrador.texto_editor == texto_editado_usuario
    # En este punto intermedio la vista previa aún conservaba el resultado viejo
    assert "Contenido viejo de la plantilla" in sesion.borrador.texto_limpio

    # 3. El usuario elige 'continuar'
    req_cont = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        accion="continuar",
    )
    resp_cont = await manejar_turno(req_cont, buscador)

    # Comportamiento esperado:
    # - Se usa b.texto_editor (lo editado), no b.bloques_texto viejo.
    # - Las ediciones nunca se pierden.
    # - Flags desactualizado y pendiente se resuelven / limpian.
    assert sesion.borrador.resultado_skill_desactualizado is False
    assert sesion.borrador.resultado_skill_pendiente is False
    assert sesion.borrador.skill_pendiente is None

    assert sesion.borrador.texto_limpio == texto_editado_usuario
    assert sesion.borrador.bloques_texto == [texto_editado_usuario]
    assert "Contenido viejo de la plantilla" not in sesion.borrador.texto_limpio
    assert resp_cont.texto_limpio == texto_editado_usuario
    assert resp_cont.estado == EstadoFlujo.ESPERANDO_METADATOS


@pytest.mark.anyio
async def test_reaplicar_sin_skill_pendiente_no_hace_nada():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.ultimas_opciones = ["finalizar", "editar", "rechazar"]
    texto_original = sesion.borrador.texto_limpio
    bloques_originales = list(sesion.borrador.bloques_texto)
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Caso 1: resultado_skill_pendiente es False y skill_pendiente es None
    sesion.borrador.resultado_skill_pendiente = False
    sesion.borrador.skill_pendiente = None

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        accion="reaplicar",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.texto_limpio == texto_original
    assert sesion.borrador.bloques_texto == bloques_originales
    assert resp.opciones == ["finalizar", "editar", "rechazar"]

    # Caso 2: resultado_skill_pendiente es True pero skill_pendiente es None
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.skill_pendiente = None

    resp2 = await manejar_turno(req, buscador)

    assert resp2.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.texto_limpio == texto_original
    assert sesion.borrador.bloques_texto == bloques_originales
    assert resp2.opciones == ["finalizar", "editar", "rechazar"]


def test_aplicar_plantilla_sin_edicion_previa_resultado_identico():
    from starlette.testclient import TestClient
    from baco.server.app.main import app
    from baco.server.app.dependencies import get_baco_agent, get_buscador_duplicados
    from baco.server.app.middleware import API_KEY

    sid = "test-plantilla-sin-edicion"
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id=sid)
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.borrador.texto_editor = None  # Sin edición previa

    mock_baco = MagicMock(return_value="## Instructivo Oficial\n\nTexto estructurado por plantilla.")
    mock_buscador = MagicMock()

    app.dependency_overrides[get_baco_agent] = lambda: mock_baco
    app.dependency_overrides[get_buscador_duplicados] = lambda: mock_buscador

    try:
        client = TestClient(app)
        client.headers.update({"X-API-Key": API_KEY, "X-Session-ID": sid})

        res = client.post("/chat/aplicar-plantilla")
        assert res.status_code == 200
        data = res.json()
        assert "Instructivo Oficial" in data["response"]
        prompt_enviado = mock_baco.call_args[0][0]
        assert TEXTO_VALIDO in prompt_enviado
        assert sesion.borrador.resultado_skill_pendiente is True
        assert sesion.borrador.resultado_skill_desactualizado is False
        assert sesion.borrador.skill_pendiente == "plantilla"
    finally:
        app.dependency_overrides.clear()


def test_auditar_semantica_sin_edicion_previa_resultado_identico():
    from starlette.testclient import TestClient
    from baco.server.app.main import app
    from baco.server.app.dependencies import get_baco_agent, get_buscador_duplicados
    from baco.server.app.middleware import API_KEY

    sid = "test-auditor-sin-edicion"
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id=sid)
    sesion.borrador.categoria_id = 1
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.borrador.texto_editor = ""  # Vacío / sin edición previa

    mock_baco = MagicMock(return_value="Dictamen: Coherente y correcto.\n<<<VERSION_CORREGIDA>>>\nTexto corregido final.\n<<<FIN_VERSION>>>")
    mock_buscador = MagicMock()

    app.dependency_overrides[get_baco_agent] = lambda: mock_baco
    app.dependency_overrides[get_buscador_duplicados] = lambda: mock_buscador

    try:
        client = TestClient(app)
        client.headers.update({"X-API-Key": API_KEY, "X-Session-ID": sid})

        res = client.post("/chat/auditar-semantica")
        assert res.status_code == 200
        data = res.json()
        assert "Coherente y correcto" in data["response"]
        assert data.get("texto_corregido") == "Texto corregido final."
        prompt_enviado = mock_baco.call_args[0][0]
        assert TEXTO_VALIDO in prompt_enviado
        assert sesion.borrador.resultado_skill_pendiente is True
        assert sesion.borrador.resultado_skill_desactualizado is False
        assert sesion.borrador.skill_pendiente == "auditor"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_continuar_con_tags_editados_quedan_guardados():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-tags-guardados")
    sesion.borrador.revision_intermedia = False
    sesion.borrador.categoria_id = 5
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevos_tags = ["instructivo", "facturacion", "afip"]
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=nuevos_tags,
        accion="continuar",
    )

    resp = await manejar_turno(req, buscador)

    # El estado avanza a FINALIZADO
    assert resp.estado == EstadoFlujo.FINALIZADO
    # Los tags editados quedaron guardados
    assert set(sesion.borrador.tags) == set(nuevos_tags)
    assert set(sesion.tags) == set(nuevos_tags)


@pytest.mark.anyio
async def test_continuar_sin_cambios_sin_avisos():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-sin-cambios")
    sesion.borrador.revision_intermedia = False
    sesion.borrador.categoria_id = 5
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Reenvía los mismos tags en orden distinto
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=["ventas", "instructivo"],
        categoria_id=5,
        accion="continuar",
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.FINALIZADO
    # Sin avisos adicionales en el mensaje
    assert "Aviso" not in resp.mensaje


@pytest.mark.anyio
async def test_cambio_solo_de_categoria_valida_solo_categoria():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-solo-cat")
    sesion.borrador.categoria_id = 5
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Categoría inválida que no existe en el catálogo
    req_invalida = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=999999,
        accion="continuar",
    )

    resp_inv = await manejar_turno(req_invalida, buscador)

    # No avanza y muestra error solo de la categoría
    assert resp_inv.estado == EstadoFlujo.REVISION_BORRADOR
    assert "La categoría '999999' no es válida o no existe" in resp_inv.mensaje
    assert "tags" not in resp_inv.mensaje.lower()

    # Categoría válida del catálogo (ej. 1 - General)
    req_valida = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        categoria_id=1,
    )
    resp_val = await manejar_turno(req_valida, buscador)
    assert resp_val.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.categoria_id == 1


@pytest.mark.anyio
async def test_continuar_con_tags_invalidos_en_revision_final_no_finaliza():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-tags-invalidos")
    sesion.borrador.revision_intermedia = False
    sesion.borrador.categoria_id = 5
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Intento de continuar con un único tag (menos de TAGS_MIN = 2)
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=["instructivo"],
        accion="continuar",
    )

    resp = await manejar_turno(req, buscador)

    # No avanza a finalizado
    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.estado == EstadoFlujo.REVISION_BORRADOR
    # Muestra el error
    assert "Se requieren al menos 2 tags o etiquetas" in resp.mensaje
    # Conserva las mismas opciones
    assert resp.opciones == ["auditar", "continuar", "volver"]
    # Verificación de que el borrador y la sesión no cambiaron (sin mutación parcial)
    assert sesion.borrador.tags == ["instructivo", "ventas"]
    assert sesion.tags == ["instructivo", "ventas"]
    assert sesion.borrador.finalizado is False


@pytest.mark.anyio
async def test_continuar_con_edicion_ejecuta_aplicar_edicion_campos_una_sola_vez():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-single-call")
    sesion.borrador.revision_intermedia = False
    sesion.borrador.categoria_id = 5
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=["instructivo", "ventas", "facturacion"],
        accion="continuar",
    )

    with patch(
        "baco.server.services.orquestador.coordinador.aplicar_edicion_campos",
        wraps=aplicar_edicion_campos,
    ) as spy_aplicar:
        resp = await manejar_turno(req, buscador)
        assert spy_aplicar.call_count == 1

    assert resp.estado == EstadoFlujo.FINALIZADO



@pytest.mark.anyio
async def test_editar_tags_en_esperando_metadatos_y_revision_borrador_quedan_guardados():
    # 1. En ESPERANDO_METADATOS
    sesion_meta = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS, session_id="test-tags-meta")
    sesion_meta.borrador.tags = ["instructivo"]
    sesion_meta.tags = ["instructivo"]
    sesion_meta.borrador.categoria_id = None
    sesion_meta.ultimas_opciones = ["volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req_meta = ChatOrquestadorRequest(
        session_id=sesion_meta.session_id,
        tags=["instructivo", "facturacion", "ventas"],
    )
    resp_meta = await manejar_turno(req_meta, buscador)
    assert resp_meta.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert set(sesion_meta.borrador.tags) == {"instructivo", "facturacion", "ventas"}
    assert set(sesion_meta.tags) == {"instructivo", "facturacion", "ventas"}

    # 2. En REVISION_BORRADOR
    sesion_rev = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-tags-rev")
    sesion_rev.borrador.categoria_id = 5
    sesion_rev.borrador.tags = ["instructivo", "ventas"]
    sesion_rev.tags = ["instructivo", "ventas"]
    sesion_rev.ultimas_opciones = ["auditar", "continuar", "volver"]

    req_rev = ChatOrquestadorRequest(
        session_id=sesion_rev.session_id,
        tags=["instructivo", "ventas", "afip"],
    )
    resp_rev = await manejar_turno(req_rev, buscador)
    assert resp_rev.estado == EstadoFlujo.REVISION_BORRADOR
    assert set(sesion_rev.borrador.tags) == {"instructivo", "ventas", "afip"}
    assert set(sesion_rev.tags) == {"instructivo", "ventas", "afip"}


@pytest.mark.anyio
async def test_edicion_pura_guarda_opciones_sugeridas_con_reaplicar_en_sesion():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-edicion-pura-opciones")
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.skill_pendiente = "plantilla"
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=TEXTO_VALIDO + "\n\nTexto adicional editado en editor.",
    )

    resp = await manejar_turno(req, buscador)
    assert "reaplicar" in resp.opciones
    assert "reaplicar" in sesion.ultimas_opciones
    assert sesion.ultimas_opciones == resp.opciones


@pytest.mark.anyio
async def test_cambio_plantilla_sin_skill_aplicada():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-plantilla-sin-skill")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.tags = ["instructivo", "ventas", "facturacion"]
    sesion.tags = ["instructivo", "ventas", "facturacion"]
    sesion.borrador.resultado_skill_pendiente = False
    sesion.borrador.resultado_skill_desactualizado = False
    sesion.borrador.skill_pendiente = None
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="soluciones",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.tipo_plantilla == "soluciones"
    assert sesion.tipo_plantilla == "soluciones"
    assert sesion.borrador.tags == ["soluciones", "ventas", "facturacion"]
    assert sesion.tags == ["soluciones", "ventas", "facturacion"]
    assert "reaplicar" not in resp.opciones
    assert sesion.borrador.resultado_skill_desactualizado is False


@pytest.mark.anyio
async def test_cambio_plantilla_con_resultado_plantillas_visible():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-plantilla-skill-vis")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.tags = ["instructivo", "ventas", "facturacion"]
    sesion.tags = ["instructivo", "ventas", "facturacion"]
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.skill_pendiente = "plantilla"
    sesion.borrador.resultado_skill_desactualizado = False
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="soluciones",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.tipo_plantilla == "soluciones"
    assert sesion.tipo_plantilla == "soluciones"
    assert sesion.borrador.resultado_skill_desactualizado is True
    assert "reaplicar" in resp.opciones
    assert "plantilla" in resp.mensaje.lower()
    assert "editaste el texto" not in resp.mensaje.lower()
    assert sesion.borrador.tags == ["soluciones", "ventas", "facturacion"]


@pytest.mark.anyio
async def test_cambio_plantilla_con_resultado_auditor_visible():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-plantilla-auditor-vis")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.tags = ["instructivo", "ventas", "facturacion"]
    sesion.tags = ["instructivo", "ventas", "facturacion"]
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.skill_pendiente = "auditor"
    sesion.borrador.resultado_skill_desactualizado = False
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="soluciones",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.tipo_plantilla == "soluciones"
    assert sesion.tipo_plantilla == "soluciones"
    assert sesion.borrador.resultado_skill_desactualizado is True
    assert sesion.borrador.skill_pendiente == "auditor"
    assert "reaplicar" in resp.opciones
    assert "plantilla" in resp.mensaje.lower()
    assert "editaste el texto" not in resp.mensaje.lower()


@pytest.mark.anyio
async def test_reaplicar_despues_del_cambio_usa_texto_original_y_nueva_plantilla():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-reaplicar-nueva-plantilla")
    texto_original = "Texto original redactado en el editor para probar reaplicación."
    texto_formateado_viejo = "## Borrador reestructurado con la plantilla 'instructivo'\n\nTexto viejo"
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.texto_editor = texto_original
    sesion.borrador.texto_base_limpio = texto_original
    sesion.texto_editor = texto_original
    sesion.borrador.bloques_texto = [texto_formateado_viejo]
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.skill_pendiente = "plantilla"
    sesion.borrador.resultado_skill_desactualizado = False
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. Cambiar plantilla a soluciones
    req1 = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="soluciones",
    )
    resp1 = await manejar_turno(req1, buscador)
    assert sesion.borrador.resultado_skill_desactualizado is True
    assert "reaplicar" in resp1.opciones

    # 2. Reaplicar con mock de baco
    prompt_recibido = None

    def baco_mock(prompt):
        nonlocal prompt_recibido
        prompt_recibido = prompt
        return f"## Borrador formateado con soluciones\n\n{texto_original}"

    req2 = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        accion="reaplicar",
    )
    setattr(req2, "_baco_agent", baco_mock)
    resp2 = await manejar_turno(req2, buscador)

    assert resp2.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion.borrador.tipo_plantilla == "soluciones"
    assert sesion.borrador.resultado_skill_desactualizado is False
    # La skill recibió la nueva plantilla y el texto original
    assert prompt_recibido is not None
    assert "soluciones" in prompt_recibido.lower()
    assert texto_original in prompt_recibido
    assert "Texto viejo" not in prompt_recibido
    # Bloques de texto actualizados
    assert "soluciones" in sesion.borrador.bloques_texto[0]
    assert texto_original in sesion.borrador.bloques_texto[0]
    assert "Texto viejo" not in sesion.borrador.bloques_texto[0]


@pytest.mark.anyio
async def test_valor_plantilla_no_permitido_error_sin_cambios():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-plantilla-invalida")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.titulo = TITULO_VALIDO
    sesion.borrador.tags = ["instructivo", "ventas"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="invalida",
        titulo="Título Que No Debe Mutar",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert "no es válido" in resp.mensaje.lower() or "no es válida" in resp.mensaje.lower()
    # Sin cambios en el borrador ni en la sesión
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.tipo_plantilla == "instructivo"
    assert sesion.borrador.titulo == TITULO_VALIDO
    assert sesion.borrador.tags == ["instructivo", "ventas"]


@pytest.mark.anyio
async def test_turno_sin_cambio_de_plantilla_sin_avisos():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-plantilla-sin-cambio")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.skill_pendiente = "plantilla"
    sesion.borrador.resultado_skill_desactualizado = False
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="instructivo",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.mensaje == ""
    assert sesion.borrador.resultado_skill_desactualizado is False
    assert "reaplicar" not in resp.opciones


@pytest.mark.anyio
async def test_extra_normalizacion_espacios_y_mayusculas_sin_cambio():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-plantilla-normalizada")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.skill_pendiente = "plantilla"
    sesion.borrador.resultado_skill_desactualizado = False
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # tipo_plantilla="Instructivo " se acepta y al ser igual no genera cambio, aviso ni reaplicar
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="Instructivo ",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.mensaje == ""
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.resultado_skill_desactualizado is False
    assert "reaplicar" not in resp.opciones
