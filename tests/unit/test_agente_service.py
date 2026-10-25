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


def test_agente_nunca_recibe_url_de_recurso_cuando_texto_limpio_esta_definido():
    """El agente solo recibe texto_limpio y nunca las URLs de los recursos del borrador."""
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
        "rec_2": Recurso(
            id="rec_2",
            tipo="video",
            nombre="Video",
            referencia="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            orden=1,
        ),
    }

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Cómo configurar el sistema contable",
        texto="Texto compuesto con URLs https://bc.finneg.com/uploads/original/error_123.png",
        texto_limpio="Texto completamente limpio para configurar el sistema contable paso a paso.",
        recursos=recs,
        tipo_plantilla="instructivo",
        conforme=True,
    )
    sesion.borrador = borrador

    prompts_recibidos = []

    def mock_baco(prompt: str) -> str:
        prompts_recibidos.append(prompt)
        return (
            "## Cómo configurar el sistema contable\n\n"
            "### Pasos a seguir\n\n"
            "Texto formateado por el modelo cumpliendo con la longitud mínima requerida."
        )

    # 1. Probar skill plantillas
    ejecutar_skill_plantillas(sid, borrador, mock_baco)
    assert len(prompts_recibidos) == 1
    prompt_plantillas = prompts_recibidos[0]
    assert "https://bc.finneg.com/uploads/original/error_123.png" not in prompt_plantillas
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" not in prompt_plantillas
    assert "Texto completamente limpio para configurar el sistema contable" in prompt_plantillas

    # 2. Probar skill validador sobre un nuevo borrador con texto_limpio original
    borrador_validador = BorradorSesion(
        modo="nuevo",
        titulo="Cómo configurar el sistema contable",
        texto="Texto compuesto con URLs https://bc.finneg.com/uploads/original/error_123.png",
        texto_limpio="Texto original a auditar para configurar el sistema contable.",
        recursos=recs,
        conforme=True,
    )
    ejecutar_skill_validador(borrador_validador, mock_baco)
    assert len(prompts_recibidos) == 2
    prompt_validador = prompts_recibidos[1]
    assert "https://bc.finneg.com/uploads/original/error_123.png" not in prompt_validador
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" not in prompt_validador
    assert "Texto original a auditar para configurar el sistema contable" in prompt_validador


def test_agente_deriva_texto_limpio_si_esta_vacio_sin_filtrar_urls():
    """Si texto_limpio está vacío, se deriva con extraer_recursos_y_texto_limpio y nunca llega la URL al agente."""
    sesion, _, _ = gestor_sesiones.obtener_o_crear(None)
    sid = sesion.session_id

    url_imagen = "https://bc.finneg.com/uploads/default/original/pantalla.png"
    url_video = "https://www.youtube.com/watch?v=abcxyz"
    texto_raw = (
        f"Pasos preliminares para la configuración:\n\n"
        f"![captura]({url_imagen})\n\n"
        f"Continuar con la validación de credenciales según el video:\n\n"
        f"{url_video}"
    )

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Guía con medios embebidos",
        texto=texto_raw,
        texto_limpio="",
        tipo_plantilla="instructivo",
        conforme=True,
    )
    sesion.borrador = borrador

    prompts_recibidos = []

    def mock_baco(prompt: str) -> str:
        prompts_recibidos.append(prompt)
        return (
            "## Guía con medios embebidos\n\n"
            "### Pasos a seguir\n\n"
            "Texto formateado por el modelo cumpliendo con la longitud mínima requerida."
        )

    ejecutar_skill_plantillas(sid, borrador, mock_baco)

    assert len(prompts_recibidos) == 1
    prompt = prompts_recibidos[0]

    # Ninguna URL de recurso multimedia debe haber llegado al agente
    assert url_imagen not in prompt
    assert url_video not in prompt
    # Debe haber llegado el texto limpio extraído
    assert "Pasos preliminares para la configuración" in prompt
    assert "Continuar con la validación de credenciales" in prompt
    # Se deben haber poblado los recursos en el borrador
    assert len(borrador.recursos) > 0


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
    """Riesgo 4: borrador.texto no se puede asignar directamente y se deriva de texto_limpio y recursos."""
    from baco.server.services.orquestador.recursos_service import componer_texto_publicable

    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Título de prueba",
        texto_limpio="Texto inicial de prueba para la composición de borrador.",
        conforme=True,
    )

    # 1. borrador.texto coincide exactamente con componer_texto_publicable
    assert borrador.texto == componer_texto_publicable(borrador.texto_limpio, borrador.recursos)

    # 2. Intentar asignar borrador.texto debe fallar (no es un campo asignable)
    with pytest.raises((AttributeError, TypeError)):
        borrador.texto = "Intento de asignación manual directa"

    # 3. Al cambiar texto_limpio, borrador.texto se actualiza inmediatamente
    borrador.texto_limpio = "Texto modificado paso a paso sin reasignar borrador.texto."
    assert borrador.texto == componer_texto_publicable(borrador.texto_limpio, borrador.recursos)
    assert "Texto modificado paso a paso" in borrador.texto

    # 4. Al agregar un recurso, borrador.texto se actualiza inmediatamente reflejando el recurso
    nuevo_rec = Recurso(
        id="rec_1",
        tipo="imagen",
        nombre="Diagrama de flujo",
        referencia="https://bc.finneg.com/uploads/diagrama.png",
        orden=0,
    )
    borrador.agregar_multimedia(nuevo_rec)
    assert borrador.texto == componer_texto_publicable(borrador.texto_limpio, borrador.recursos)
    assert "https://bc.finneg.com/uploads/diagrama.png" in borrador.texto

