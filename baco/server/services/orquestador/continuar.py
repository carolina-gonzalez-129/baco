"""
Módulo de avance unificado para el orquestador.

Define la tabla de transiciones declaradas, la compuerta de validación previa
al avance y las funciones de respuesta para el troncal convergente del flujo
(igual para nuevo, enriquecer, actualizar y "Es un tema distinto"):
  Paso 1: Pedir tipo de plantilla (ESPERANDO_PLANTILLA).
  Paso 2: Ofrecer la skill de plantillas, opcional (REVISION_BORRADOR, revision_intermedia=True).
  Paso 3: Pedir tags y categoría (ESPERANDO_METADATOS).
  Paso 4: Ofrecer el auditor, opcional (REVISION_BORRADOR, revision_intermedia=False).
  Paso 5: Edición final (EDICION_FINAL) y Finalizar.

Este módulo NO ejecuta skills: las skills solo corren cuando la persona toca
"Aplicar plantilla" o "Auditar" (handlers.py -> edicion.ejecutar_skill).
"""

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple, Union

from baco.server.schemas.chat_orquestado import (
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.services.orquestador.mensajes import (
    MSG_BORRADOR_FINALIZADO,
    MSG_RECHAZADO,
    OPCIONES_FINALIZADO,
    OPCIONES_PLANTILLAS,
    OPCIONES_REINICIAR,
    PREFIJO_ERROR_CONFORMIDAD,
    PREFIJO_METADATOS_REGISTRADOS,
    msg_pedir_metadatos,
    msg_pedir_plantilla,
)
from baco.server.services.orquestador.sesion import SesionChat
from baco.server.services.validar_articulo import sanitizar_borrador
from baco.server.services.orquestador.validaciones import (
    DICCIONARIO_OFICIAL_CATEGORIAS,
    combinar_tags,
    construir_respuesta,
    extraer_tipo_plantilla,
    validar_borrador,
    verificar_compuerta_avance,
)


@dataclass(frozen=True)
class ReglaContinuar:
    """Representa una regla declarada de avance en el troncal del flujo."""
    estado_destino: Union[EstadoFlujo, Callable[[SesionChat], EstadoFlujo]]
    avanzar: Callable[[SesionChat], None]
    construir_respuesta: Callable[[SesionChat, str, Optional[str]], ChatOrquestadorResponse]


# ==============================================================================
# Funciones de responsabilidad única por paso del troncal
# ==============================================================================

# --- Paso 1: Pedir plantilla (o aviso de metadatos heredados al inicio) ---

def _destino_paso_plantilla(sesion: SesionChat) -> EstadoFlujo:
    b = sesion.borrador
    if b and b.metadatos_anteriores and not b.metadatos_heredados_revisados:
        return EstadoFlujo.REVISION_BORRADOR
    plantilla = (b.tipo_plantilla or sesion.tipo_plantilla or extraer_tipo_plantilla(b.tags)) if b else None
    if plantilla:
        return EstadoFlujo.REVISION_BORRADOR
    return EstadoFlujo.ESPERANDO_PLANTILLA


def _avanzar_paso_plantilla(sesion: SesionChat) -> None:
    b = sesion.borrador
    if not b:
        return
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id
    if b.metadatos_anteriores and not b.metadatos_heredados_revisados:
        b.revision_intermedia = True
        b.texto_base_revision_final = None
        return
    plantilla = b.tipo_plantilla or sesion.tipo_plantilla or extraer_tipo_plantilla(b.tags)
    if plantilla:
        b.tipo_plantilla = plantilla
        sesion.tipo_plantilla = plantilla
        b.tags = combinar_tags(plantilla, b.tags)
        sesion.tags = list(b.tags)
        b.revision_intermedia = True
        b.texto_base_revision_final = None


def _resp_paso_plantilla(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if b and b.metadatos_anteriores and not b.metadatos_heredados_revisados:
        cat_nom = b.metadatos_anteriores.get("categoria_nombre") or (
            DICCIONARIO_OFICIAL_CATEGORIAS.get(
                b.metadatos_anteriores.get("categoria_id"),
                f"Categoría {b.metadatos_anteriores.get('categoria_id')}",
            )
            if b.metadatos_anteriores.get("categoria_id")
            else "Sin categoría"
        )
        tags_str = ", ".join(b.metadatos_anteriores.get("tags") or []) or "ninguna"
        validar_borrador(sesion, prefijo)
        aviso_meta = f"Este artículo ya tenía la categoría {cat_nom} y las etiquetas: {tags_str}. ¿Querés mantenerlas?"
        # El detalle de los metadatos heredados se muestra solo en el banner (aviso_metadatos_heredados).
        mensaje_espera = f"{prefijo}Revisá arriba la categoría y las etiquetas del artículo original. ¿Querés mantenerlas?".strip()
        ops = ["aceptar_metadatos", "rechazar_metadatos", "volver"]
        return construir_respuesta(
            sesion,
            mensaje_espera,
            ops,
            aviso_privacidad=aviso_privacidad,
            aviso_metadatos_heredados=aviso_meta,
        )

    if b and not b.tipo_plantilla:
        return construir_respuesta(
            sesion,
            msg_pedir_plantilla(prefijo),
            OPCIONES_PLANTILLAS,
            aviso_privacidad=aviso_privacidad,
        )

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_privacidad)


# --- Paso 2: Ofrecer la skill de plantillas (opcional) ---

def _avanzar_paso_revision_intermedia(sesion: SesionChat) -> None:
    b = sesion.borrador
    if not b:
        return
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id
    plantilla = b.tipo_plantilla or sesion.tipo_plantilla or extraer_tipo_plantilla(b.tags)
    if plantilla:
        b.tipo_plantilla = plantilla
        sesion.tipo_plantilla = plantilla
        b.tags = combinar_tags(plantilla, b.tags)
        sesion.tags = list(b.tags)
    b.revision_intermedia = True
    b.texto_base_revision_final = None



def _resp_paso_revision_intermedia(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_privacidad)


# --- Paso 3: Pedir tags y categoría desde revisión intermedia ---

def _destino_paso_metadatos(sesion: SesionChat) -> EstadoFlujo:
    b = sesion.borrador
    if b and (b.categoria_id is None or len(b.tags) < 2):
        return EstadoFlujo.ESPERANDO_METADATOS
    return EstadoFlujo.REVISION_BORRADOR


def _avanzar_paso_metadatos(sesion: SesionChat) -> None:
    b = sesion.borrador
    if not b:
        return
    b.revision_intermedia = False
    b.texto_base_revision_final = b.texto_limpio
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id


def _resp_paso_metadatos(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if sesion.estado == EstadoFlujo.ESPERANDO_METADATOS:
        return construir_respuesta(sesion, msg_pedir_metadatos(b.tipo_plantilla or ""), ["volver"])
    msg, ops = validar_borrador(sesion, prefijo or PREFIJO_METADATOS_REGISTRADOS)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_privacidad)


# --- Paso 4: Ofrecer el auditor (opcional) ---

def _avanzar_paso_revision_final(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("ESPERANDO_METADATOS")
    b = sesion.borrador
    if not b:
        return
    b.revision_intermedia = False
    b.texto_base_revision_final = b.texto_limpio
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id


def _resp_paso_revision_final(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    pref = prefijo or PREFIJO_METADATOS_REGISTRADOS
    msg, ops = validar_borrador(sesion, pref)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_privacidad)



def _avanzar_paso_edicion_final(sesion: SesionChat) -> None:
    sesion.limpiar_fallos("REVISION_BORRADOR")
    b = sesion.borrador
    if not b:
        return
    b.revision_intermedia = False
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id


def _resp_paso_edicion_final(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    from baco.server.services.orquestador.mensajes import MSG_EDICION_FINAL, OPCIONES_EDICION_FINAL
    msg = f"{prefijo}{MSG_EDICION_FINAL}".strip()
    return construir_respuesta(sesion, msg, OPCIONES_EDICION_FINAL, aviso_privacidad=aviso_privacidad)


def continuar_desde_revision(sesion: SesionChat) -> ChatOrquestadorResponse:
    """Avanza desde REVISION_BORRADOR (intermedia o final) al próximo paso del troncal."""
    return continuar(sesion)


def _avanzar_paso_finalizado(sesion: SesionChat) -> None:
    b = sesion.borrador
    if b is None:
        return
    # La adopción del resultado de skill pendiente la hace handlers.py antes de finalizar.
    b.metadatos_heredados_revisados = True
    sesion.metadatos_heredados_revisados = True
    limpio = sanitizar_borrador(texto=b.texto_limpio, titulo=b.titulo)
    titulo_conf = limpio["titulo_sanitizado"]
    bloques_conf = [
        sanitizar_borrador(texto=bl)["texto_sanitizado"].strip()
        for bl in b.bloques_texto
        if bl.strip()
    ]
    bloques_conf = [bl for bl in bloques_conf if bl]
    txt_conf_limpio = "\n\n".join(bloques_conf).strip()
    sesion.actualizar_contenido_borrador(
        titulo=titulo_conf,
        bloques_texto=bloques_conf,
        texto_base_limpio=txt_conf_limpio,
        texto_editor=txt_conf_limpio,
        texto_original=txt_conf_limpio,
    )
    b.finalizado = True
    sesion._aviso_privacidad_final = limpio.get("aviso_privacidad")


def _resp_paso_finalizado(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    aviso_priv = aviso_privacidad or getattr(sesion, "_aviso_privacidad_final", None)
    return construir_respuesta(
        sesion,
        MSG_BORRADOR_FINALIZADO,
        OPCIONES_FINALIZADO,
        aviso_privacidad=aviso_priv,
    )


def _registrar_finalizado(sesion: SesionChat) -> ChatOrquestadorResponse:
    """Registra la finalización del borrador aplicando sanitización silenciosa final si corresponde."""
    b = sesion.borrador
    if b is None:
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    if b.metadatos_anteriores and not b.metadatos_heredados_revisados:
        # Sin recursión: se vuelve a pedir la decisión sobre los metadatos heredados.
        return _resp_paso_plantilla(
            sesion, prefijo="Debés aceptar o rechazar los metadatos heredados antes de confirmar la finalización. "
        )

    if sesion.estado == EstadoFlujo.EDICION_FINAL:
        return continuar(sesion)

    _avanzar_paso_finalizado(sesion)
    sesion.estado = EstadoFlujo.FINALIZADO
    return _resp_paso_finalizado(sesion)


# ==============================================================================
# Gestión de metadatos heredados (variante como parámetro del troncal)
# ==============================================================================

def gestionar_metadatos_heredados(
    sesion: SesionChat, opcion: str
) -> Optional[ChatOrquestadorResponse]:
    """
    Aísla y gestiona la resolución de aceptar_metadatos / rechazar_metadatos
    en los flujos de enriquecer o actualizar.
    """
    b = sesion.borrador
    if not b or not b.metadatos_anteriores:
        return None

    if opcion in ("aceptar", "aceptar_metadatos"):
        b.metadatos_heredados_revisados = True
        sesion.metadatos_heredados_revisados = True
        _avanzar_paso_plantilla(sesion)
        destino = _destino_paso_plantilla(sesion)
        sesion.estado = destino
        return _resp_paso_plantilla(sesion, prefijo="Se confirmaron los metadatos de la versión anterior. ")

    if opcion in ("rechazar_metadatos",) or (
        opcion == "rechazar" and not b.metadatos_heredados_revisados
    ):
        b.metadatos_heredados_revisados = True
        sesion.metadatos_heredados_revisados = True
        b.tipo_plantilla = None
        b.categoria_id = None
        b.categoria_nombre = None
        b.tags = []
        sesion.categoria_id = None
        sesion.categoria_nombre = None
        sesion.tags = []
        _avanzar_paso_plantilla(sesion)
        destino = _destino_paso_plantilla(sesion)
        sesion.estado = destino
        return _resp_paso_plantilla(sesion, prefijo="Se descartaron los metadatos heredados. ")

    return None


# ==============================================================================
# Tabla declarada de avance por (estado, variante)
# ==============================================================================

TABLA_CONTINUAR: Dict[Tuple[EstadoFlujo, Optional[str]], ReglaContinuar] = {
    # Inicio del troncal desde texto (nuevo o enriquecimiento)
    (EstadoFlujo.ESPERANDO_TEXTO, None): ReglaContinuar(
        estado_destino=_destino_paso_plantilla,
        avanzar=_avanzar_paso_plantilla,
        construir_respuesta=_resp_paso_plantilla,
    ),
    (EstadoFlujo.DECISION_TEXTO, None): ReglaContinuar(
        estado_destino=_destino_paso_plantilla,
        avanzar=_avanzar_paso_plantilla,
        construir_respuesta=_resp_paso_plantilla,
    ),

    # Paso 1 -> Paso 2: Elección de plantilla hacia revisión intermedia
    (EstadoFlujo.ESPERANDO_PLANTILLA, None): ReglaContinuar(
        estado_destino=EstadoFlujo.REVISION_BORRADOR,
        avanzar=_avanzar_paso_revision_intermedia,
        construir_respuesta=_resp_paso_revision_intermedia,
    ),

    # Paso 2 -> Paso 3: Revisión intermedia hacia tags y categoría
    (EstadoFlujo.REVISION_BORRADOR, "intermedia"): ReglaContinuar(
        estado_destino=_destino_paso_metadatos,
        avanzar=_avanzar_paso_metadatos,
        construir_respuesta=_resp_paso_metadatos,
    ),

    # Paso 3 -> Paso 4: Metadatos definidos hacia revisión final con validador
    (EstadoFlujo.ESPERANDO_METADATOS, None): ReglaContinuar(
        estado_destino=EstadoFlujo.REVISION_BORRADOR,
        avanzar=_avanzar_paso_revision_final,
        construir_respuesta=_resp_paso_revision_final,
    ),

    # Paso 4 / Revisión final
    (EstadoFlujo.REVISION_BORRADOR, None): ReglaContinuar(
        estado_destino=EstadoFlujo.EDICION_FINAL,
        avanzar=_avanzar_paso_edicion_final,
        construir_respuesta=_resp_paso_edicion_final,
    ),

    # Paso 5 / Finalizado desde Edición Final
    (EstadoFlujo.EDICION_FINAL, None): ReglaContinuar(
        estado_destino=EstadoFlujo.FINALIZADO,
        avanzar=_avanzar_paso_finalizado,
        construir_respuesta=_resp_paso_finalizado,
    ),
}


# ==============================================================================
# Punto de entrada único
# ==============================================================================

def continuar(
    sesion: SesionChat,
    opcion: Optional[str] = None,
    prefijo: str = "",
    aviso_privacidad: Optional[str] = None,
) -> ChatOrquestadorResponse:
    """
    Punto de entrada único para avanzar en el flujo consultando TABLA_CONTINUAR.
    Ejecuta compuertas de validación si corresponde, actualiza el estado y datos
    de la sesión y construye la respuesta del orquestador.
    """
    b = sesion.borrador
    if b is None:
        raise ValueError("No se puede avanzar sin un borrador activo en la sesión.")

    if aviso_privacidad is None:
        if getattr(sesion, "aviso_privacidad", None):
            aviso_privacidad = sesion.aviso_privacidad
        elif getattr(sesion, "validacion", None) and getattr(sesion.validacion, "aviso_privacidad", None):
            aviso_privacidad = sesion.validacion.aviso_privacidad

    if opcion:
        resp_meta = gestionar_metadatos_heredados(sesion, opcion)
        if resp_meta is not None:
            return resp_meta

    variante = "intermedia" if b.revision_intermedia else None
    regla = TABLA_CONTINUAR.get((sesion.estado, variante)) or TABLA_CONTINUAR.get((sesion.estado, None))
    if regla is None:
        raise ValueError(
            f"No existe regla de avance definida para estado={sesion.estado} y variante={variante}"
        )

    # Compuerta previa al avance desde revisión
    if sesion.estado == EstadoFlujo.REVISION_BORRADOR and variante == "intermedia":
        if b.metadatos_anteriores and not b.metadatos_heredados_revisados:
            # Sin recursión: continuar() en este mismo estado volvería a entrar acá.
            return _resp_paso_plantilla(
                sesion,
                prefijo="Debés aceptar o rechazar los metadatos heredados antes de continuar. ",
            )
        comp = verificar_compuerta_avance(sesion)
        if comp is not None:
            return comp
    elif sesion.estado == EstadoFlujo.REVISION_BORRADOR:
        if b.metadatos_anteriores and not b.metadatos_heredados_revisados:
            return _resp_paso_revision_final(
                sesion,
                prefijo="Debés aceptar o rechazar los metadatos heredados antes de confirmar la finalización. ",
            )
        comp = verificar_compuerta_avance(sesion)
        if comp is not None:
            return comp

    regla.avanzar(sesion)
    destino = regla.estado_destino(sesion) if callable(regla.estado_destino) else regla.estado_destino
    sesion.estado = destino
    return regla.construir_respuesta(sesion, prefijo, aviso_privacidad)
