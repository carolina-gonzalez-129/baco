"""Contrato de estados del orquestador (paso 3, back).

Por cada estado el back declara tres cosas separadas:
- opciones: botones del chat (los arman los handlers).
- editables: campos del panel que el back acepta en ese estado.
- navegacion: acciones para moverse en el flujo (por ahora solo "volver");
  el front decide cómo mostrarlas.

Regla única de aceptación: una opción se acepta solo si el back la devolvió en el
turno anterior (opciones o navegación), si es global o si es una acción de panel del
estado (ACCIONES_PANEL_POR_ESTADO). Un campo fuera de
`editables` se descarta con aviso.

Paso 5: EDICION_FINAL (sin volver), FINALIZADO (terminal; "ver_articulo_final" va en
navegación) y RECHAZADO (terminal) también rigen por este contrato.
"""
from typing import List, Optional, Tuple

from baco.server.schemas.chat_orquestado import ChatOrquestadorRequest, EstadoFlujo

OPCIONES_GLOBALES = frozenset({"reiniciar", "ayuda"})
IDS_NAVEGACION = frozenset({"volver", "ver_articulo_final"})

ESTADOS_CONTRATO = frozenset({
    EstadoFlujo.ESPERANDO_TITULO,
    EstadoFlujo.DECISION_TITULO,
    EstadoFlujo.ESPERANDO_TEXTO,
    EstadoFlujo.DECISION_TEXTO,
    EstadoFlujo.ESPERANDO_PLANTILLA,
    EstadoFlujo.ESPERANDO_METADATOS,
    EstadoFlujo.REVISION_TIPO,
    EstadoFlujo.REVISION_METADATOS,
    EstadoFlujo.EDICION_FINAL,
    EstadoFlujo.FINALIZADO,
    EstadoFlujo.RECHAZADO,
})

# Estados donde el mensaje libre es contenido (título o texto), no una opción.
ESTADOS_ENTRADA_LIBRE = frozenset({EstadoFlujo.ESPERANDO_TITULO, EstadoFlujo.ESPERANDO_TEXTO})

# Acciones que el panel envía en su estado aunque el último turno no las haya ofrecido
# (p. ej. después de un error de longitud que devuelve opciones vacías).
# "reaplicar": el panel la envía cuando el Editor cambió después de una skill; el handler
# verifica que haya un resultado de skill pendiente.
ACCIONES_PANEL_POR_ESTADO = {
    EstadoFlujo.ESPERANDO_TEXTO: frozenset({"confirmar_texto"}),
    EstadoFlujo.ESPERANDO_METADATOS: frozenset({"enviar_datos"}),
    EstadoFlujo.REVISION_TIPO: frozenset({"reaplicar"}),
    EstadoFlujo.REVISION_METADATOS: frozenset({"reaplicar"}),
    EstadoFlujo.EDICION_FINAL: frozenset({"reaplicar"}),
}

CAMPOS_CONTENIDO = ["titulo", "texto", "texto_editor"]
CAMPOS_FILTRADOS = ("tipo_plantilla", "categoria_id", "tags")
_ETIQUETAS_CAMPO = {
    "tipo_plantilla": "Tipo de plantilla",
    "categoria_id": "Categoría",
    "tags": "Etiquetas",
}


# Estados donde cada skill se puede ejecutar (también por los endpoints REST).
ESTADOS_SKILL = {
    "plantilla": frozenset({EstadoFlujo.REVISION_TIPO, EstadoFlujo.EDICION_FINAL}),
    "auditor": frozenset({EstadoFlujo.REVISION_METADATOS, EstadoFlujo.EDICION_FINAL}),
}


# Botón principal del panel por estado. "guardar" no viaja como accion: el front envía los campos.
_ACCION_PANEL = {
    EstadoFlujo.ESPERANDO_TEXTO: ("confirmar_texto", "Confirmar texto"),
    EstadoFlujo.ESPERANDO_METADATOS: ("enviar_datos", "Enviar datos"),
    EstadoFlujo.REVISION_TIPO: ("guardar", "Guardar cambios"),
    EstadoFlujo.REVISION_METADATOS: ("guardar", "Guardar cambios"),
    EstadoFlujo.EDICION_FINAL: ("guardar", "Guardar cambios"),
}

# Motivo cuando la skill no corre en el estado actual.
_MOTIVO_FUERA_DE_ESTADO = {
    ("plantilla", EstadoFlujo.REVISION_METADATOS): "La plantilla se aplica en su paso o en la edición final.",
    ("auditor", EstadoFlujo.REVISION_TIPO): "El validador se habilita después de definir categoría y etiquetas.",
}


def skill_permitida(estado, skill: str) -> bool:
    return estado in ESTADOS_SKILL.get(skill, frozenset())


def plantilla_aplicada(sesion) -> bool:
    """True si ya corrió una skill sobre el borrador: el tipo queda fijo hasta EDICION_FINAL."""
    b = sesion.borrador
    return bool(b is not None and b.skill_aplicada)


def auditado(sesion) -> bool:
    """True si ya corrió el auditor: categoría y etiquetas quedan fijas hasta EDICION_FINAL."""
    b = sesion.borrador
    return bool(b is not None and (b.skill_aplicada or "").lower() == "auditor")


def campos_editables(sesion) -> List[str]:
    e = sesion.estado
    if e == EstadoFlujo.ESPERANDO_TITULO:
        return ["titulo"]
    if e in (EstadoFlujo.DECISION_TITULO, EstadoFlujo.DECISION_TEXTO):
        # El texto escrito en el panel se usa al enriquecer o al seguir con el texto propio.
        return ["texto"]
    if e == EstadoFlujo.ESPERANDO_TEXTO:
        return ["texto"]
    if e == EstadoFlujo.ESPERANDO_PLANTILLA:
        return ["tipo_plantilla"]
    if e == EstadoFlujo.ESPERANDO_METADATOS:
        return CAMPOS_CONTENIDO + ["categoria_id", "tags"]
    if e == EstadoFlujo.REVISION_TIPO:
        return CAMPOS_CONTENIDO + ([] if plantilla_aplicada(sesion) else ["tipo_plantilla"])
    if e == EstadoFlujo.REVISION_METADATOS:
        return CAMPOS_CONTENIDO + ([] if auditado(sesion) else ["categoria_id", "tags"])
    if e == EstadoFlujo.EDICION_FINAL:
        return CAMPOS_CONTENIDO + ["tipo_plantilla", "categoria_id", "tags"]
    return []


def navegacion(sesion, opciones: List[str]) -> List[str]:
    """Navegación del estado. Fuera del contrato se respeta lo que venía en opciones."""
    e = sesion.estado
    if e not in ESTADOS_CONTRATO:
        return [o for o in opciones if o in IDS_NAVEGACION]
    if e == EstadoFlujo.FINALIZADO:
        return ["ver_articulo_final"]
    if e in (EstadoFlujo.EDICION_FINAL, EstadoFlujo.RECHAZADO):
        # EDICION_FINAL: sin volver (después de una skill solo se corrige acá). RECHAZADO: terminal.
        return []
    if getattr(sesion, "confirmando_rechazo", False) or e == EstadoFlujo.ESPERANDO_TITULO:
        return []
    if e == EstadoFlujo.REVISION_TIPO and plantilla_aplicada(sesion):
        return []
    if e == EstadoFlujo.REVISION_METADATOS and auditado(sesion):
        return []
    return ["volver"]


def separar_opciones(sesion, opciones: List[str]) -> Tuple[List[str], List[str]]:
    """Separa los botones del chat de la navegación."""
    chat = [o for o in opciones if not (isinstance(o, str) and o in IDS_NAVEGACION)]
    return chat, navegacion(sesion, opciones)


def es_accion(sesion, req: ChatOrquestadorRequest, opcion: str) -> bool:
    """True si el turno pide una opción (botón o palabra clave), no contenido libre."""
    if req.accion and req.accion.strip():
        return True
    if not opcion or sesion.estado in ESTADOS_ENTRADA_LIBRE:
        return False
    from baco.server.services.orquestador.mensajes import DESCRIPTORES_BOTONES
    return opcion in DESCRIPTORES_BOTONES or opcion in ("reaplicar", "aceptar")


def opcion_permitida(sesion, opcion: str) -> bool:
    if sesion.estado not in ESTADOS_CONTRATO or opcion in OPCIONES_GLOBALES:
        return True
    permitidas = {o.casefold() for o in (sesion.ultimas_opciones or []) if isinstance(o, str)}
    permitidas |= set(getattr(sesion, "ultima_navegacion", None) or [])
    permitidas |= ACCIONES_PANEL_POR_ESTADO.get(sesion.estado, frozenset())
    return opcion.casefold() in permitidas


def _motivo_descarte(sesion, campo: str) -> str:
    e = sesion.estado
    if e in (EstadoFlujo.FINALIZADO, EstadoFlujo.RECHAZADO):
        return "el artículo ya está cerrado"
    if campo == "tipo_plantilla" and e == EstadoFlujo.REVISION_TIPO:
        return "ya se aplicó la plantilla; vas a poder cambiarlo en la edición final"
    if campo in ("categoria_id", "tags") and e == EstadoFlujo.REVISION_METADATOS:
        return "ya se auditó el artículo; vas a poder cambiarlas en la edición final"
    if campo in ("categoria_id", "tags") and e not in (
        EstadoFlujo.ESPERANDO_METADATOS, EstadoFlujo.REVISION_METADATOS
    ):
        return "se cargan en el paso de clasificación"
    return "no se edita en este paso; vas a poder cambiarlo en la edición final"


def filtrar_campos_no_editables(
    sesion, req: ChatOrquestadorRequest
) -> List[Tuple[str, str]]:
    """Quita del request tipo, categoría y etiquetas si el estado no los acepta.
    Devuelve los descartes (solo los que cambiaban algo) para avisar en el chat.
    Título y texto siguen resueltos por cada handler (ver campos_editables).
    """
    if sesion.estado not in ESTADOS_CONTRATO:
        return []
    from baco.server.services.orquestador.edicion import (
        categoria_difiere,
        plantilla_difiere,
        tags_difiere,
    )
    from baco.server.services.orquestador.validaciones import extraer_tipo_plantilla

    editables = set(campos_editables(sesion))
    b = sesion.borrador
    tags_act = (b.tags if b else sesion.tags) or []
    plantilla_act = (b.tipo_plantilla if b else sesion.tipo_plantilla) or extraer_tipo_plantilla(tags_act)
    cat_act = b.categoria_id if b else sesion.categoria_id

    descartes: List[Tuple[str, str]] = []
    for campo in CAMPOS_FILTRADOS:
        valor = getattr(req, campo, None)
        if valor is None or campo in editables:
            continue
        if campo == "tipo_plantilla":
            try:
                difiere = plantilla_difiere(valor, plantilla_act)
            except ValueError:
                difiere = True
        elif campo == "categoria_id":
            difiere = categoria_difiere(valor, cat_act)
        else:
            difiere = tags_difiere(valor, tags_act, plantilla=plantilla_act)
        if difiere:
            descartes.append((_ETIQUETAS_CAMPO[campo], _motivo_descarte(sesion, campo)))
        setattr(req, campo, None)
    return descartes


def accion_panel(sesion) -> Optional[dict]:
    par = _ACCION_PANEL.get(sesion.estado)
    if par is None:
        return None
    accion, label = par
    return {"accion": accion, "label": label, "campos": campos_editables(sesion)}


def estado_skills(sesion, habilitadas: bool, motivo: Optional[str]) -> dict:
    """Disponibilidad de cada skill. `habilitadas`/`motivo`: límite de largo del borrador."""
    b = sesion.borrador
    v = getattr(sesion, "validacion", None)
    con_bloqueantes = (
        sesion.estado in (EstadoFlujo.REVISION_TIPO, EstadoFlujo.REVISION_METADATOS)
        and v is not None and getattr(v, "status", None) == "Pendiente"
    )
    res = {}
    for skill in ("plantilla", "auditor"):
        if b is None:
            m = "Todavía no hay un borrador armado."
        elif not skill_permitida(sesion.estado, skill):
            m = _MOTIVO_FUERA_DE_ESTADO.get(
                (skill, sesion.estado), "Las skills se habilitan en la revisión del borrador."
            )
        elif con_bloqueantes:
            m = "Primero resolvé los bloqueantes de la validación."
        elif not habilitadas:
            m = motivo or "Las skills de asistencia del agente están deshabilitadas para este borrador."
        elif skill == "plantilla" and not b.tipo_plantilla:
            m = "Primero elegí un tipo de plantilla."
        elif skill == "auditor" and (b.categoria_id is None or len(b.tags or []) < 2):
            m = "Requiere categoría y al menos 2 etiquetas."
        else:
            m = None
        res[skill] = {"habilitada": m is None, "motivo": m}
    return res
