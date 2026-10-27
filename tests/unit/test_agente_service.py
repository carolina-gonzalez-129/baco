import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from baco.server.schemas.chat_orquestado import BorradorSesion
from baco.server.schemas.recurso import Recurso
from baco.server.services.agente_service import (
    ejecutar_skill_plantillas,
    ejecutar_skill_validador,
    _obtener_texto_limpio_estricto,
)
from baco.server.services.orquestador.sesion import gestor_sesiones


def test_skills_rechazan_si_borrador_tiene_recursos_o_marcadores_y_no_llaman_al_modelo():
    """Guarda defensiva: si el borrador contiene recursos o marcadores/tags multimedia,
    se corta con error 400 y el modelo nunca es invocado."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id

    recs = {
        "rec_1": Recurso(
            id="rec_1",
            tipo="imagen",
            nombre="Captura",
            referencia="https://bc.finneg.com/uploads/original/error_123.png",
            orden=0,
        ),
    }

    # Caso 1: borrador con diccionario de recursos poblado
    borrador_con_recursos = BorradorSesion(
        modo="nuevo",
        titulo="Cómo configurar el sistema contable",
        texto_limpio="Texto completamente limpio para configurar el sistema contable paso a paso.",
        recursos=recs,
        tipo_plantilla="instructivo",
        conforme=True,
    )

    mock_baco = MagicMock()

    with pytest.raises(HTTPException) as exc1:
        ejecutar_skill_plantillas(sid, borrador_con_recursos, mock_baco)
    assert exc1.value.status_code == 400
    assert "recursos multimedia" in exc1.value.detail
    mock_baco.assert_not_called()

    with pytest.raises(HTTPException) as exc2:
        ejecutar_skill_validador(borrador_con_recursos, mock_baco)
    assert exc2.value.status_code == 400
    assert "recursos multimedia" in exc2.value.detail
    mock_baco.assert_not_called()

    # Caso 2: borrador sin dict de recursos pero con marcador [[recurso:rec_1]] forzado en bloques_texto
    borrador_con_marcador = BorradorSesion(
        modo="nuevo",
        titulo="Cómo configurar el sistema contable",
        bloques_texto=["Texto preliminar en el cuerpo."],
        tipo_plantilla="instructivo",
        conforme=True,
    )
    object.__setattr__(
        borrador_con_marcador,
        "bloques_texto",
        ["Texto preliminar con marcador [[recurso:rec_1]] en el cuerpo."],
    )

    with pytest.raises(HTTPException) as exc3:
        ejecutar_skill_plantillas(sid, borrador_con_marcador, mock_baco)
    assert exc3.value.status_code == 400
    assert "marcadores de recursos" in exc3.value.detail
    mock_baco.assert_not_called()

    # Caso 3: texto con tag HTML multimedia
    borrador_con_html = BorradorSesion(
        modo="nuevo",
        titulo="Cómo configurar el sistema contable",
        texto_limpio="Texto que contiene un tag <img src='https://ejemplo.com/foto.png'> en el cuerpo.",
        tipo_plantilla="instructivo",
        conforme=True,
    )

    with pytest.raises(HTTPException) as exc4:
        ejecutar_skill_plantillas(sid, borrador_con_html, mock_baco)
    assert exc4.value.status_code == 400
    assert "tags multimedia" in exc4.value.detail
    mock_baco.assert_not_called()

    # Caso 4: texto con imagen Markdown
    borrador_con_md = BorradorSesion(
        modo="nuevo",
        titulo="Cómo configurar el sistema contable",
        texto_limpio="Texto que contiene una imagen ![captura](https://ejemplo.com/foto.png) en Markdown.",
        tipo_plantilla="instructivo",
        conforme=True,
    )

    with pytest.raises(HTTPException) as exc5:
        ejecutar_skill_plantillas(sid, borrador_con_md, mock_baco)
    assert exc5.value.status_code == 400
    assert "tags multimedia" in exc5.value.detail
    mock_baco.assert_not_called()


def test_skills_aceptan_texto_puro_sin_recursos_y_permiten_marcadores_pii():
    """El agente procesa correctamente texto sin recursos y acepta marcadores PII anonimizados."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id

    texto_con_pii = (
        "Pasos para ingresar al ERP Finnegans con credenciales protegidas:\n\n"
        "1. Ingresar usuario 'admin' y clave [CONTRASENA_OCULTA].\n"
        "2. Validar token [TOKEN_OCULTO] de autenticación de dos factores.\n"
        "3. Confirmar que el comprobante pertenezca a la empresa con CUIT 30-12345678-9."
    )

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Ingreso seguro al sistema",
        texto_limpio=texto_con_pii,
        tipo_plantilla="instructivo",
        conforme=True,
    )

    prompts_recibidos = []

    def mock_baco(prompt: str) -> str:
        prompts_recibidos.append(prompt)
        return (
            "## Ingreso seguro al sistema\n\n"
            "### Objetivo\n"
            "Describir el proceso de autenticación con credenciales anonimizadas.\n\n"
            "### Procedimiento\n"
            "1. Ingresar con clave [CONTRASENA_OCULTA].\n"
            "2. Validar token [TOKEN_OCULTO] de seguridad."
        )

    # 1. Probar plantillas
    resultado = ejecutar_skill_plantillas(sid, borrador, mock_baco)
    assert len(prompts_recibidos) == 1
    assert "[CONTRASENA_OCULTA]" in prompts_recibidos[0]
    assert "[TOKEN_OCULTO]" in prompts_recibidos[0]
    assert "REGLA CRÍTICA DE MARCADORES MULTIMEDIA" not in prompts_recibidos[0]
    assert "[CONTRASENA_OCULTA]" in resultado

    # 2. Probar validador
    resultado_val = ejecutar_skill_validador(borrador, mock_baco)
    assert len(prompts_recibidos) == 2
    assert "[CONTRASENA_OCULTA]" in prompts_recibidos[1]
    assert resultado_val is not None


def test_agente_corta_con_error_claro_si_no_hay_texto():
    """Si texto_limpio y texto están vacíos, corta con HTTPException 400."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Guía vacía",
        texto="",
        texto_limpio="",
        tipo_plantilla="instructivo",
        conforme=True,
    )
    sesion.borrador = borrador

    mock_baco = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        ejecutar_skill_plantillas(sid, borrador, mock_baco)

    assert exc_info.value.status_code == 400
    assert "no contiene texto" in exc_info.value.detail
    mock_baco.assert_not_called()

    with pytest.raises(HTTPException) as exc_info_val:
        ejecutar_skill_validador(borrador, mock_baco)

    assert exc_info_val.value.status_code == 400
    assert "no contiene texto" in exc_info_val.value.detail
    mock_baco.assert_not_called()


def test_borrador_texto_no_es_asignable_y_coincide_siempre_con_componer_texto_publicable():
    """Riesgo 4: borrador.texto_alineado_discourse no se puede asignar directamente y se deriva de bloques_texto y recursos."""
    from baco.server.services.orquestador.recursos_service import componer_texto_publicable

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Título de prueba",
        bloques_texto=["Texto inicial de prueba para la composición de borrador."],
        conforme=True,
    )

    # 1. borrador.texto_alineado_discourse coincide exactamente con componer_texto_publicable
    assert borrador.texto_alineado_discourse == componer_texto_publicable(borrador.bloques_texto, borrador.recursos)
    assert not hasattr(borrador, "texto")

    # 2. Intentar asignar borrador.texto o borrador.texto_alineado_discourse debe fallar
    with pytest.raises((AttributeError, TypeError)):
        borrador.texto = "Intento de asignación manual directa"
    with pytest.raises((AttributeError, TypeError)):
        borrador.texto_alineado_discourse = "Intento de asignación manual directa"

    # 3. Al cambiar bloques_texto, borrador.texto_alineado_discourse se actualiza inmediatamente
    borrador.bloques_texto = ["Texto modificado paso a paso sin reasignar texto_alineado_discourse."]
    assert borrador.texto_alineado_discourse == componer_texto_publicable(borrador.bloques_texto, borrador.recursos)
    assert "Texto modificado paso a paso" in borrador.texto_alineado_discourse

    # 4. Al agregar un recurso, borrador.texto_alineado_discourse se actualiza inmediatamente reflejando el recurso
    nuevo_rec = Recurso(
        id="rec_1",
        tipo="imagen",
        nombre="Diagrama de flujo",
        referencia="https://bc.finneg.com/uploads/diagrama.png",
        posicion=0,
        orden=0,
    )
    borrador.agregar_multimedia(nuevo_rec)
    assert borrador.texto_alineado_discourse == componer_texto_publicable(borrador.bloques_texto, borrador.recursos)
    assert "https://bc.finneg.com/uploads/diagrama.png" in borrador.texto_alineado_discourse


def test_escapar_delimitadores_xml_usa_constante_buffer():
    """Ítem 5: Verifica que _escapar_delimitadores_xml utilice la constante con nombre
    BUFFER_CARACTERES_PROMPT_XML para limitar el tamaño del prompt XML."""
    from baco.server.config_limites import BUFFER_CARACTERES_PROMPT_XML, TEXTO_MAX
    from baco.server.services.agente_service import _escapar_delimitadores_xml

    assert isinstance(BUFFER_CARACTERES_PROMPT_XML, int)
    assert BUFFER_CARACTERES_PROMPT_XML == 500

    texto_muy_largo = "A" * (TEXTO_MAX + BUFFER_CARACTERES_PROMPT_XML + 300)
    resultado = _escapar_delimitadores_xml(texto_muy_largo)
    assert len(resultado) == TEXTO_MAX + BUFFER_CARACTERES_PROMPT_XML

