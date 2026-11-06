"""
Módulo de retroceso unificado para el orquestador.

Define la tabla de transiciones y funciones de restauración de datos para
la acción "volver" según el par (estado, modo), preservando exactamente
el comportamiento actual del flujo.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple, Union

from baco.server.schemas.chat_orquestado import (
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.services.orquestador.mensajes import (
    MSG_VOLVER_ENRIQUECER_O_DESCARTAR,
    MSG_VOLVER_METADATOS,
    MSG_VOLVER_PLANTILLA,
    MSG_VOLVER_TEXTO,
    MSG_VOLVER_TEXTO_ACTUALIZADO,
    MSG_VOLVER_TITULO,
    OPCIONES_ENRIQUECER_CONTINUAR,
    OPCIONES_ENRIQUECER_DESCARTAR,
    OPCIONES_PLANTILLAS,
    OPCIONES_SERIE_DECISION,
    msg_coincidencia,
)
from baco.server.services.orquestador.sesion import SesionChat
from baco.server.services.orquestador.validaciones import (
    DICCIONARIO_OFICIAL_CATEGORIAS,
    construir_respuesta,
    extraer_tipo_plantilla,
    validar_borrador,
)


PREFIJO_VOLVER_REVISION = "Volvemos a la revisión del borrador. "


@dataclass(frozen=True)
class ReglaRetroceso:
    """Representa una entrada en la tabla de retroceso para (estado, modo)."""
    estado_destino: Union[EstadoFlujo, Callable[[SesionChat], EstadoFlujo]]
    restaurar: Callable[[SesionChat], None]
    construir_respuesta: Callable[[SesionChat], ChatOrquestadorResponse]

def resetear_enriquecimiento_descartado(
    sesion: SesionChat,
    agregar_a_descartados: bool = False,
    texto_extra: Optional[str] = None,
) -> str:
    """
    Restaura el estado de la sesión al descartar o volver tras haber cargado
    un artículo para enriquecer (caminos de coincidencia de título y de texto).
    """
    if agregar_a_descartados:
        if sesion.borrador is not None and sesion.borrador.articulo_original_id:
            if sesion.borrador.articulo_original_id not in sesion.articulos_descartados_ids:
                sesion.articulos_descartados_ids.append(sesion.borrador.articulo_original_id)
        for c in sesion.coincidencias:
            if c.id and c.id not in sesion.articulos_descartados_ids:
                sesion.articulos_descartados_ids.append(c.id)
        sesion.coincidencias = []

        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            texto_propio = (
                (texto_extra or "").strip()
                or (sesion.texto_en_edicion or "").strip()
                or (sesion.texto_editor or "").strip()
                or (sesion.borrador.texto_editor or "").strip()
            )
        else:
            texto_propio = (
                (texto_extra or "").strip()
                or (sesion.texto_limpio or "").strip()
                or (sesion.texto_en_edicion or "").strip()
                or (sesion.texto or "").strip()
            )
    else:
        # Comportamiento original de "Volver" en _restaurar_esperando_texto (L58)
        sesion.articulos_descartados_ids = []
        texto_propio = ""

    sesion.borrador = None
    sesion.contenido_adicional = []
    sesion.limpiar_fallos("ESPERANDO_TEXTO")

    if texto_propio:
        sesion.texto = texto_propio
        sesion.texto_limpio = texto_propio
        sesion.texto_en_edicion = texto_propio
        sesion.bloques_texto = [texto_propio]
    else:
        sesion.texto = ""
        sesion.texto_limpio = ""
        sesion.texto_en_edicion = ""
        sesion.bloques_texto = []

    return texto_propio


def _restaurar_esperando_texto_enriquecimiento(sesion: SesionChat) -> None:
    resetear_enriquecimiento_descartado(sesion, agregar_a_descartados=False)


def _restaurar_decision_titulo(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("DECISION_TITULO")
    sesion.coincidencias = []


def _restaurar_esperando_texto(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("ESPERANDO_TEXTO")
    sesion.texto_en_edicion = ""
    sesion.texto = ""
    sesion.texto_limpio = ""
    sesion.articulos_descartados_ids = []


def _restaurar_decision_texto(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("DECISION_TEXTO")
    sesion.coincidencias = []


def _restaurar_esperando_plantilla(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("ESPERANDO_PLANTILLA")
    b = sesion.borrador
    if b and b.metadatos_anteriores:
        b.metadatos_heredados_revisados = False
        sesion.metadatos_heredados_revisados = False
        ant = b.metadatos_anteriores
        b.categoria_id = ant.get("categoria_id")
        b.categoria_nombre = ant.get("categoria_nombre") or (
            DICCIONARIO_OFICIAL_CATEGORIAS.get(b.categoria_id) if b.categoria_id else None
        )
        b.tags = list(ant.get("tags") or [])
        b.tipo_plantilla = extraer_tipo_plantilla(b.tags)
        sesion.categoria_id = b.categoria_id
        sesion.categoria_nombre = b.categoria_nombre
        sesion.tags = list(b.tags)


def _restaurar_esperando_metadatos(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("ESPERANDO_METADATOS")
    b = sesion.borrador
    if b and b.tipo_plantilla:
        # Vuelve a REVISION_TIPO (edición y skills) conservando la plantilla.
        b.texto_base_revision_final = None


def _restaurar_skill_pendiente(sesion: SesionChat) -> None:
    """Descarta el resultado de la skill pendiente y restaura el texto_original."""
    b = sesion.borrador
    if b is not None and (
        getattr(b, "resultado_skill_pendiente", False)
        or getattr(b, "skill_pendiente", None)
        or getattr(b, "resultado_skill_desactualizado", False)
    ):
        texto_orig = (
            getattr(b, "texto_original", None)
            or getattr(sesion, "texto_original", None)
            or getattr(b, "texto_editor", None)
            or getattr(sesion, "texto_editor", None)
            or getattr(b, "texto_base_limpio", None)
            or getattr(sesion, "texto_limpio", None)
            or ""
        ).strip()
        bloques_orig = [texto_orig] if texto_orig else []
        sesion.actualizar_contenido_borrador(
            bloques_texto=bloques_orig,
            texto_base_limpio=texto_orig,
            texto_editor=texto_orig,
            texto_original=texto_orig,
            resultado_skill_desactualizado=False,
            resultado_skill_pendiente=False,
        )
        b.skill_pendiente = None



def _restaurar_revision_tipo(sesion: SesionChat) -> None:
    sesion.limpiar_fallos()
    _restaurar_skill_pendiente(sesion)
    # Se vuelve a elegir plantilla reseteando tipo_plantilla.
    if sesion.borrador:
        sesion.borrador.tipo_plantilla = None


def _restaurar_revision_metadatos(sesion: SesionChat) -> None:
    sesion.limpiar_fallos()
    _restaurar_skill_pendiente(sesion)

def _resp_decision_titulo(sesion: SesionChat) -> ChatOrquestadorResponse:
    return construir_respuesta(sesion, MSG_VOLVER_TITULO, [])


def _resp_esperando_texto_nuevo(sesion: SesionChat) -> ChatOrquestadorResponse:
    return construir_respuesta(sesion, MSG_VOLVER_TITULO, [])


def _resp_esperando_texto_enriquecimiento(sesion: SesionChat) -> ChatOrquestadorResponse:
    elegido = sesion.coincidencias[0] if sesion.coincidencias else None
    es_semantico = any(getattr(c, "tipo_coincidencia", "") == "semantico" for c in sesion.coincidencias)
    if es_semantico:
        mensaje = (
            sesion.coincidencias[0].mensaje
            if (sesion.coincidencias and hasattr(sesion.coincidencias[0], "mensaje"))
            else "Coincidencia por contenido"
        )
        return construir_respuesta(
            sesion,
            msg_coincidencia(mensaje, elegido.titulo if elegido else "", elegido.url if elegido else ""),
            OPCIONES_ENRIQUECER_CONTINUAR,
        )
    es_serie = elegido and elegido.tipo_coincidencia == "serie"
    ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
    return construir_respuesta(sesion, MSG_VOLVER_ENRIQUECER_O_DESCARTAR, ops)


def _destino_esperando_texto_enriquecimiento(sesion: SesionChat) -> EstadoFlujo:
    if any(getattr(c, "tipo_coincidencia", "") == "semantico" for c in sesion.coincidencias):
        return EstadoFlujo.DECISION_TEXTO
    return EstadoFlujo.DECISION_TITULO


def _resp_decision_texto(sesion: SesionChat) -> ChatOrquestadorResponse:
    return construir_respuesta(sesion, MSG_VOLVER_TEXTO, ["volver"])


def _destino_esperando_plantilla(sesion: SesionChat) -> EstadoFlujo:
    # Convergencia: desde el paso 1 del troncal se vuelve al paso de texto, en todos los flujos.
    return EstadoFlujo.ESPERANDO_TEXTO


def _resp_esperando_plantilla(sesion: SesionChat) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if b and b.modo == "enriquecimiento":
        from baco.server.services.orquestador.mensajes import obtener_ayuda_contextual
        msg, ops = obtener_ayuda_contextual(sesion)
        return construir_respuesta(sesion, msg, ops)
    return construir_respuesta(
        sesion,
        MSG_VOLVER_TEXTO_ACTUALIZADO,
        ["confirmar_texto", "volver"],
    )


def _destino_esperando_metadatos(sesion: SesionChat) -> EstadoFlujo:
    b = sesion.borrador
    if b and b.tipo_plantilla:
        return EstadoFlujo.REVISION_TIPO
    return EstadoFlujo.ESPERANDO_PLANTILLA


def _resp_esperando_metadatos(sesion: SesionChat) -> ChatOrquestadorResponse:
    if sesion.estado == EstadoFlujo.ESPERANDO_PLANTILLA:
        return construir_respuesta(sesion, MSG_VOLVER_PLANTILLA, OPCIONES_PLANTILLAS)
    msg, ops = validar_borrador(sesion, PREFIJO_VOLVER_REVISION)
    return construir_respuesta(sesion, msg, ops)


def _resp_revision_tipo(sesion: SesionChat) -> ChatOrquestadorResponse:
    return construir_respuesta(sesion, MSG_VOLVER_PLANTILLA, OPCIONES_PLANTILLAS)


def _resp_revision_metadatos(sesion: SesionChat) -> ChatOrquestadorResponse:
    return construir_respuesta(sesion, MSG_VOLVER_METADATOS, ["volver"])



# ==============================================================================
# Tabla de retroceso por (estado, modo)
# ==============================================================================

TABLA_RETROCESO: Dict[Tuple[EstadoFlujo, Optional[str]], ReglaRetroceso] = {
    # DECISION_TITULO: vuelve a ESPERANDO_TITULO
    (EstadoFlujo.DECISION_TITULO, None): ReglaRetroceso(
        estado_destino=EstadoFlujo.ESPERANDO_TITULO,
        restaurar=_restaurar_decision_titulo,
        construir_respuesta=_resp_decision_titulo,
    ),

    # ESPERANDO_TEXTO (nuevo / sin borrador): vuelve a ESPERANDO_TITULO
    (EstadoFlujo.ESPERANDO_TEXTO, "nuevo"): ReglaRetroceso(
        estado_destino=EstadoFlujo.ESPERANDO_TITULO,
        restaurar=_restaurar_esperando_texto,
        construir_respuesta=_resp_esperando_texto_nuevo,
    ),
    (EstadoFlujo.ESPERANDO_TEXTO, None): ReglaRetroceso(
        estado_destino=EstadoFlujo.ESPERANDO_TITULO,
        restaurar=_restaurar_esperando_texto,
        construir_respuesta=_resp_esperando_texto_nuevo,
    ),

    # ESPERANDO_TEXTO (enriquecimiento): vuelve a DECISION_TEXTO (semántico) o DECISION_TITULO
    (EstadoFlujo.ESPERANDO_TEXTO, "enriquecimiento"): ReglaRetroceso(
        estado_destino=_destino_esperando_texto_enriquecimiento,
        restaurar=_restaurar_esperando_texto_enriquecimiento,
        construir_respuesta=_resp_esperando_texto_enriquecimiento,
    ),

    # DECISION_TEXTO: vuelve a ESPERANDO_TEXTO
    (EstadoFlujo.DECISION_TEXTO, None): ReglaRetroceso(
        estado_destino=EstadoFlujo.ESPERANDO_TEXTO,
        restaurar=_restaurar_decision_texto,
        construir_respuesta=_resp_decision_texto,
    ),

    # ESPERANDO_PLANTILLA: vuelve siempre a ESPERANDO_TEXTO; con metadatos_anteriores
    # además restaura los heredados (se vuelven a confirmar en ESPERANDO_METADATOS).
    (EstadoFlujo.ESPERANDO_PLANTILLA, "nuevo"): ReglaRetroceso(
        estado_destino=_destino_esperando_plantilla,
        restaurar=_restaurar_esperando_plantilla,
        construir_respuesta=_resp_esperando_plantilla,
    ),
    (EstadoFlujo.ESPERANDO_PLANTILLA, "enriquecimiento"): ReglaRetroceso(
        estado_destino=_destino_esperando_plantilla,
        restaurar=_restaurar_esperando_plantilla,
        construir_respuesta=_resp_esperando_plantilla,
    ),
    (EstadoFlujo.ESPERANDO_PLANTILLA, None): ReglaRetroceso(
        estado_destino=_destino_esperando_plantilla,
        restaurar=_restaurar_esperando_plantilla,
        construir_respuesta=_resp_esperando_plantilla,
    ),

    # ESPERANDO_METADATOS: vuelve a REVISION_TIPO conservando
    # tipo_plantilla; sin plantilla elegida vuelve a ESPERANDO_PLANTILLA.
    (EstadoFlujo.ESPERANDO_METADATOS, None): ReglaRetroceso(
        estado_destino=_destino_esperando_metadatos,
        restaurar=_restaurar_esperando_metadatos,
        construir_respuesta=_resp_esperando_metadatos,
    ),

    # REVISION_TIPO: vuelve a ESPERANDO_PLANTILLA reseteando tipo_plantilla (cualquier modo).
    (EstadoFlujo.REVISION_TIPO, None): ReglaRetroceso(
        estado_destino=EstadoFlujo.ESPERANDO_PLANTILLA,
        restaurar=_restaurar_revision_tipo,
        construir_respuesta=_resp_revision_tipo,
    ),

    # REVISION_METADATOS: vuelve a ESPERANDO_METADATOS conservando tipo_plantilla (cualquier modo).
    (EstadoFlujo.REVISION_METADATOS, None): ReglaRetroceso(
        estado_destino=EstadoFlujo.ESPERANDO_METADATOS,
        restaurar=_restaurar_revision_metadatos,
        construir_respuesta=_resp_revision_metadatos,
    ),
    # EDICION_FINAL no tiene retroceso (contrato paso 5).
}


# ==============================================================================
# Función pública única de retroceso
# ==============================================================================

def retroceder(sesion: SesionChat) -> ChatOrquestadorResponse:
    """
    Ejecuta el retroceso del flujo para la sesión consultando TABLA_RETROCESO.
    Restaura los datos correspondientes, actualiza el estado de destino y
    construye la respuesta del orquestador.
    """
    modo = sesion.borrador.modo if sesion.borrador else "nuevo"
    regla = TABLA_RETROCESO.get((sesion.estado, modo)) or TABLA_RETROCESO.get((sesion.estado, None))
    if regla is None:
        raise ValueError(
            f"No existe regla de retroceso definida para estado={sesion.estado} y modo={modo}"
        )

    regla.restaurar(sesion)
    destino = regla.estado_destino(sesion) if callable(regla.estado_destino) else regla.estado_destino
    sesion.estado = destino
    return regla.construir_respuesta(sesion)
