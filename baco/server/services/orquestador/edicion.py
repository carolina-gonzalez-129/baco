from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from baco.server.config_limites import (
    TAGS_MIN,
    TAGS_PLANTILLAS_PERMITIDAS,
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)
from baco.server.schemas.chat_orquestado import (
    CategoriaOpcion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.schemas.recurso import Recurso
from baco.server.services.orquestador.recursos_service import (
    _max_num_recurso,
    procesar_recursos_y_bloques,
)
from baco.server.services.orquestador.sesion import SesionChat
from baco.server.services.orquestador.validaciones import (
    combinar_tags,
    extraer_tipo_plantilla,
    resolver_categoria,
    validar_longitud,
)
from baco.server.services.validar_articulo import sanitizar_borrador


ESTADOS_EDICION_LIBRE = {
    EstadoFlujo.ESPERANDO_PLANTILLA,
    EstadoFlujo.ESPERANDO_METADATOS,
    EstadoFlujo.REVISION_BORRADOR,
    EstadoFlujo.SUBSANANDO_BORRADOR,
}


@dataclass
class ResultadoEdicion:
    ok: bool
    error: Optional[str] = None
    aviso: Optional[str] = None
    aviso_privacidad: Optional[str] = None
    aviso_skill_desactualizada: Optional[str] = None
    opciones_sugeridas: Optional[List[str]] = None
    titulo_nuevo: Optional[str] = None
    bloques_nuevos: Optional[List[str]] = None
    recursos_nuevos: Optional[Dict[str, Recurso]] = None
    txt_nuevo_limpio: Optional[str] = None
    ultimo_id_nuevo: Optional[int] = None
    categoria_id_nueva: Optional[int] = None
    categoria_nombre_nuevo: Optional[str] = None
    tags_nuevos: Optional[List[str]] = None
    tipo_plantilla_nueva: Optional[str] = None


MSG_SKILL_DESACTUALIZADA = (
    "Editaste el texto, así que la versión de la Vista previa quedó desactualizada."
)
MSG_PLANTILLA_DESACTUALIZADA = (
    "Cambiaste la plantilla, así que la versión de la Vista previa quedó desactualizada."
)


def tiene_resultado_skill_visible(borrador: Optional[Any]) -> bool:
    """Indica si el borrador tiene un resultado de skill visible en la Vista previa."""
    if not borrador:
        return False
    return bool(
        getattr(borrador, "resultado_skill_pendiente", False)
        or getattr(borrador, "skill_pendiente", None)
        or getattr(borrador, "resultado_skill_desactualizado", False)
    )


def procesar_edicion_titulo(titulo: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Valida y sanitiza el título provisto.

    Retorna: (titulo_sanitizado, aviso_privacidad, error)
    """
    tit_nuevo = (titulo or "").strip()
    err_tit = validar_longitud(tit_nuevo, TITULO_MIN, TITULO_MAX, "título")
    if err_tit:
        return None, None, err_tit

    sanit_tit = sanitizar_borrador(texto="", titulo=tit_nuevo)
    titulo_sanitizado = sanit_tit["titulo_sanitizado"]
    aviso_priv = sanit_tit.get("aviso_privacidad")
    return titulo_sanitizado, aviso_priv, None


def procesar_edicion_categoria(
    categoria_id: int,
    categorias_disponibles: Optional[List[CategoriaOpcion]] = None,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Valida la categoría provista contra el catálogo oficial.

    Retorna: (categoria_id, categoria_nombre, error)
    """
    res_cat = resolver_categoria(categoria_id, categorias_disponibles)
    if res_cat.categoria_id is None:
        return None, None, f"La categoría '{categoria_id}' no es válida o no existe en el catálogo oficial."
    return res_cat.categoria_id, res_cat.categoria_nombre, None


def procesar_edicion_tags(
    tags: List[str],
    plantilla: Optional[str] = None,
) -> Tuple[Optional[List[str]], Optional[str]]:
    """Filtra y valida los tags provistos, preservando la plantilla fija y asegurando TAGS_MIN.

    Retorna: (tags_nuevos, error)
    """
    tags_filtrados = [
        t
        for t in tags
        if extraer_tipo_plantilla([t]) is None or (plantilla and extraer_tipo_plantilla([t]) == plantilla)
    ]
    tags_nuevos = combinar_tags(plantilla, tags_filtrados)
    if len(tags_nuevos) < TAGS_MIN:
        return None, f"Se requieren al menos {TAGS_MIN} tags o etiquetas (actualmente tiene {len(tags_nuevos)})."
    return tags_nuevos, None


def revalidar_estructura_plantilla(
    sesion: SesionChat,
    texto: str,
    titulo: Optional[str] = None,
    plantilla: Optional[str] = None,
) -> Optional[str]:
    """Revalida las secciones y estructura requeridas por la plantilla (si está definida)
    usando validar_texto_y_estructura_post_duplicados, exclusivamente como aviso no bloqueante.
    """
    b = sesion.borrador
    plantilla_evaluar = plantilla or (b.tipo_plantilla if b else None)
    if not b or not plantilla_evaluar:
        return None

    try:
        from baco.server.schemas.articulo import ArticuloSchema, Tag
        from baco.server.services.validar_articulo import (
            validar_metadatos,
            validar_texto_y_estructura_post_duplicados,
        )

        tags_art = [
            Tag(name=t)
            for t in (b.tags or [])
            if extraer_tipo_plantilla([t]) is None
        ]
        tags_art.append(Tag(name=plantilla_evaluar))

        art_eval = ArticuloSchema(
            id=b.articulo_original_id or 0,
            titulo=titulo or b.titulo or sesion.titulo or "",
            texto=texto,
            categoria_id=b.categoria_id,
            tags=tags_art,
            url=b.articulo_original_url,
        )
        res_val = validar_texto_y_estructura_post_duplicados(art_eval)
        hallazgos_meta = validar_metadatos(art_eval)
        findings = [
            f
            for f in res_val.get("findings", [])
            if f not in hallazgos_meta and f.get("field") != "titulo"
        ]
        if findings:
            detalle = "\n".join(
                f"- [{f['severity']}] {f['description']} ({f['action']})"
                for f in findings
            )
            return f"Aviso sobre la estructura de la plantilla '{plantilla_evaluar}':\n{detalle}"
    except Exception:
        pass
    return None


def procesar_edicion_texto(
    texto: str,
    sesion: SesionChat,
    titulo_contexto: Optional[str] = None,
    det_req: Optional[str] = None,
) -> Tuple[
    Optional[List[str]],
    Optional[Dict[str, Recurso]],
    Optional[str],
    Optional[int],
    Optional[str],
    Optional[str],
    Optional[str],
]:
    """Valida marcadores, procesa recursos/bloques, sanitiza, valida longitud y
    revalida estructura de plantilla.

    Retorna: (bloques_nuevos, recursos_nuevos, txt_nuevo_limpio, ultimo_id_nuevo, aviso_privacidad, aviso_plantilla, error)
    """
    b = sesion.borrador
    recursos_previos = b.recursos if b else sesion.recursos
    ultimo_id_base = max(
        sesion.ultimo_id_recurso,
        (b.ultimo_id_recurso if b else 0),
        _max_num_recurso(recursos_previos),
    )

    txt_nuevo = (texto or "").strip()
    bloques_proc, recs_comb, err_marcadores = procesar_recursos_y_bloques(
        txt_nuevo,
        recursos_previos=recursos_previos,
        ultimo_id=ultimo_id_base,
    )
    if err_marcadores:
        return None, None, None, None, None, None, err_marcadores

    txt_proc = "\n\n".join(bloques_proc).strip()
    titulo_para_sanit = titulo_contexto or (b.titulo if b else sesion.titulo) or ""
    sanit_edit = sanitizar_borrador(texto=txt_proc, titulo=titulo_para_sanit)
    txt_verif = sanit_edit["texto_sanitizado"]
    aviso_txt = sanit_edit.get("aviso_privacidad")

    bloques_nuevos = [
        sanitizar_borrador(texto=bl)["texto_sanitizado"].strip()
        for bl in bloques_proc
        if bl.strip()
    ]
    bloques_nuevos = [bl for bl in bloques_nuevos if bl]

    aviso_efectivo = aviso_txt or det_req

    err_txt = validar_longitud(txt_verif, TEXTO_MIN, TEXTO_MAX_PERCENTIL_99, "texto")
    if err_txt:
        return None, None, None, None, None, None, err_txt

    txt_nuevo_limpio = txt_verif
    recursos_nuevos = recs_comb
    ultimo_id_nuevo = max(ultimo_id_base, _max_num_recurso(recs_comb))

    aviso_plantilla = revalidar_estructura_plantilla(sesion, txt_verif, titulo_para_sanit)

    # El texto editado pasa a ser el nuevo texto original previo a las skills
    if sesion.borrador is not None:
        sesion.borrador.texto_editor = txt_nuevo_limpio
        sesion.borrador.texto_base_limpio = txt_nuevo_limpio
    sesion.texto_editor = txt_nuevo_limpio

    return (
        bloques_nuevos,
        recursos_nuevos,
        txt_nuevo_limpio,
        ultimo_id_nuevo,
        aviso_efectivo,
        aviso_plantilla,
        None,
    )


def normalizar_texto_para_comparar(texto: Optional[str]) -> str:
    """Normaliza saltos de línea (CRLF a LF) y espacios en los extremos."""
    if not texto:
        return ""
    return texto.replace("\r\n", "\n").strip()


def texto_difiere(
    texto_req: Optional[str],
    texto_guardado: Optional[str],
    titulo_contexto: Optional[str] = None,
) -> bool:
    """Determina si el texto del request difiere efectivamente del texto guardado.
    Compara tanto en crudo normalizado (saltos de línea y extremos) como tras sanitizar
    el texto del request con el contexto del título, evitando falsos positivos al reenviar
    el mismo texto devuelto por el back.
    """
    if texto_req is None:
        return False
    norm_req = normalizar_texto_para_comparar(texto_req)
    norm_guardado = normalizar_texto_para_comparar(texto_guardado)
    if norm_req == norm_guardado:
        return False

    sanit = sanitizar_borrador(texto=norm_req, titulo=titulo_contexto or "")
    txt_sanit = normalizar_texto_para_comparar(sanit.get("texto_sanitizado"))
    return txt_sanit != norm_guardado


def titulo_difiere(
    titulo_req: Optional[str],
    titulo_guardado: Optional[str],
) -> bool:
    """Determina si el título del request difiere efectivamente del título guardado.
    Compara en crudo normalizado y tras sanitizar.
    """
    if titulo_req is None:
        return False
    norm_req = normalizar_texto_para_comparar(titulo_req)
    norm_guardado = normalizar_texto_para_comparar(titulo_guardado)
    if norm_req == norm_guardado:
        return False

    sanit = sanitizar_borrador(texto="", titulo=norm_req)
    tit_sanit = normalizar_texto_para_comparar(sanit.get("titulo_sanitizado"))
    return tit_sanit != norm_guardado


def categoria_difiere(
    categoria_req: Optional[int],
    categoria_guardada: Optional[int],
) -> bool:
    """Determina si la categoría del request difiere efectivamente de la guardada."""
    if categoria_req is None:
        return False
    return categoria_req != categoria_guardada


def plantilla_difiere(
    plantilla_req: Optional[str],
    plantilla_guardada: Optional[str],
) -> bool:
    """Determina si el tipo de plantilla del request difiere del guardado.
    Hay cambio solo si el valor no es None y difiere.
    Aplica strip().lower() antes de validarlo contra TAGS_PLANTILLAS_PERMITIDAS.
    """
    if plantilla_req is None:
        return False
    norm_req = plantilla_req.strip().lower()
    if norm_req not in TAGS_PLANTILLAS_PERMITIDAS:
        permitidas = " o ".join(f"'{p}'" for p in TAGS_PLANTILLAS_PERMITIDAS)
        raise ValueError(
            f"El tipo de plantilla '{plantilla_req.strip()}' no es válido. Las opciones permitidas son: {permitidas}."
        )
    norm_guardada = (plantilla_guardada or "").strip().lower()
    return norm_req != norm_guardada


def tags_difiere(
    tags_req: Optional[List[str]],
    tags_guardados: Optional[List[str]],
    plantilla: Optional[str] = None,
) -> bool:
    """Determina si los tags del request difieren de los guardados como conjunto (ignorando orden).
    Compara solo tags temáticos, excluyendo los de plantilla mediante extraer_tipo_plantilla.
    """
    if tags_req is None:
        return False
    tematicos_req = {
        t.strip().lower()
        for t in tags_req
        if t and t.strip() and extraer_tipo_plantilla([t]) is None
    }
    tematicos_guardados = {
        t.strip().lower()
        for t in (tags_guardados or [])
        if t and t.strip() and extraer_tipo_plantilla([t]) is None
    }
    return tematicos_req != tematicos_guardados


def aplicar_edicion_campos(
    sesion: SesionChat,
    req: ChatOrquestadorRequest,
) -> ResultadoEdicion:
    """Valida y aplica la edición silenciosa de título y/o texto en estados posteriores a duplicados."""
    b = sesion.borrador

    tit_guardado = (b.titulo if b else sesion.titulo) or ""
    tiene_skill_vis = tiene_resultado_skill_visible(b)
    txt_guardado = (
        b.texto_editor
        if (b and b.texto_editor and tiene_skill_vis)
        else (b.texto_limpio if b else (sesion.texto_limpio or sesion.texto))
    ) or ""

    edita_titulo = titulo_difiere(req.titulo, tit_guardado)
    edita_texto = texto_difiere(req.texto, txt_guardado, titulo_contexto=tit_guardado)

    if not edita_titulo and not edita_texto:
        return ResultadoEdicion(ok=True)

    titulo_nuevo = None
    aviso_priv_tit = None
    if edita_titulo:
        titulo_nuevo, aviso_priv_tit, err_tit = procesar_edicion_titulo(req.titulo)
        if err_tit:
            return ResultadoEdicion(ok=False, error=err_tit)

    bloques_nuevos = None
    recursos_nuevos = None
    txt_nuevo_limpio = None
    ultimo_id_nuevo = None
    aviso_priv_txt = None
    aviso_plantilla = None

    if edita_texto:
        (
            bloques_nuevos,
            recursos_nuevos,
            txt_nuevo_limpio,
            ultimo_id_nuevo,
            aviso_priv_txt,
            aviso_plantilla,
            err_txt,
        ) = procesar_edicion_texto(
            req.texto,
            sesion,
            titulo_contexto=titulo_nuevo or tit_guardado,
            det_req=getattr(req, "aviso_privacidad_detectado", None),
        )
        if err_txt:
            return ResultadoEdicion(ok=False, error=err_txt)

    kwargs: Dict[str, Any] = {}
    if edita_titulo:
        kwargs["titulo"] = titulo_nuevo

    if edita_texto:
        kwargs["bloques_texto"] = bloques_nuevos
        kwargs["recursos"] = recursos_nuevos
        kwargs["ultimo_id_recurso"] = ultimo_id_nuevo
        if txt_nuevo_limpio is not None:
            kwargs["texto_base_limpio"] = txt_nuevo_limpio
            kwargs["texto_editor"] = txt_nuevo_limpio
        if tiene_skill_vis:
            kwargs["resultado_skill_desactualizado"] = False
            kwargs["resultado_skill_pendiente"] = False
            if b is not None:
                b.resultado_skill_desactualizado = False
                b.resultado_skill_pendiente = False
                b.skill_pendiente = None

    if kwargs:
        sesion.actualizar_contenido_borrador(**kwargs)

    partes_aviso_priv = [p for p in (aviso_priv_tit, aviso_priv_txt) if p]
    aviso_priv_total = "\n".join(partes_aviso_priv) if partes_aviso_priv else None

    return ResultadoEdicion(
        ok=True,
        aviso=aviso_plantilla,
        aviso_privacidad=aviso_priv_total,
        titulo_nuevo=titulo_nuevo,
        bloques_nuevos=bloques_nuevos,
        recursos_nuevos=recursos_nuevos,
        txt_nuevo_limpio=txt_nuevo_limpio,
        ultimo_id_nuevo=ultimo_id_nuevo,
    )


async def ejecutar_skill(
    sesion: SesionChat,
    req: ChatOrquestadorRequest,
    skill: str,
    es_reaplicacion: bool = False,
) -> ChatOrquestadorResponse:
    """Ejecuta la skill ('plantilla' o 'auditor') sobre el texto original del Editor.
    El resultado va solo a b.bloques_texto y sesion.bloques_texto.
    El texto original se preserva en b.texto_editor, sesion.texto_editor y b.texto_base_limpio.
    No sincroniza sesion.texto_limpio ni sesion.texto con el resultado de la skill.
    """
    from baco.server.services.orquestador.validaciones import (
        construir_respuesta,
        extraer_tipo_plantilla,
    )

    b = sesion.borrador
    if b is None:
        from baco.server.services.orquestador.mensajes import MSG_RECHAZADO, OPCIONES_REINICIAR
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    skill_norm = (skill or "plantilla").lower()
    es_auditor = "auditor" in skill_norm or "validador" in skill_norm
    skill_nombre = "auditor" if es_auditor else "plantilla"

    # Validación para auditar: requiere categoría y tags temáticos
    if es_auditor:
        tags_tematicos = [
            t for t in (b.tags or [])
            if t and t.strip() and extraer_tipo_plantilla([t]) is None
        ]
        if not b.categoria_id or not tags_tematicos:
            msg_falta_meta = (
                "Para auditar el artículo, primero es necesario definir la categoría y al menos una etiqueta temática."
            )
            return construir_respuesta(sesion, msg_falta_meta, sesion.ultimas_opciones)

    texto_origen = (
        b.texto_editor
        or sesion.texto_editor
        or b.texto_base_limpio
        or b.texto_limpio
        or sesion.texto_limpio
        or sesion.texto
        or ""
    ).strip()

    baco = getattr(req, "_baco_agent", None) or getattr(sesion, "_baco_agent", None)
    if baco is None:
        try:
            from baco.server.app.dependencies import get_baco_agent
            baco = get_baco_agent()
        except Exception:
            baco = None

    if baco is None or not callable(baco):
        msg_sin_agente = (
            "No pudimos aplicar la plantilla en este momento. Por favor, intentá nuevamente."
            if not es_auditor
            else "No pudimos auditar el artículo en este momento. Por favor, intentá nuevamente."
        )
        return construir_respuesta(sesion, msg_sin_agente, sesion.ultimas_opciones)

    bloques_anteriores = list(b.bloques_texto) if b.bloques_texto else []
    try:
        b.bloques_texto = [texto_origen] if texto_origen else []
        if es_auditor:
            from baco.server.services.agente_service import ejecutar_skill_validador
            dictamen, texto_corr = ejecutar_skill_validador(b, baco)
            resultado = (texto_corr or dictamen or "").strip()
        else:
            from baco.server.services.agente_service import ejecutar_skill_plantillas
            resultado = (ejecutar_skill_plantillas(sesion.session_id, b, baco) or "").strip()

        if not resultado:
            raise ValueError("La skill no devolvió contenido.")
    except Exception:
        b.bloques_texto = bloques_anteriores
        msg_error = (
            "No pudimos aplicar la plantilla en este momento. Por favor, intentá nuevamente."
            if not es_auditor
            else "No pudimos auditar el artículo en este momento. Por favor, intentá nuevamente."
        )
        return construir_respuesta(sesion, msg_error, sesion.ultimas_opciones)

    b.bloques_texto = [resultado]
    sesion.bloques_texto = [resultado]

    b.texto_editor = texto_origen
    sesion.texto_editor = texto_origen
    b.texto_base_limpio = texto_origen

    b.resultado_skill_desactualizado = False
    b.resultado_skill_pendiente = True
    b.skill_pendiente = skill_nombre

    if es_reaplicacion:
        opciones = [o for o in sesion.ultimas_opciones if o != "reaplicar"]
        if not opciones:
            opciones = (
                ["continuar_revision", "volver"]
                if getattr(b, "revision_intermedia", False)
                else ["continuar", "volver"]
            )
        msg = (
            "Reaplicamos la plantilla sobre el texto actual del Editor."
            if not es_auditor
            else "Reauditamos el artículo con el texto actual del Editor."
        )
    else:
        opciones = (
            ["continuar_revision", "volver"]
            if getattr(b, "revision_intermedia", False)
            else ["continuar", "volver"]
        )
        msg = (
            "Listo, apliqué la plantilla. Revisá el resultado y tocá **Continuar**."
            if not es_auditor
            else "Listo, revisé el texto. Mirá el resultado y tocá **Continuar**."
        )

    sesion.ultimas_opciones = list(opciones)
    return construir_respuesta(sesion, msg, opciones)


async def handle_reaplicar_skill(
    sesion: SesionChat,
    req: ChatOrquestadorRequest,
    buscador: Any,
) -> ChatOrquestadorResponse:
    """Reejecuta la skill sobre el texto actual del Editor, que es el nuevo original.
    Limpia el flag de desactualizado y no cambia el estado del flujo.
    """
    from baco.server.services.orquestador.validaciones import construir_respuesta
    b = sesion.borrador
    if b is None:
        from baco.server.services.orquestador.mensajes import MSG_RECHAZADO, OPCIONES_REINICIAR
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    if not getattr(b, "resultado_skill_pendiente", False) or not getattr(b, "skill_pendiente", None):
        return construir_respuesta(sesion, "", sesion.ultimas_opciones)

    skill = (b.skill_pendiente or "plantilla").lower()
    return await ejecutar_skill(sesion, req, skill=skill, es_reaplicacion=True)
