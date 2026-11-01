import pytest

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    CoincidenciaArticulo,
    EstadoFlujo,
    Recurso,
)
from baco.server.services.orquestador.retroceso import resetear_enriquecimiento_descartado
from baco.server.services.orquestador.sesion import SESIONES, SesionChat
from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos

TEXTO_ORIGINAL_DISCOURSE = (
    "Contenido completo del artículo existente en Discourse recuperado de la base de datos "
    "con explicaciones previas del procedimiento de facturación."
)
TEXTO_PROPIO_USUARIO = "Mi propio aporte redactado manualmente en el editor para este tema."


@pytest.fixture(autouse=True)
def limpiar_sesiones():
    SESIONES.clear()
    limpiar_cache_catalogos()
    yield
    SESIONES.clear()
    limpiar_cache_catalogos()


def _crear_sesion_enriquecimiento(
    articulo_id=101,
    texto_editor=TEXTO_PROPIO_USUARIO,
    texto_cargado=TEXTO_ORIGINAL_DISCOURSE,
    coincidencias=None,
):
    if coincidencias is None:
        coincidencias = [
            CoincidenciaArticulo(
                id=articulo_id,
                titulo="Artículo Existente en Discourse",
                url=f"https://bc.finneg.com/t/{articulo_id}",
                tipo_coincidencia="exacto",
            )
        ]
    borrador = BorradorSesion(
        modo="enriquecimiento",
        articulo_original_id=articulo_id,
        titulo="Artículo Existente en Discourse",
        bloques_texto=[texto_cargado],
        texto_limpio=texto_cargado,
        texto_editor=texto_editor,
        categoria_id=5,
        categoria_nombre="Ventas",
        tipo_plantilla="instructivo",
        tags=["instructivo", "ventas"],
    )
    sesion = SesionChat(
        session_id=f"test-reseteo-{articulo_id}",
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo="Artículo Existente en Discourse",
        texto=texto_cargado,
        texto_limpio=texto_cargado,
        texto_editor=texto_editor,
        bloques_texto=[texto_cargado],
        borrador=borrador,
        coincidencias=list(coincidencias),
        articulos_descartados_ids=[],
        categoria_id=5,
        categoria_nombre="Ventas",
        tags=["instructivo", "ventas"],
    )
    SESIONES[sesion.session_id] = sesion
    return sesion


def test_es_un_tema_distinto_descarta_y_conserva_texto_propio():
    """Verifica que 'es un tema distinto' (agregar_a_descartados=True) ponga borrador en None,
    agregue los IDs a articulos_descartados_ids, no conserve el texto del artículo original
    y preserve el texto propio de la persona (texto_editor)."""
    sesion = _crear_sesion_enriquecimiento(
        articulo_id=101,
        texto_editor=TEXTO_PROPIO_USUARIO,
        texto_cargado=TEXTO_ORIGINAL_DISCOURSE,
    )
    sesion.coincidencias.append(
        CoincidenciaArticulo(id=102, titulo="Otra coincidencia", url="https://bc.finneg.com/t/102")
    )

    res_texto = resetear_enriquecimiento_descartado(sesion, agregar_a_descartados=True)

    assert sesion.borrador is None
    assert 101 in sesion.articulos_descartados_ids
    assert 102 in sesion.articulos_descartados_ids
    assert sesion.coincidencias == []
    # El texto cargado de Discourse NO debe quedar en texto_limpio ni bloques_texto
    assert TEXTO_ORIGINAL_DISCOURSE not in sesion.texto_limpio
    assert TEXTO_ORIGINAL_DISCOURSE not in sesion.bloques_texto
    # El texto propio se conserva
    assert sesion.texto_limpio == TEXTO_PROPIO_USUARIO
    assert sesion.bloques_texto == [TEXTO_PROPIO_USUARIO]
    assert sesion.texto == TEXTO_PROPIO_USUARIO
    assert res_texto == TEXTO_PROPIO_USUARIO


def test_volver_desde_enriquecimiento_comportamiento_original():
    """Verifica que 'volver' desde enriquecimiento (agregar_a_descartados=False) deje borrador None,
    articulos_descartados_ids vacío y vacíe todo el texto (comportamiento original)."""
    sesion = _crear_sesion_enriquecimiento(
        articulo_id=202,
        texto_editor=TEXTO_PROPIO_USUARIO,
    )
    sesion.articulos_descartados_ids = [999]

    res_texto = resetear_enriquecimiento_descartado(sesion, agregar_a_descartados=False)

    assert sesion.borrador is None
    assert sesion.articulos_descartados_ids == []
    assert sesion.texto == ""
    assert sesion.texto_limpio == ""
    assert sesion.texto_en_edicion == ""
    assert sesion.bloques_texto == []
    assert res_texto == ""


def test_sin_texto_propio_vacia_todos_los_campos_de_texto():
    """Verifica que al descartar sin texto propio, texto, texto_limpio, texto_en_edicion y bloques_texto queden vacíos."""
    sesion = _crear_sesion_enriquecimiento(
        articulo_id=303,
        texto_editor="",
        texto_cargado=TEXTO_ORIGINAL_DISCOURSE,
    )
    sesion.borrador.texto_editor = ""
    sesion.texto_en_edicion = ""

    res_texto = resetear_enriquecimiento_descartado(sesion, agregar_a_descartados=True)

    assert sesion.texto == ""
    assert sesion.texto_limpio == ""
    assert sesion.texto_en_edicion == ""
    assert sesion.bloques_texto == []
    assert res_texto == ""


def test_reseteo_no_toca_recursos_orden_posiciones_base_limpio_ni_metadatos():
    """Verifica que resetear_enriquecimiento_descartado no altere recursos, orden_multimedia, posiciones,
    texto_base_limpio ni metadatos de la sesión."""
    sesion = _crear_sesion_enriquecimiento(articulo_id=404)
    recurso_mock = Recurso(
        id="rec1",
        numero=1,
        tipo="imagen",
        nombre="foto.png",
        alt="Captura de pantalla",
        posicion=0,
    )
    sesion.recursos = {"rec1": recurso_mock}
    sesion.orden_multimedia = [1]
    sesion.posiciones = [0]
    sesion.texto_base_limpio = "Texto base previamente extraído"
    sesion.categoria_id = 12
    sesion.categoria_nombre = "Finanzas"
    sesion.tags = ["instructivo", "finanzas"]

    resetear_enriquecimiento_descartado(sesion, agregar_a_descartados=True)

    assert sesion.recursos == {"rec1": recurso_mock}
    assert sesion.orden_multimedia == [1]
    assert sesion.posiciones == [0]
    assert sesion.texto_base_limpio == "Texto base previamente extraído"
    assert sesion.categoria_id == 12
    assert sesion.categoria_nombre == "Finanzas"
    assert sesion.tags == ["instructivo", "finanzas"]


def test_camino_coincidencia_titulo_y_texto_mismo_resultado():
    """Verifica que el reseteo produzca el mismo resultado tanto si se llegó por coincidencia de título como de texto."""
    # Camino 1: coincidencia por título
    sesion_tit = _crear_sesion_enriquecimiento(
        articulo_id=501,
        texto_editor="Texto redactado camino título",
        texto_cargado="Texto existente por título",
    )
    res_tit = resetear_enriquecimiento_descartado(sesion_tit, agregar_a_descartados=True)

    # Camino 2: coincidencia por texto semántico
    sesion_txt = _crear_sesion_enriquecimiento(
        articulo_id=502,
        texto_editor="Texto redactado camino texto",
        texto_cargado="Texto existente por semántica",
    )
    res_txt = resetear_enriquecimiento_descartado(sesion_txt, agregar_a_descartados=True)

    assert sesion_tit.borrador is None
    assert sesion_txt.borrador is None
    assert 501 in sesion_tit.articulos_descartados_ids
    assert 502 in sesion_txt.articulos_descartados_ids
    assert sesion_tit.texto_limpio == "Texto redactado camino título"
    assert sesion_txt.texto_limpio == "Texto redactado camino texto"
    assert res_tit == "Texto redactado camino título"
    assert res_txt == "Texto redactado camino texto"


def test_modo_no_enriquecimiento_conserva_texto_con_respaldos_originales():
    """Verifica que en modo nuevo (no enriquecimiento), el texto de la persona se conserve
    utilizando los respaldos originales de la sesión (texto_limpio, texto_en_edicion, texto)."""
    borrador_nuevo = BorradorSesion(
        modo="nuevo",
        titulo="Título Nuevo",
        bloques_texto=["Texto en borrador nuevo"],
        texto_limpio="Texto en borrador nuevo",
        tipo_plantilla="instructivo",
        tags=["instructivo"],
    )
    sesion = SesionChat(
        session_id="test-modo-nuevo",
        estado=EstadoFlujo.ESPERANDO_TEXTO,
        titulo="Título Nuevo",
        texto="Texto original de sesión",
        texto_limpio="Texto limpio original de sesión",
        texto_en_edicion="Texto en edición original",
        borrador=borrador_nuevo,
    )

    res_texto = resetear_enriquecimiento_descartado(sesion, agregar_a_descartados=True)

    assert sesion.borrador is None
    assert sesion.texto_limpio == "Texto limpio original de sesión"
    assert sesion.texto == "Texto limpio original de sesión"
    assert sesion.bloques_texto == ["Texto limpio original de sesión"]
    assert res_texto == "Texto limpio original de sesión"
