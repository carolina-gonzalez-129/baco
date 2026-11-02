"""
Módulo de avance unificado para el orquestador.

Define la tabla de transiciones declaradas, la compuerta de validación previa
al avance y las funciones de respuesta para el troncal del flujo:
  Paso 1: Pedir tipo de plantilla (ESPERANDO_PLANTILLA).
  Paso 2: Aplicar plantilla y revisión intermedia (REVISION_BORRADOR, revision_intermedia=True).
  Paso 3: Pedir tags y categoría (ESPERANDO_METADATOS).
  Paso 4: Aplicar validador y revisión final (REVISION_BORRADOR, revision_intermedia=False).
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
from baco.server.services.orquestador.recursos_service import texto_efectivo_sin_marcadores
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
        mensaje_espera = f"{prefijo}{aviso_meta}".strip()
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


# --- Paso 2: Revisión intermedia tras aplicar plantilla ---

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

    texto_vigente = (
        b.texto_editor
        or sesion.texto_editor
        or b.texto_original
        or sesion.texto_original
        or b.texto_limpio
        or sesion.texto_limpio
        or b.texto_base_limpio
        or sesion.texto
        or ""
    ).strip()
    texto_origen = texto_efectivo_sin_marcadores(texto_vigente)
    sesion.texto_original = texto_origen
    b.texto_original = texto_origen
    b.texto_editor = texto_origen
    sesion.texto_editor = texto_origen
    b.texto_base_limpio = texto_origen
    sesion.texto_limpio = texto_origen

    import os
    baco = getattr(sesion, "_baco_agent", None)
    if baco is None:
        try:
            from baco.server.app.main import app
            from baco.server.app.dependencies import get_baco_agent
            override = app.dependency_overrides.get(get_baco_agent)
            if override:
                baco = override()
        except Exception:
            pass
    if baco is None and "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            from baco.server.app.dependencies import get_baco_agent
            baco = get_baco_agent()
        except Exception:
            baco = None

    if baco is not None and callable(baco):
        resultado_plantilla = None
        try:
            from baco.server.services.agente_service import (
                ejecutar_skill_plantillas,
                ejecutar_skill_validador,
            )
            b.bloques_texto = [texto_origen] if texto_origen else []
            resultado_plantilla = (
                ejecutar_skill_plantillas(sesion.session_id, b, baco) or ""
            ).strip()
            if resultado_plantilla:
                b.bloques_texto = [resultado_plantilla]
                sesion.bloques_texto = [resultado_plantilla]
        except Exception:
            resultado_plantilla = None

        if resultado_plantilla:
            try:
                dictamen, texto_corr = ejecutar_skill_validador(b, baco)
                resultado_final = (texto_corr or resultado_plantilla).strip()
                if resultado_final:
                    b.bloques_texto = [resultado_final]
                    sesion.bloques_texto = [resultado_final]
            except Exception:
                pass

            b.resultado_skill_desactualizado = False
            b.resultado_skill_pendiente = True
            b.skill_pendiente = "plantilla"
            b.skill_aplicada = "plantilla"
            sesion.skill_aplicada = "plantilla"


def _resp_paso_revision_intermedia(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    msg, ops = validar_borrador(sesion, prefijo)
    ops = [op for op in ops if op != "aplicar_plantilla"]
    if b and getattr(b, "resultado_skill_pendiente", False):
        if sesion.validacion and sesion.validacion.valido:
            msg = f"{prefijo}Listo, apliqué la plantilla. Revisá el resultado y tocá **Continuar**.".strip()
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


# --- Paso 4: Revisión final tras definir metadatos con validador ---

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
    """
    Decide la acción de 'continuar' o 'continuar_revision' desde el estado de revisión:
    - Si es revisión intermedia: avanza al siguiente paso del troncal con continuar().
    - Si es revisión final: registra la finalización del borrador con _registrar_finalizado().
    """
    b = sesion.borrador
    if b is not None and b.revision_intermedia:
        return continuar(sesion)
    return continuar(sesion)


def _avanzar_paso_finalizado(sesion: SesionChat) -> None:
    b = sesion.borrador
    if b is None:
        return
    from baco.server.services.orquestador.edicion import adoptar_resultado_skill_pendiente
    adoptar_resultado_skill_pendiente(sesion)
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
        return continuar(sesion, prefijo="Debés aceptar o rechazar los metadatos heredados antes de confirmar la finalización. ")

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
            return continuar(
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
