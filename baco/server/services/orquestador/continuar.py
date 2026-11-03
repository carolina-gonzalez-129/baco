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
    OPCIONES_CONFIRMAR_METADATOS,
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

# --- Paso 1: Pedir tipo de plantilla (siempre, en todos los flujos) ---

def _destino_paso_plantilla(sesion: SesionChat) -> EstadoFlujo:
    # Convergencia: nuevo, enriquecer, actualizar y "Es un tema distinto" siempre
    # piden primero el tipo de plantilla, aunque venga heredado o en los tags.
    return EstadoFlujo.ESPERANDO_PLANTILLA


def _avanzar_paso_plantilla(sesion: SesionChat) -> None:
    b = sesion.borrador
    if not b:
        return
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id


def _resp_paso_plantilla(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    return construir_respuesta(
        sesion,
        msg_pedir_plantilla(prefijo),
        OPCIONES_PLANTILLAS,
        aviso_privacidad=aviso_privacidad,
    )


def _heredados_pendientes(sesion: SesionChat) -> bool:
    b = sesion.borrador
    return bool(b and b.metadatos_anteriores and not b.metadatos_heredados_revisados)


def _cargar_metadatos_heredados(sesion: SesionChat) -> None:
    """Carga en el borrador la categoría y las etiquetas del artículo original."""
    b = sesion.borrador
    ant = b.metadatos_anteriores or {}
    plantilla = b.tipo_plantilla or sesion.tipo_plantilla
    tematicos = [t for t in (ant.get("tags") or []) if extraer_tipo_plantilla([t]) is None]
    b.tags = combinar_tags(plantilla, tematicos)
    b.categoria_id = ant.get("categoria_id")
    b.categoria_nombre = ant.get("categoria_nombre") or (
        DICCIONARIO_OFICIAL_CATEGORIAS.get(b.categoria_id) if b.categoria_id else None
    )
    sesion.tags = list(b.tags)
    sesion.categoria_id = b.categoria_id
    sesion.categoria_nombre = b.categoria_nombre


def _resp_metadatos_heredados(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    """Paso 3 en enriquecer/actualizar: la categoría y las etiquetas del artículo original
    se cargan en el panel, editables. Se confirma con Enviar datos, igual que la carga manual
    (sin banner ni botones Mantener / Elegir otros).
    """
    _cargar_metadatos_heredados(sesion)
    b = sesion.borrador
    b.metadatos_heredados_revisados = True
    sesion.metadatos_heredados_revisados = True
    tematicos = [t for t in b.tags if extraer_tipo_plantilla([t]) is None]
    mensaje = (
        f"{prefijo}Cargué en el panel la categoría **{b.categoria_nombre or 'sin categoría'}** "
        f"y las etiquetas **{', '.join(tematicos) or 'ninguna'}** del artículo original. "
        "Podés modificarlas y, cuando estés conforme, tocá **Enviar datos**."
    ).strip()
    return construir_respuesta(
        sesion, mensaje, OPCIONES_CONFIRMAR_METADATOS, aviso_privacidad=aviso_privacidad
    )


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
    if _heredados_pendientes(sesion):
        return EstadoFlujo.ESPERANDO_METADATOS
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
        if _heredados_pendientes(sesion):
            return _resp_metadatos_heredados(sesion, prefijo, aviso_privacidad)
        return construir_respuesta(sesion, msg_pedir_metadatos(b.tipo_plantilla or "", prefijo), ["volver"])
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


def _verificar_obligatorios_finalizar(sesion: SesionChat) -> Optional[ChatOrquestadorResponse]:
    """Parte 3: al tocar Finalizar reutiliza la validación de obligatorios del flujo.
    Si falta algo, queda en EDICION_FINAL con un aviso accionable y OPCIONES_EDICION_FINAL.
    """
    from baco.server.services.orquestador.mensajes import OPCIONES_EDICION_FINAL
    from baco.server.services.orquestador.validaciones import validar_borrador

    validar_borrador(sesion)
    v = sesion.validacion
    if v is not None and v.valido:
        return None

    def _campo(f, k):
        return f.get(k) if isinstance(f, dict) else getattr(f, k, None)

    bloqueantes = [f for f in (v.findings if v else []) if _campo(f, "severity") == "Bloqueante"]
    lineas = []
    for f in bloqueantes:
        accion = _campo(f, "action")
        lineas.append(f"- {_campo(f, 'description')}" + (f" ({accion})" if accion else ""))
    detalle = "\n".join(lineas) or "- Hay campos obligatorios sin completar."
    msg = (
        f"Antes de finalizar falta completar:\n{detalle}\n\n"
        "Corregilo en el panel del borrador y tocá **Finalizar** de nuevo."
    )
    sesion.ultimas_opciones = list(OPCIONES_EDICION_FINAL)
    return construir_respuesta(sesion, msg, OPCIONES_EDICION_FINAL)


def _registrar_finalizado(sesion: SesionChat) -> ChatOrquestadorResponse:
    """Registra la finalización del borrador aplicando sanitización silenciosa final si corresponde."""
    b = sesion.borrador
    if b is None:
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    if _heredados_pendientes(sesion):
        # Sin recursión: se vuelve al paso de tags y categoría a decidir sobre los heredados.
        sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
        return _resp_metadatos_heredados(
            sesion, prefijo="Antes de finalizar, decidí si mantenés los metadatos heredados. "
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
    Resuelve aceptar_metadatos / rechazar_metadatos (enriquecer o actualizar) en el
    paso de tags y categoría. Conserva el tipo de plantilla elegido en el paso 1.
    """
    b = sesion.borrador
    if not b or not b.metadatos_anteriores:
        return None

    acepta = opcion in ("aceptar", "aceptar_metadatos")
    rechaza = opcion == "rechazar_metadatos" or (
        opcion == "rechazar" and not b.metadatos_heredados_revisados
    )
    if not (acepta or rechaza):
        return None

    b.metadatos_heredados_revisados = True
    sesion.metadatos_heredados_revisados = True
    plantilla = b.tipo_plantilla or sesion.tipo_plantilla
    ant = b.metadatos_anteriores
    if acepta:
        _cargar_metadatos_heredados(sesion)
        prefijo = "Se confirmaron los metadatos de la versión anterior. "
    else:
        b.tags = combinar_tags(plantilla, [])
        b.categoria_id = None
        b.categoria_nombre = None
        prefijo = "Se descartaron los metadatos heredados. "
    sesion.tags = list(b.tags)
    sesion.categoria_id = b.categoria_id
    sesion.categoria_nombre = b.categoria_nombre

    sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
    destino = _destino_paso_metadatos(sesion)
    if destino == EstadoFlujo.REVISION_BORRADOR:
        _avanzar_paso_revision_final(sesion)
        sesion.estado = destino
        return _resp_paso_revision_final(sesion, prefijo)
    return _resp_paso_metadatos(sesion, prefijo)


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
        # Los metadatos heredados se resuelven en el paso siguiente (tags y categoría).
        comp = verificar_compuerta_avance(sesion)
        if comp is not None:
            return comp
    elif sesion.estado == EstadoFlujo.REVISION_BORRADOR:
        if _heredados_pendientes(sesion):
            sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
            return _resp_metadatos_heredados(
                sesion,
                prefijo="Antes de seguir, decidí si mantenés los metadatos heredados. ",
            )
        comp = verificar_compuerta_avance(sesion)
        if comp is not None:
            return comp

    elif sesion.estado == EstadoFlujo.EDICION_FINAL:
        comp = _verificar_obligatorios_finalizar(sesion)
        if comp is not None:
            return comp

    regla.avanzar(sesion)
    destino = regla.estado_destino(sesion) if callable(regla.estado_destino) else regla.estado_destino
    sesion.estado = destino
    return regla.construir_respuesta(sesion, prefijo, aviso_privacidad)
