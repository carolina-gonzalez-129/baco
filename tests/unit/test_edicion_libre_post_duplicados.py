from unittest.mock import MagicMock, patch

import pytest

from baco.server.config_limites import (
    TEXTO_MAX,
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
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
        EstadoFlujo.REVISION_TIPO,
        EstadoFlujo.REVISION_METADATOS,
    }


def _crear_sesion_en_estado(estado: EstadoFlujo, session_id: str = "test-edicion") -> SesionChat:
    sesion = SesionChat(
        session_id=session_id,
        estado=estado,
        titulo=TITULO_VALIDO,
        texto_limpio=TEXTO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        ultimas_opciones=["instructivo", "soluciones"] if estado == EstadoFlujo.ESPERANDO_PLANTILLA else [],
        # "volver" viaja en navegación (solo en los pasos de carga).
        ultima_navegacion=(
            ["volver"]
            if estado in (EstadoFlujo.ESPERANDO_PLANTILLA, EstadoFlujo.ESPERANDO_METADATOS)
            else []
        ),
    )
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=TITULO_VALIDO,
        texto_limpio=TEXTO_VALIDO,
        bloques_texto=[TEXTO_VALIDO],
        tipo_plantilla="instructivo" if estado in (EstadoFlujo.ESPERANDO_METADATOS, EstadoFlujo.REVISION_METADATOS) else None,
    )
    SESIONES[session_id] = sesion
    return sesion


@pytest.mark.anyio
async def test_titulo_en_esperando_plantilla_se_descarta_con_aviso():
    # ESPERANDO_PLANTILLA no tiene campos editables: el título se descarta con aviso.
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA)
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_titulo = "Configuración avanzada del punto de venta AFIP"
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=nuevo_titulo,
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert resp.opciones == ["instructivo", "soluciones"]
    assert resp.navegacion == ["volver"]
    assert "No apliqué" in resp.mensaje
    assert "**Título**" in resp.mensaje
    assert sesion.titulo == TITULO_VALIDO
    assert sesion.borrador.titulo == TITULO_VALIDO

    # Búsqueda de duplicados NUNCA se relanza
    buscador.evaluar_titulo.assert_not_called()
    buscador.evaluar_texto.assert_not_called()


@pytest.mark.anyio
async def test_edicion_silenciosa_en_esperando_metadatos():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS)
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
    assert resp.opciones == []
    assert resp.navegacion == ["volver"]
    assert resp.mensaje.startswith("Guardé tus cambios")
    assert "**Texto**" in resp.mensaje
    assert resp.texto_limpio == nuevo_texto
    assert sesion.borrador.texto_limpio == nuevo_texto

    buscador.evaluar_titulo.assert_not_called()
    buscador.evaluar_texto.assert_not_called()


@pytest.mark.anyio
async def test_edicion_en_revision_metadatos_guarda_y_avisa():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS)
    sesion.ultimas_opciones = ["auditar", "continuar"]
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

    assert resp.estado == EstadoFlujo.REVISION_METADATOS
    assert resp.opciones == ["auditar", "continuar"]
    assert resp.mensaje.startswith("Guardé tus cambios")
    assert resp.texto_limpio == nuevo_texto
    assert sesion.borrador.texto_limpio == nuevo_texto


@pytest.mark.anyio
async def test_error_validacion_titulo_corto_no_cambia_estado():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS)
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo="Corto",  # < 15 caracteres
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.opciones == []
    assert resp.navegacion == ["volver"]
    assert f"{TITULO_MIN} caracteres" in resp.mensaje
    # Título original no se corrompe
    assert sesion.borrador.titulo == TITULO_VALIDO


@pytest.mark.anyio
async def test_error_validacion_texto_corto_no_cambia_estado():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS)
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto="Muy breve",  # < 20 caracteres
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.opciones == []
    assert resp.navegacion == ["volver"]
    assert f"{TEXTO_MIN} caracteres" in resp.mensaje
    assert sesion.borrador.texto_limpio == TEXTO_VALIDO


@pytest.mark.anyio
async def test_error_marcadores_prohibidos_en_texto():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS)
    buscador = MagicMock(spec=BuscadorDuplicados)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=TEXTO_VALIDO + " [[R1]]",
    )

    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.opciones == []
    assert "marcadores no válidos" in resp.mensaje
    assert sesion.borrador.texto_limpio == TEXTO_VALIDO


@pytest.mark.anyio
async def test_solo_se_valida_el_campo_editado():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS)
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Si el texto de la sesión tuviese algún detalle o fuese ignorado, solo validamos el título editado
    nuevo_titulo = "Título completamente nuevo y válido para el artículo"
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=nuevo_titulo,
    )

    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.titulo == nuevo_titulo
    assert resp.mensaje.startswith("Guardé tus cambios")
    assert "**Título**" in resp.mensaje
    assert "**Texto**" not in resp.mensaje


@pytest.mark.anyio
async def test_recalculo_skills_habilitadas():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS)
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
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS)
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.ultimas_opciones = ["auditar", "continuar"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    texto_con_indicar = TEXTO_VALIDO + " [Indicar configuración faltante]"
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_con_indicar,
    )

    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.REVISION_METADATOS
    assert resp.opciones == ["auditar", "continuar"]
    # Se muestra como aviso en el chat
    assert "estructura de la plantilla" in resp.mensaje
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
async def test_edicion_simultanea_titulo_y_texto():
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS)
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_tit = "Nuevo Título Válido para el Flujo"
    nuevo_txt = "Nuevo texto con longitud suficiente para superar el mínimo requerido por la regla."

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=nuevo_tit,
        texto=nuevo_txt,
    )

    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert resp.titulo == nuevo_tit
    assert resp.texto_limpio == nuevo_txt
    assert resp.mensaje.startswith("Guardé tus cambios")
    assert "**Título**" in resp.mensaje and "**Texto**" in resp.mensaje


@pytest.mark.anyio
async def test_eleccion_de_plantilla_descarta_titulo_editado_y_avanza():
    # En ESPERANDO_PLANTILLA no hay campos editables: elegir "instructivo" avanza y el título
    # editado no se aplica (el front avisa de los cambios sin guardar).
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA)
    buscador = MagicMock(spec=BuscadorDuplicados)

    nuevo_tit = "Título Editado Junto con Opción"
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=nuevo_tit,
        accion="instructivo",
    )

    resp = await manejar_turno(req, buscador)
    assert sesion.borrador.titulo != nuevo_tit
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert resp.estado == EstadoFlujo.REVISION_TIPO



@pytest.mark.anyio
async def test_reenvio_mismo_texto_previo_sin_validacion_ni_mensaje():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS)
    sesion.ultimas_opciones = ["auditar", "continuar"]
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

    # Sin cambios: no valida, mismo estado y opciones
    assert resp.mensaje == "No había cambios para guardar."
    assert resp.estado == EstadoFlujo.REVISION_METADATOS
    assert resp.opciones == ["auditar", "continuar"]

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
    assert resp_crlf.mensaje == "No había cambios para guardar."


@pytest.mark.anyio
async def test_edicion_texto_con_opcion_continuar_procesa_una_sola_vez():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS)
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar"]
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

    with patch(
        "baco.server.services.orquestador.edicion.procesar_edicion_texto",
        wraps=procesar_edicion_texto,
    ) as spy_proc:
        resp = await manejar_turno(req, buscador)
        # El texto se procesa una sola vez (en el coordinador, antes de la opción)
        assert spy_proc.call_count == 1

    assert sesion.borrador.texto_limpio == nuevo_texto
    assert resp.estado == EstadoFlujo.EDICION_FINAL


@pytest.mark.anyio
async def test_editar_vista_previa_con_resultado_skill_visible_conserva_editor_y_skill():
    # Contrato (3/11): con resultado de skill visible, `texto` es la Vista previa. Editarla no pisa
    # el texto fuente del Editor ni descarta el resultado pendiente.
    from baco.server.services.agente_service import ejecutar_skill_plantillas

    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_TIPO)
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.ultimas_opciones = ["aplicar_plantilla", "continuar"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. Aplicar la plantilla inicialmente
    baco_mock = MagicMock(return_value="### Paso 1\nConfigurar opciones iniciales del sistema Finnegans.")
    resultado_plantilla = ejecutar_skill_plantillas(sesion.session_id, sesion.borrador, baco_mock)
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.resultado_skill_desactualizado = False
    sesion.borrador.skill_pendiente = "plantilla"
    assert "Paso 1" in resultado_plantilla
    assert "Paso 1" in sesion.borrador.texto_limpio
    texto_fuente = sesion.borrador.texto_editor
    assert texto_fuente == TEXTO_VALIDO

    # 2. La persona edita la Vista previa con el resultado de skill visible
    texto_editado_usuario = (
        "Texto personalizado por el usuario después de aplicar la plantilla con detalles "
        "operativos específicos de la empresa para la configuración."
    )
    req_edicion = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        texto=texto_editado_usuario,
    )
    resp_edicion = await manejar_turno(req_edicion, buscador)

    # La Vista previa muestra lo editado
    assert resp_edicion.texto_limpio == texto_editado_usuario
    assert sesion.borrador.texto_limpio == texto_editado_usuario
    assert sesion.borrador.bloques_texto == [texto_editado_usuario]

    # El Editor conserva el texto fuente (entrada si se reaplica la skill)
    assert sesion.borrador.texto_editor == texto_fuente
    assert sesion.borrador.texto_original == texto_fuente
    assert sesion.texto_editor == texto_fuente

    # El resultado de la skill sigue pendiente de adoptar
    assert sesion.borrador.resultado_skill_pendiente is True
    assert sesion.borrador.skill_pendiente == "plantilla"

    assert resp_edicion.estado == EstadoFlujo.REVISION_TIPO
    assert resp_edicion.mensaje.startswith("Guardé tus cambios")
    assert "**Texto de la Vista previa**" in resp_edicion.mensaje
    assert resp_edicion.opciones == ["aplicar_plantilla", "continuar"]


@pytest.mark.anyio
async def test_editar_sin_resultado_pendiente_sin_aviso():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS)
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

    # Sin aviso de skill desactualizada: solo el detalle de lo guardado
    assert resp.mensaje.startswith("Guardé tus cambios")
    assert "Vista previa" not in resp.mensaje
    assert "reaplicar" not in resp.opciones
    assert sesion.borrador.resultado_skill_desactualizado is False


@pytest.mark.anyio
async def test_reaplicar_sin_skill_pendiente_no_hace_nada():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS)
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

    assert resp.estado == EstadoFlujo.REVISION_METADATOS
    assert sesion.estado == EstadoFlujo.REVISION_METADATOS
    assert sesion.borrador.texto_limpio == texto_original
    assert sesion.borrador.bloques_texto == bloques_originales
    assert resp.opciones == ["finalizar", "editar", "rechazar"]

    # Caso 2: resultado_skill_pendiente es True pero skill_pendiente es None
    sesion.borrador.resultado_skill_pendiente = True
    sesion.borrador.skill_pendiente = None

    resp2 = await manejar_turno(req, buscador)

    assert resp2.estado == EstadoFlujo.REVISION_METADATOS
    assert sesion.estado == EstadoFlujo.REVISION_METADATOS
    assert sesion.borrador.texto_limpio == texto_original
    assert sesion.borrador.bloques_texto == bloques_originales
    assert resp2.opciones == ["finalizar", "editar", "rechazar"]


def test_aplicar_plantilla_sin_edicion_previa_resultado_identico():
    from starlette.testclient import TestClient

    from baco.server.app.dependencies import get_baco_agent, get_buscador_duplicados
    from baco.server.app.main import app
    from baco.server.app.middleware import API_KEY

    sid = "test-plantilla-sin-edicion"
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_TIPO, session_id=sid)
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

    from baco.server.app.dependencies import get_baco_agent, get_buscador_duplicados
    from baco.server.app.main import app
    from baco.server.app.middleware import API_KEY

    sid = "test-auditor-sin-edicion"
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS, session_id=sid)
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
async def test_punto_1_descarta_plantilla_categoria_y_tags_fuera_de_paso_natural_sin_error():
    # En REVISION_TIPO con la plantilla ya aplicada no se editan tipo, categoría ni etiquetas.
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_TIPO, session_id="test-ignorar-meta")
    sesion.borrador.skill_aplicada = "plantilla"
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.categoria_id = 20
    sesion.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["aplicar_plantilla", "continuar"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Enviar tipo_plantilla inválido, categoria_id inexistente y tags vacíos fuera de su paso natural:
    # se descartan con aviso, sin error (ni ValueError ni 500) y sin mutar el borrador.
    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tipo_plantilla="invalida_cualquiera",
        categoria_id=999999,
        tags=[],
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.REVISION_TIPO
    assert resp.mensaje.startswith("No apliqué")
    for campo in ("**Tipo de plantilla**", "**Categoría**", "**Etiquetas**"):
        assert campo in resp.mensaje
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.categoria_id == 20
    assert sesion.borrador.tags == ["instructivo", "ventas"]


@pytest.mark.anyio
async def test_punto_3_anonimizacion_pii_y_validacion_solo_campo_modificado():
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS, session_id="test-pii-edicion")
    sesion.ultimas_opciones = ["auditar", "continuar"]
    buscador = MagicMock(spec=BuscadorDuplicados)

    # Editar título con PII (email) -> se anonimiza y se valida longitud, sin tocar el texto
    req_tit = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo="Configurar alertas para usuario@empresa.com en Ventas",
    )
    resp_tit = await manejar_turno(req_tit, buscador)
    assert resp_tit.estado == EstadoFlujo.REVISION_METADATOS
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
    assert resp_txt.estado == EstadoFlujo.REVISION_METADATOS
    assert "cliente@dominio.com" not in (sesion.borrador.texto_limpio or "")
    assert sesion.borrador.titulo == titulo_prev


@pytest.mark.anyio
async def test_esperando_metadatos_con_edicion_de_texto_y_error():
    # (ESPERANDO_PLANTILLA no tiene editables: ver test_eleccion_de_plantilla_descarta_titulo_editado_y_avanza)
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. En ESPERANDO_METADATOS: trae tags + categoria_id Y texto válido que difiere -> aplica texto y avanza
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
    assert resp_m_ok.estado == EstadoFlujo.REVISION_METADATOS

    # 2. En ESPERANDO_METADATOS: trae tags + categoria_id Y texto inválido (corto) -> error sin avanzar
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
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS, session_id="test-single-call")
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar"]
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

    assert resp.estado == EstadoFlujo.EDICION_FINAL


@pytest.mark.anyio
async def test_continuar_persiste_tags_editados_antes_de_avanzar():
    buscador = MagicMock(spec=BuscadorDuplicados)

    # 1. En revisión final (revision_intermedia=False) con accion="continuar"
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS, session_id="test-continuar-tags-final")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.categoria_id = 20
    sesion.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar"]

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        tags=["instructivo", "facturacion", "afip"],
        accion="continuar",
    )
    resp = await manejar_turno(req, buscador)

    assert resp.estado == EstadoFlujo.EDICION_FINAL
    assert sesion.borrador.tags == ["instructivo", "facturacion", "afip"]
    assert sesion.tags == ["instructivo", "facturacion", "afip"]
    assert resp.tags_acumulados == ["instructivo", "facturacion", "afip"]

    # 2. En ESPERANDO_METADATOS con accion="enviar_datos": persiste las etiquetas y avanza
    sesion_int = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS, session_id="test-continuar-tags-intermedia")
    sesion_int.borrador.tipo_plantilla = "instructivo"
    sesion_int.tipo_plantilla = "instructivo"
    sesion_int.borrador.categoria_id = 20
    sesion_int.borrador.categoria_nombre = "Ventas"
    sesion_int.categoria_id = 20
    sesion_int.categoria_nombre = "Ventas"
    sesion_int.borrador.tags = ["instructivo"]
    sesion_int.tags = ["instructivo"]

    req_int = ChatOrquestadorRequest(
        session_id=sesion_int.session_id,
        tags=["cobranzas", "recibos"],
        accion="enviar_datos",
    )
    resp_int = await manejar_turno(req_int, buscador)

    assert resp_int.estado == EstadoFlujo.REVISION_METADATOS
    assert sesion_int.borrador.tags == ["instructivo", "cobranzas", "recibos"]
    assert sesion_int.tags == ["instructivo", "cobranzas", "recibos"]


@pytest.mark.anyio
async def test_continuar_valida_tags_solo_si_cambiaron():
    from baco.server.services.orquestador.edicion import procesar_edicion_tags

    buscador = MagicMock(spec=BuscadorDuplicados)

    # Caso A: En ESPERANDO_METADATOS con categoría y etiquetas ya cargadas, si el request reenvía
    # las mismas etiquetas y aprieta "Enviar datos", NO se validan y avanza a REVISION_METADATOS.
    sesion_sin_cambio = _crear_sesion_en_estado(
        EstadoFlujo.ESPERANDO_METADATOS, session_id="test-continuar-tags-sin-cambio"
    )
    sesion_sin_cambio.borrador.tipo_plantilla = "instructivo"
    sesion_sin_cambio.tipo_plantilla = "instructivo"
    sesion_sin_cambio.borrador.categoria_id = 20
    sesion_sin_cambio.borrador.categoria_nombre = "Ventas"
    sesion_sin_cambio.borrador.tags = ["instructivo", "ventas"]
    sesion_sin_cambio.tags = ["instructivo", "ventas"]

    req_sin_cambio = ChatOrquestadorRequest(
        session_id=sesion_sin_cambio.session_id,
        tags=["instructivo", "ventas"],
        categoria_id=20,
        accion="enviar_datos",
    )
    with patch(
        "baco.server.services.orquestador.edicion.procesar_edicion_tags",
        wraps=procesar_edicion_tags,
    ) as spy_proc_tags:
        resp_sin_cambio = await manejar_turno(req_sin_cambio, buscador)
        assert spy_proc_tags.call_count == 0

    assert resp_sin_cambio.estado == EstadoFlujo.REVISION_METADATOS

    # Caso B: Si los tags sí cambiaron pero quedan con menos de TAGS_MIN, se validan, falla y no avanza ni pisa la sesión.
    sesion_invalido = _crear_sesion_en_estado(
        EstadoFlujo.REVISION_METADATOS, session_id="test-continuar-tags-invalido"
    )
    sesion_invalido.borrador.tipo_plantilla = "instructivo"
    sesion_invalido.tipo_plantilla = "instructivo"
    sesion_invalido.borrador.categoria_id = 20
    sesion_invalido.borrador.categoria_nombre = "Ventas"
    sesion_invalido.categoria_id = 20
    sesion_invalido.categoria_nombre = "Ventas"
    sesion_invalido.borrador.tags = ["instructivo", "ventas"]
    sesion_invalido.tags = ["instructivo", "ventas"]
    sesion_invalido.ultimas_opciones = ["auditar", "continuar"]

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

    assert resp_invalido.estado == EstadoFlujo.REVISION_METADATOS
    assert "Se requieren al menos" in resp_invalido.mensaje
    assert sesion_invalido.borrador.tags == ["instructivo", "ventas"]
    assert sesion_invalido.tags == ["instructivo", "ventas"]


@pytest.mark.anyio
async def test_validacion_post_duplicados_compara_cinco_campos_sin_cambios_en_silencio():
    """Si los 5 campos (título, texto, categoría, tags, tipo de plantilla) coinciden con su
    último valor validado, se validan en silencio sin re-ejecutar validadores de edición."""
    from baco.server.services.orquestador.edicion import (
        procesar_edicion_categoria,
        procesar_edicion_tags,
        procesar_edicion_texto,
    )
    from baco.server.services.orquestador.validaciones import validar_borrador

    buscador = MagicMock(spec=BuscadorDuplicados)
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS, session_id="test-cinco-campos-silencio")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.categoria_id = 20
    sesion.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar"]
    validar_borrador(sesion)

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=sesion.borrador.titulo,
        texto=sesion.borrador.texto_limpio,
        categoria_id=20,
        tags=["instructivo", "ventas"],
        tipo_plantilla="instructivo",
        accion="continuar",
    )

    with (
        patch("baco.server.services.orquestador.edicion.procesar_edicion_titulo", wraps=procesar_edicion_titulo) as spy_tit,
        patch("baco.server.services.orquestador.edicion.procesar_edicion_texto", wraps=procesar_edicion_texto) as spy_txt,
        patch("baco.server.services.orquestador.edicion.procesar_edicion_categoria", wraps=procesar_edicion_categoria) as spy_cat,
        patch("baco.server.services.orquestador.edicion.procesar_edicion_tags", wraps=procesar_edicion_tags) as spy_tags,
        patch("baco.server.services.orquestador.handlers.validar_borrador", wraps=validar_borrador) as spy_val_borr,
    ):
        resp = await manejar_turno(req, buscador)
        assert spy_tit.call_count == 0
        assert spy_txt.call_count == 0
        assert spy_cat.call_count == 0
        assert spy_tags.call_count == 0
        assert spy_val_borr.call_count == 0

    assert resp.estado == EstadoFlujo.EDICION_FINAL


@pytest.mark.anyio
async def test_validacion_post_duplicados_solo_valida_y_pide_accion_sobre_campo_modificado():
    """Al enviar los 5 campos, solo se valida y pide acción sobre el campo que cambió;
    los campos no modificados se validan en silencio."""
    from baco.server.services.orquestador.edicion import (
        procesar_edicion_categoria,
        procesar_edicion_tags,
        procesar_edicion_texto,
    )

    buscador = MagicMock(spec=BuscadorDuplicados)
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS, session_id="test-solo-campo-modificado")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.categoria_id = 20
    sesion.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar"]

    # 1. Solo cambia categoria_id a un valor inválido; título, texto, tags y plantilla no cambiaron
    req_cat_inv = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=sesion.borrador.titulo,
        texto=sesion.borrador.texto_limpio,
        categoria_id=999999,
        tags=["instructivo", "ventas"],
        tipo_plantilla="instructivo",
        accion="continuar",
    )
    with (
        patch("baco.server.services.orquestador.edicion.procesar_edicion_titulo", wraps=procesar_edicion_titulo) as spy_tit,
        patch("baco.server.services.orquestador.edicion.procesar_edicion_texto", wraps=procesar_edicion_texto) as spy_txt,
        patch("baco.server.services.orquestador.edicion.procesar_edicion_categoria", wraps=procesar_edicion_categoria) as spy_cat,
        patch("baco.server.services.orquestador.edicion.procesar_edicion_tags", wraps=procesar_edicion_tags) as spy_tags,
    ):
        resp_cat = await manejar_turno(req_cat_inv, buscador)
        assert spy_tit.call_count == 0
        assert spy_txt.call_count == 0
        assert spy_cat.call_count == 1
        assert spy_tags.call_count == 0

    assert resp_cat.estado == EstadoFlujo.REVISION_METADATOS
    assert "categoría" in resp_cat.mensaje.lower()
    assert sesion.borrador.categoria_id == 20

    # 2. Solo cambia tipo_plantilla: en REVISION_METADATOS no es editable, se descarta con aviso
    req_plant_inv = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=sesion.borrador.titulo,
        texto=sesion.borrador.texto_limpio,
        categoria_id=20,
        tags=["instructivo", "ventas"],
        tipo_plantilla="plantilla_inexistente",
    )
    resp_plant_inv = await manejar_turno(req_plant_inv, buscador)
    assert resp_plant_inv.estado == EstadoFlujo.REVISION_METADATOS
    assert "No apliqué" in resp_plant_inv.mensaje
    assert "**Tipo de plantilla**" in resp_plant_inv.mensaje
    assert sesion.borrador.tipo_plantilla == "instructivo"

    # 3. Solo cambia categoria_id a una válida (21 - Contabilidad) y continúa
    req_cambio_valido = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=sesion.borrador.titulo,
        texto=sesion.borrador.texto_limpio,
        categoria_id=21,
        tags=["instructivo", "ventas"],
        tipo_plantilla="instructivo",
        accion="continuar",
    )
    resp_ok = await manejar_turno(req_cambio_valido, buscador)
    assert resp_ok.estado == EstadoFlujo.EDICION_FINAL
    assert sesion.borrador.tipo_plantilla == "instructivo"
    assert sesion.borrador.categoria_id == 21
    assert sesion.borrador.categoria_nombre == "Contabilidad"
    assert "instructivo" in sesion.borrador.tags
    assert "ventas" in sesion.borrador.tags


@pytest.mark.anyio
async def test_esperando_metadatos_compara_cinco_campos_y_solo_pide_accion_en_modificados():
    """En ESPERANDO_METADATOS, reenviar campos ya validados junto con la acción del paso
    valida en silencio los no modificados y solo pide acción sobre lo que falta o cambió."""
    buscador = MagicMock(spec=BuscadorDuplicados)
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS, session_id="test-metadatos-cinco-campos")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.borrador.categoria_id = None
    sesion.categoria_id = None

    # Caso 1: Usuario envía categoría por mensaje ("Ventas") mientras el front reenvía
    # título, texto, tipo_plantilla y tags sin cambios.
    req_cat_msg = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=sesion.borrador.titulo,
        texto=sesion.borrador.texto_limpio,
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
        mensaje="Ventas",
    )
    resp = await manejar_turno(req_cat_msg, buscador)
    assert resp.estado == EstadoFlujo.REVISION_METADATOS
    assert sesion.borrador.categoria_id == 20
    assert sesion.borrador.categoria_nombre == "Ventas"
    assert sesion.borrador.tags == ["instructivo", "ventas"]

    # Caso 2: En ESPERANDO_METADATOS con categoría ya validada (20), el usuario modifica tags
    # quitando el tag temático (queda solo ["instructivo"]) y reenvía categoria_id=20 sin cambios.
    # Solo debe pedir acción sobre el tag faltante, manteniendo la categoría validada en silencio.
    sesion2 = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_METADATOS, session_id="test-metadatos-solo-tags")
    sesion2.borrador.tipo_plantilla = "instructivo"
    sesion2.tipo_plantilla = "instructivo"
    sesion2.borrador.categoria_id = 20
    sesion2.borrador.categoria_nombre = "Ventas"
    sesion2.categoria_id = 20
    sesion2.categoria_nombre = "Ventas"
    sesion2.borrador.tags = ["instructivo", "ventas"]
    sesion2.tags = ["instructivo", "ventas"]

    req_quita_tag = ChatOrquestadorRequest(
        session_id=sesion2.session_id,
        titulo=sesion2.borrador.titulo,
        texto=sesion2.borrador.texto_limpio,
        categoria_id=20,
        tipo_plantilla="instructivo",
        tags=["instructivo"],
    )
    resp2 = await manejar_turno(req_quita_tag, buscador)
    assert resp2.estado == EstadoFlujo.ESPERANDO_METADATOS
    assert sesion2.borrador.categoria_id == 20
    assert "etiqueta" in resp2.mensaje.lower() or "tag" in resp2.mensaje.lower()
    assert "categoría" not in resp2.mensaje.lower()


@pytest.mark.anyio
async def test_esperando_plantilla_no_revalida_texto_sin_cambios_como_plantilla():
    """En ESPERANDO_PLANTILLA, si el texto del artículo contiene la palabra 'instructivo' pero no cambió,
    no debe interpretarse el texto sin cambios como selección de plantilla cuando falta elegirla."""
    buscador = MagicMock(spec=BuscadorDuplicados)
    sesion = _crear_sesion_en_estado(EstadoFlujo.ESPERANDO_PLANTILLA, session_id="test-plantilla-texto-igual")
    texto_con_palabra = (
        "Este documento describe el instructivo detallado para configurar el módulo de facturación "
        "electrónica en el sistema de gestión comercial paso a paso."
    )
    sesion.actualizar_contenido_borrador(
        bloques_texto=[texto_con_palabra],
        texto_base_limpio=texto_con_palabra,
        texto_editor=texto_con_palabra,
        texto_original=texto_con_palabra,
    )
    sesion.borrador.tipo_plantilla = None
    sesion.tipo_plantilla = None
    sesion.borrador.tags = []
    sesion.tags = []

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo=sesion.borrador.titulo,
        texto=texto_con_palabra,
        mensaje="texto_invalido_no_plantilla",
    )
    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.ESPERANDO_PLANTILLA
    assert sesion.borrador.tipo_plantilla is None


@pytest.mark.anyio
async def test_anonimizacion_pii_se_mantiene_siempre_en_titulo_texto_y_tags_post_duplicados():
    """La anonimización de PII se mantiene siempre en las validaciones posteriores a duplicados
    para título, texto y tags."""
    buscador = MagicMock(spec=BuscadorDuplicados)
    sesion = _crear_sesion_en_estado(EstadoFlujo.REVISION_METADATOS, session_id="test-pii-post-duplicados")
    sesion.borrador.tipo_plantilla = "instructivo"
    sesion.tipo_plantilla = "instructivo"
    sesion.borrador.categoria_id = 20
    sesion.borrador.categoria_nombre = "Ventas"
    sesion.categoria_id = 20
    sesion.categoria_nombre = "Ventas"
    sesion.borrador.tags = ["instructivo", "ventas"]
    sesion.tags = ["instructivo", "ventas"]
    sesion.ultimas_opciones = ["auditar", "continuar"]

    req = ChatOrquestadorRequest(
        session_id=sesion.session_id,
        titulo="Configuración de cuenta para cliente@empresa.com en sistema",
        texto=(
            "Para configurar el acceso del usuario juan.perez@gmail.com comuníquese "
            "al correo indicado y verifique todos los parámetros del servidor."
        ),
        tags=["instructivo", "ventas", "contacto maria.gomez@gmail.com"],
        categoria_id=20,
        tipo_plantilla="instructivo",
    )
    resp = await manejar_turno(req, buscador)
    assert resp.estado == EstadoFlujo.REVISION_METADATOS
    assert "cliente@empresa.com" not in sesion.borrador.titulo
    assert "juan.perez@gmail.com" not in sesion.borrador.texto_limpio
    assert all("maria.gomez@gmail.com" not in t for t in sesion.borrador.tags)
    assert resp.aviso_privacidad is not None
