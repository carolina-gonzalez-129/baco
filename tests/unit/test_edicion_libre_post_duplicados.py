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
async def test_editar_texto_con_resultado_skill_visible_descarta_skill_y_actualiza_vista_previa():
    from baco.server.services.agente_service import ejecutar_skill_plantillas

    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR)
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.ultimas_opciones = ["aplicar_plantilla", "continuar_revision", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. Aplicar la plantilla inicialmente
    baco_mock = MagicMock(return_value="### Paso 1\nConfigurar opciones iniciales del sistema Finnegans.")
    resultado_plantilla = ejecutar_skill_plantillas(sesion.session_id, sesion.borrador, baco_mock)
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.resultado_skill_desactualizado = False
    sesion.borrador.skill_pendiente = "plantilla"
    assert "Paso 1" in resultado_plantilla
    assert "Paso 1" in sesion.borrador.texto_limpio

    # 2. La persona edita el texto del Editor con un resultado de skill visible
    texto_editado_usuario = (
        "Texto personalizado por el usuario después de aplicar la plantilla con detalles "
        "operativos específicos de la empresa para la configuración."
    )
    req_edicion = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_editado_usuario,
    )
    resp_edicion = await manejar_turno(req_edicion, buscador)

    # El texto editado pasa a ser el nuevo original (texto_editor y texto_base_limpio)
    assert sesion.borrador.texto_editor == texto_editado_usuario
    assert sesion.borrador.texto_base_limpio == texto_editado_usuario
    assert sesion.texto_editor == texto_editado_usuario

    # La Vista previa muestra el texto editado (se descarta el resultado de la skill)
    assert resp_edicion.texto_limpio == texto_editado_usuario
    assert sesion.borrador.texto_limpio == texto_editado_usuario
    assert sesion.borrador.bloques_texto == [texto_editado_usuario]
    assert "Paso 1" not in resp_edicion.texto_limpio

    # Se limpian resultado_skill_pendiente, resultado_skill_desactualizado y skill_pendiente
    assert sesion.borrador.resultado_skill_pendiente is False
    assert sesion.borrador.resultado_skill_desactualizado is False
    assert sesion.borrador.skill_pendiente is None

    # No se reaplica nada ni se ofrece "reaplicar" ni aviso de desactualizada
    assert resp_edicion.mensaje == ""
    assert "reaplicar" not in resp_edicion.opciones
    assert resp_edicion.opciones == ["aplicar_plantilla", "continuar_revision", "volver"]


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
async def test_punto_1_ignora_plantilla_categoria_y_tags_fuera_de_paso_natural_sin_error():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-ignorar-meta")
    sesion.borrador.revision_intermedia = False
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.categoria_id = 20
    sesion.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Enviar tipo_plantilla inválido, categoria_id inexistente y tags vacíos fuera de su paso natural:
    # deben ignorarse sin error (ni ValueError ni 500) y sin mutar el borrador.
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="invalida_cualquiera",
        categoria_id=999999,
        tags=[],
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_BORRADOR
    assert resp.mensaje == ""
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.categoria_id == 20
    assert sesion.borrador.tags == ["instructivo", "ventas"]


@pytest.mark.anyio
async def test_punto_3_anonimizacion_pii_y_validacion_solo_campo_modificado():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-pii-edicion")
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Editar título con PII (email) -> se anonimiza y se valida longitud, sin tocar el texto
    req_tit = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo="Configurar alertas para usuario@empresa.com en Ventas",
    )
    resp_tit = await manejar_turno(req_tit, buscador)
    assert resp_tit.estado == EstadoFlujo.REVISION_BORRADOR
    assert "usuario@empresa.com" not in (sesion.borrador.titulo or "")
    assert sesion.borrador.texto_limpio == TEXTO_VALIDO

    # Editar texto con PII (email) -> se anonimiza y se valida longitud, sin tocar el título
    titulo_prev = sesion.borrador.titulo
    req_txt = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=(
            "Para configurar el envío de comprobantes a cliente@dominio.com en Finnegans ERP "
            "es necesario ingresar al maestro de clientes y verificar la casilla de correo."
        ),
    )
    resp_txt = await manejar_turno(req_txt, buscador)
    assert resp_txt.estado == EstadoFlujo.REVISION_BORRADOR
    assert "cliente@dominio.com" not in (sesion.borrador.texto_limpio or "")
    assert sesion.borrador.titulo == titulo_prev


@pytest.mark.anyio
async def test_esperando_plantilla_y_metadatos_con_edicion_titulo_texto_y_error():
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. En ESPERANDO_PLANTILLA: trae tipo_plantilla Y título válido que difiere -> aplica título y avanza
    sesion_p = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA, session_id="test-p-combo-ok")
    nuevo_tit = "Título editado al elegir plantilla en paso natural"
    req_p_ok = ChatOrquestadorRequest(
        session_id=sesion_p.session_id,
        tipo_plantilla="instructivo",
        titulo=nuevo_tit,
    )
    resp_p_ok = await manejar_turno(req_p_ok, buscador)
    assert sesion_p.borrador.titulo == nuevo_tit
    assert sesion_p.borrador.tipo_plantilla == "instructivo"
    assert resp_p_ok.estado == EstadoFlujo.REVISION_BORRADOR

    # 2. En ESPERANDO_PLANTILLA: trae tipo_plantilla Y título inválido (corto) -> error sin avanzar
    sesion_p_err = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA, session_id="test-p-combo-err")
    req_p_err = ChatOrquestadorRequest(
        session_id=sesion_p_err.session_id,
        tipo_plantilla="instructivo",
        titulo="Corto",
    )
    resp_p_err = await manejar_turno(req_p_err, buscador)
    assert resp_p_err.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert sesion_p_err.borrador.tipo_plantilla is None
    assert sesion_p_err.borrador.titulo == TITULO_VALIDO
    assert f"{TITULO_MIN} caracteres" in resp_p_err.mensaje

    # 3. En ESPERANDO_METADATOS: trae tags + categoria_id Y texto válido que difiere -> aplica texto y avanza
    sesion_m = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS, session_id="test-m-combo-ok")
    sesion_m.borrador.tags = ["instructivo"]
    nuevo_txt = (
        "1. Ingresar al módulo de Ventas en el menú principal.\n\n"
        "2. Seleccionar el punto de venta electrónico y asociar el certificado AFIP."
    )
    req_m_ok = ChatOrquestadorRequest(
        session_id=sesion_m.session_id,
        tags=["instructivo", "ventas"],
        categoria_id=20,
        texto=nuevo_txt,
    )
    resp_m_ok = await manejar_turno(req_m_ok, buscador)
    assert sesion_m.borrador.texto_limpio == nuevo_txt
    assert sesion_m.borrador.categoria_id == 20
    assert "ventas" in sesion_m.borrador.tags
    assert resp_m_ok.estado == EstadoFlujo.REVISION_BORRADOR

    # 4. En ESPERANDO_METADATOS: trae tags + categoria_id Y texto inválido (corto) -> error sin avanzar
    sesion_m_err = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS, session_id="test-m-combo-err")
    sesion_m_err.borrador.tags = ["instructivo"]
    req_m_err = ChatOrquestadorRequest(
        session_id=sesion_m_err.session_id,
        tags=["instructivo", "ventas"],
        categoria_id=20,
        texto="Muy corto",
    )
    resp_m_err = await manejar_turno(req_m_err, buscador)
    assert resp_m_err.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert sesion_m_err.borrador.categoria_id is None
    assert sesion_m_err.borrador.texto_limpio == TEXTO_VALIDO
    assert f"{TEXTO_MIN} caracteres" in resp_m_err.mensaje


@pytest.mark.anyio
async def test_continuar_con_edicion_ejecuta_aplicar_edicion_campos_una_sola_vez():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-single-call")
    sesion.borrador.revision_intermedia = False
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo="Cómo configurar el punto de venta electrónico en Ventas",
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
async def test_continuar_persiste_tags_editados_antes_de_avanzar():
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. En revisión final (revision_intermedia=False) con accion="continuar"
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-continuar-tags-final")
    sesion.borrador.revision_intermedia = False
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.categoria_id = 20
    sesion.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar", "volver"]

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=["instructivo", "facturacion", "afip"],
        accion="continuar",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.FINALIZADO
    assert sesion.borrador.tags == ["instructivo", "facturacion", "afip"]
    assert sesion.tags == ["instructivo", "facturacion", "afip"]
    assert resp.tags_acumulados == ["instructivo", "facturacion", "afip"]

    # 2. En revisión intermedia (revision_intermedia=True) con accion="continuar_revision"
    sesion_int = _crear_sesion_en_estado(EstadoFlujo.REVISION_BORRADOR, session_id="test-continuar-tags-intermedia")
    sesion_int.borrador.revision_intermedia = True
    sesion_int.borrador.tipo_plantilla = "instructivo"
    sesion_int.tipo_plantilla = "instructivo"
    sesion_int.borrador.categoria_id = 20
    sesion_int.borrador.categoria_nombre = "Ventas"
    sesion_int.categoria_id = 20
    sesion_int.categoria_nombre = "Ventas"
    sesion_int.borrador.tags = ["instructivo"]
    sesion_int.tags = ["instructivo"]
    sesion_int.ultimas_opciones = ["aplicar_plantilla", "continuar_revision", "volver"]

    req_int = ChatOrquestadorRequest(
        session_id=sesion_int.session_id,
        tags=["cobranzas", "recibos"],
        accion="continuar_revision",
    )
    resp_int = await manejar_turno(req_int, buscador)

    # Al tener ya categoria_id=20 y ahora >= 2 tags persistidos antes de avanzar, pasa directo a revisión final
    assert resp_int.estado == EstadoFlujo.REVISION_BORRADOR
    assert sesion_int.borrador.revision_intermedia is False
    assert sesion_int.borrador.tags == ["instructivo", "cobranzas", "recibos"]
    assert sesion_int.tags == ["instructivo", "cobranzas", "recibos"]


@pytest.mark.anyio
async def test_continuar_valida_tags_solo_si_cambiaron():
    from baco.server.services.orquestador.edicion import procesar_edicion_tags

    buscador = MagicMock(spec=BuscadorDuplicados)

    # Caso A: En revisión intermedia los tags guardados son ["instructivo"] (< TAGS_MIN).
    # Si el request reenvía los mismos tags sin cambios y aprieta "Continuar", NO se validan y avanza a ESPERANDO_METADATOS.
    sesion_sin_cambio = _crear_sesion_en_estado(
        EstadoFlujo.REVISION_BORRADOR, session_id="test-continuar-tags-sin-cambio"
    )
    sesion_sin_cambio.borrador.revision_intermedia = True
    sesion_sin_cambio.borrador.tipo_plantilla = "instructivo"
    sesion_sin_cambio.tipo_plantilla = "instructivo"
    sesion_sin_cambio.borrador.tags = ["instructivo"]
    sesion_sin_cambio.tags = ["instructivo"]
    sesion_sin_cambio.ultimas_opciones = ["aplicar_plantilla", "continuar_revision", "volver"]

    req_sin_cambio = ChatOrquestadorRequest(
        session_id=sesion_sin_cambio.session_id,
        tags=["instructivo"],
        accion="continuar_revision",
    )
    with patch(
        "baco.server.services.orquestador.edicion.procesar_edicion_tags",
        wraps=procesar_edicion_tags,
    ) as spy_proc_tags:
        resp_sin_cambio = await manejar_turno(req_sin_cambio, buscador)
        assert spy_proc_tags.call_count == 0

    assert resp_sin_cambio.estado == EstadoFlujo.ESPERANDO_METADATOS

    # Caso B: Si los tags sí cambiaron pero quedan con menos de TAGS_MIN, se validan, falla y no avanza ni pisa la sesión.
    sesion_invalido = _crear_sesion_en_estado(
        EstadoFlujo.REVISION_BORRADOR, session_id="test-continuar-tags-invalido"
    )
    sesion_invalido.borrador.revision_intermedia = False
    sesion_invalido.borrador.tipo_plantilla = "instructivo"
    sesion_invalido.tipo_plantilla = "instructivo"
    sesion_invalido.borrador.categoria_id = 20
    sesion_invalido.borrador.categoria_nombre = "Ventas"
    sesion_invalido.categoria_id = 20
    sesion_invalido.categoria_nombre = "Ventas"
    sesion_invalido.borrador.tags = ["instructivo", "ventas"]
    sesion_invalido.tags = ["instructivo", "ventas"]
    sesion_invalido.ultimas_opciones = ["auditar", "continuar", "volver"]

    req_invalido = ChatOrquestadorRequest(
        session_id=sesion_invalido.session_id,
        tags=["instructivo"],
        accion="continuar",
    )
    with patch(
        "baco.server.services.orquestador.edicion.procesar_edicion_tags",
        wraps=procesar_edicion_tags,
    ) as spy_proc_tags_inv:
        resp_invalido = await manejar_turno(req_invalido, buscador)
        assert spy_proc_tags_inv.call_count == 1

    assert resp_invalido.estado == EstadoFlujo.REVISION_BORRADOR
    assert "Se requieren al menos" in resp_invalido.mensaje
    assert sesion_invalido.borrador.tags == ["instructivo", "ventas"]
    assert sesion_invalido.tags == ["instructivo", "ventas"]
