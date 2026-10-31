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
    avanzar_a_metadatos_o_revision,
    construir_respuesta,
    extraer_tipo_plantilla,
)


PREFIJO_VOLVER_REVISION = "Volvemos a la revisión del borrador. "


@dataclass(frozen=True)
class ReglaRetroceso:
    """Representa una entrada en la tabla de retroceso para (estado, modo)."""
    estado_destino: Union[EstadoFlujo, Callable[[SesionChat], EstadoFlujo]]
    restaurar: Callable[[SesionChat], None]
    construir_respuesta: Callable[[SesionChat], ChatOrquestadorResponse]

def _restaurar_decision_titulo(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("DECISION_TITULO")
    sesion.coincidencias = []


def _restaurar_esperando_texto(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("ESPERANDO_TEXTO")
    sesion.texto_en_edicion = ""


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
        # Vuelve a la revisión intermedia (edición y skills) conservando la plantilla.
        b.revision_intermedia = True
        b.texto_base_revision_final = None


def _restaurar_revision_borrador(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("REVISION_BORRADOR")
    sesion.limpiar_fallos("SUBSANANDO_BORRADOR")


def _restaurar_revision_borrador_nuevo(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("REVISION_BORRADOR")
    sesion.limpiar_fallos("SUBSANANDO_BORRADOR")
    # Desde la revisión intermedia se vuelve a elegir plantilla reseteando tipo_plantilla.
    if sesion.borrador and sesion.borrador.revision_intermedia:
        sesion.borrador.tipo_plantilla = None

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
    b = sesion.borrador
    if b and b.metadatos_anteriores:
        return EstadoFlujo.REVISION_BORRADOR
    return EstadoFlujo.ESPERANDO_TEXTO


def _resp_esperando_plantilla(sesion: SesionChat) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if b and b.metadatos_anteriores:
        return avanzar_a_metadatos_o_revision(sesion)
    return construir_respuesta(
        sesion,
        MSG_VOLVER_TEXTO_ACTUALIZADO,
        ["confirmar_texto", "volver"],
    )


def _destino_esperando_metadatos(sesion: SesionChat) -> EstadoFlujo:
    b = sesion.borrador
    if b and b.tipo_plantilla:
        return EstadoFlujo.REVISION_BORRADOR
    return EstadoFlujo.ESPERANDO_PLANTILLA


def _resp_esperando_metadatos(sesion: SesionChat) -> ChatOrquestadorResponse:
    if sesion.estado == EstadoFlujo.ESPERANDO_PLANTILLA:
        return construir_respuesta(sesion, MSG_VOLVER_PLANTILLA, OPCIONES_PLANTILLAS)
    return avanzar_a_metadatos_o_revision(sesion, PREFIJO_VOLVER_REVISION)


def _destino_revision_borrador_nuevo(sesion: SesionChat) -> EstadoFlujo:
    b = sesion.borrador
    if b and b.revision_intermedia:
        return EstadoFlujo.ESPERANDO_PLANTILLA
    return EstadoFlujo.ESPERANDO_METADATOS


def _resp_revision_borrador_nuevo(sesion: SesionChat) -> ChatOrquestadorResponse:
    if sesion.estado == EstadoFlujo.ESPERANDO_PLANTILLA:
        return construir_respuesta(sesion, MSG_VOLVER_PLANTILLA, OPCIONES_PLANTILLAS)
    return construir_respuesta(sesion, MSG_VOLVER_METADATOS, ["volver"])


def _resp_revision_borrador_enriquecimiento(sesion: SesionChat) -> ChatOrquestadorResponse:
    elegido = sesion.coincidencias[0] if sesion.coincidencias else None
    es_serie = elegido and elegido.tipo_coincidencia == "serie"
    ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
    return construir_respuesta(sesion, MSG_VOLVER_ENRIQUECER_O_DESCARTAR, ops)


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
        restaurar=_restaurar_esperando_texto,
        construir_respuesta=_resp_esperando_texto_enriquecimiento,
    ),

    # DECISION_TEXTO: vuelve a ESPERANDO_TEXTO
    (EstadoFlujo.DECISION_TEXTO, None): ReglaRetroceso(
        estado_destino=EstadoFlujo.ESPERANDO_TEXTO,
        restaurar=_restaurar_decision_texto,
        construir_respuesta=_resp_decision_texto,
    ),

    # ESPERANDO_PLANTILLA: con metadatos_anteriores restaura y va a REVISION_BORRADOR;
    # sin metadatos_anteriores regresa a ESPERANDO_TEXTO.
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

    # ESPERANDO_METADATOS: vuelve a la revisión intermedia (REVISION_BORRADOR) conservando
    # tipo_plantilla; sin plantilla elegida vuelve a ESPERANDO_PLANTILLA.
    (EstadoFlujo.ESPERANDO_METADATOS, None): ReglaRetroceso(
        estado_destino=_destino_esperando_metadatos,
        restaurar=_restaurar_esperando_metadatos,
        construir_respuesta=_resp_esperando_metadatos,
    ),

    # REVISION_BORRADOR (nuevo): desde la revisión intermedia vuelve a ESPERANDO_PLANTILLA
    # (reseteando tipo_plantilla); desde la revisión final vuelve a ESPERANDO_METADATOS.
    (EstadoFlujo.REVISION_BORRADOR, "nuevo"): ReglaRetroceso(
        estado_destino=_destino_revision_borrador_nuevo,
        restaurar=_restaurar_revision_borrador_nuevo,
        construir_respuesta=_resp_revision_borrador_nuevo,
    ),

    # REVISION_BORRADOR (enriquecimiento): vuelve a DECISION_TITULO
    (EstadoFlujo.REVISION_BORRADOR, "enriquecimiento"): ReglaRetroceso(
        estado_destino=EstadoFlujo.DECISION_TITULO,
        restaurar=_restaurar_revision_borrador,
        construir_respuesta=_resp_revision_borrador_enriquecimiento,
    ),

    # SUBSANANDO_BORRADOR: idéntico a REVISION_BORRADOR
    (EstadoFlujo.SUBSANANDO_BORRADOR, "nuevo"): ReglaRetroceso(
        estado_destino=_destino_revision_borrador_nuevo,
        restaurar=_restaurar_revision_borrador_nuevo,
        construir_respuesta=_resp_revision_borrador_nuevo,
    ),
    (EstadoFlujo.SUBSANANDO_BORRADOR, "enriquecimiento"): ReglaRetroceso(
        estado_destino=EstadoFlujo.DECISION_TITULO,
        restaurar=_restaurar_revision_borrador,
        construir_respuesta=_resp_revision_borrador_enriquecimiento,
    ),
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
