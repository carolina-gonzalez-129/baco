from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from starlette.concurrency import run_in_threadpool
import asyncio

from baco.server.config_limites import (
    TAGS_MIN,
    TAGS_PLANTILLAS_PERMITIDAS,
    TEXTO_MAX,
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
    texto_efectivo_sin_marcadores,
)
from baco.server.services.orquestador.sesion import SesionChat
from baco.server.services.orquestador.validaciones import (
    combinar_tags,
    extraer_tipo_plantilla,
    interpretar_opcion,
    resolver_categoria,
    validar_longitud,
)
from baco.server.services.validar_articulo import sanitizar_borrador


ESTADOS_EDICION_LIBRE = {
    EstadoFlujo.ESPERANDO_PLANTILLA,
    EstadoFlujo.ESPERANDO_METADATOS,
    EstadoFlujo.REVISION_TIPO,
    EstadoFlujo.REVISION_METADATOS,

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
    # Resumen para el mensaje de guardado: (campo, detalle) aplicados y descartados con motivo.
    cambios: Optional[List[Tuple[str, str]]] = None
    descartes: Optional[List[Tuple[str, str]]] = None


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


def _sanitizar_tags_tematicos(
    tags: List[str],
    plantilla: Optional[str] = None,
) -> Tuple[List[str], Optional[str]]:
    """Sanitiza PII en cada tag temático manteniendo la plantilla fija."""
    tags_filtrados: List[str] = []
    avisos_priv: List[str] = []
    for t in tags:
        if not t or not t.strip():
            continue
        tp = extraer_tipo_plantilla([t])
        if tp is not None:
            if plantilla and tp == plantilla:
                tags_filtrados.append(tp)
            continue
        sanit_t = sanitizar_borrador(texto=t.strip(), sanitizar_redundancia_titulo=False)
        t_limpio = (sanit_t.get("texto_sanitizado") or t).strip()
        aviso_t = sanit_t.get("aviso_privacidad")
        if aviso_t and aviso_t not in avisos_priv:
            avisos_priv.append(aviso_t)
        if t_limpio:
            tags_filtrados.append(t_limpio)
    aviso_priv = "\n".join(avisos_priv) if avisos_priv else None
    return tags_filtrados, aviso_priv


def procesar_edicion_tags(
    tags: List[str],
    plantilla: Optional[str] = None,
) -> Tuple[Optional[List[str]], Optional[str]]:
    """Filtra, sanitiza y valida los tags provistos, preservando la plantilla fija y asegurando TAGS_MIN.

    Retorna: (tags_nuevos, error)
    """
    tags_filtrados, _ = _sanitizar_tags_tematicos(tags, plantilla=plantilla)
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
            def _linea(f):
                desc = str(f.get("description") or "").strip().rstrip(".")
                accion = str(f.get("action") or "").strip()
                return f"- **{desc}.**" + (f" {accion}" if accion else "") + f" _({f['severity']})_"
            detalle = "\n".join(_linea(f) for f in findings)
            return (
                f"⚠️ **Revisá la estructura de la plantilla {plantilla_evaluar.capitalize()}:**"
                f"\n\n{detalle}"
            )
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
        sesion.borrador.texto_original = txt_nuevo_limpio
    sesion.texto_editor = txt_nuevo_limpio
    sesion.texto_original = txt_nuevo_limpio

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
    Compara solo tags temáticos (tanto en crudo normalizado como tras sanitizar),
    excluyendo los de plantilla mediante extraer_tipo_plantilla.
    """
    if tags_req is None:
        return False
    tematicos_guardados = {
        t.strip().lower()
        for t in (tags_guardados or [])
        if t and t.strip() and extraer_tipo_plantilla([t]) is None
    }
    tematicos_req_crudo = {
        t.strip().lower()
        for t in tags_req
        if t and t.strip() and extraer_tipo_plantilla([t]) is None
    }
    if tematicos_req_crudo == tematicos_guardados:
        return False

    tags_sanit, _ = _sanitizar_tags_tematicos(tags_req, plantilla=plantilla)
    tematicos_req_sanit = {
        t.strip().lower()
        for t in tags_sanit
        if t and t.strip() and extraer_tipo_plantilla([t]) is None
    }
    return tematicos_req_sanit != tematicos_guardados


def aplicar_edicion_campos(
    sesion: SesionChat,
    req: ChatOrquestadorRequest,
) -> ResultadoEdicion:
    """Valida y aplica la edición de los campos que cambiaron respecto de su último valor validado
    en estados posteriores a la búsqueda de duplicados. Los campos no modificados se validan en silencio.
    """
    b = sesion.borrador
    det_req = getattr(req, "aviso_privacidad_detectado", None)

    tit_guardado = (b.titulo if b else sesion.titulo) or ""
    tiene_skill_vis = tiene_resultado_skill_visible(b)
    # Con resultado de skill visible, req.texto es el de la Vista previa: se compara contra él.
    txt_guardado = (b.texto_limpio if b else (sesion.texto_limpio or sesion.texto)) or ""
    cat_guardada = b.categoria_id if b else sesion.categoria_id
    tags_guardados = (b.tags if b else sesion.tags) or []
    plantilla_guardada = (
        (b.tipo_plantilla if b else sesion.tipo_plantilla)
        or extraer_tipo_plantilla(tags_guardados)
    )

    edita_titulo = titulo_difiere(req.titulo, tit_guardado)
    texto_req = req.texto if (req.texto is not None or tiene_skill_vis) else req.texto_editor
    edita_texto = texto_difiere(texto_req, txt_guardado, titulo_contexto=tit_guardado)
    # Con skill visible, el Editor conserva el texto fuente (no se envía; se usa para re-ejecutar la skill).
    edita_editor = bool(
        tiene_skill_vis and b is not None and req.texto_editor is not None
        and texto_difiere(req.texto_editor, b.texto_editor or "", titulo_contexto=tit_guardado)
    )

    opcion_actual = interpretar_opcion(req)
    es_continuar = opcion_actual in ("continuar", "finalizar", "editar")
    es_edicion_final = sesion.estado == EstadoFlujo.EDICION_FINAL
    es_revision = sesion.estado in (EstadoFlujo.REVISION_TIPO, EstadoFlujo.REVISION_METADATOS, EstadoFlujo.EDICION_FINAL)
    if es_edicion_final:
        es_continuar = True
    # En ESPERANDO_PLANTILLA no se aceptan categoría ni tags temáticos (se cargan en ESPERANDO_METADATOS).
    permite_metadatos = sesion.estado != EstadoFlujo.ESPERANDO_PLANTILLA

    edita_plantilla = False
    tipo_plantilla_nueva = None
    if es_continuar and req.tipo_plantilla is not None:
        try:
            edita_plantilla = plantilla_difiere(req.tipo_plantilla, plantilla_guardada)
        except ValueError as e:
            return ResultadoEdicion(ok=False, error=str(e))
        if edita_plantilla:
            tipo_plantilla_nueva = req.tipo_plantilla.strip().lower()
    elif es_revision and req.tipo_plantilla is not None:
        try:
            if plantilla_difiere(req.tipo_plantilla, plantilla_guardada):
                edita_plantilla = True
                tipo_plantilla_nueva = req.tipo_plantilla.strip().lower()
        except ValueError:
            edita_plantilla = False

    plantilla_efectiva = tipo_plantilla_nueva or plantilla_guardada

    descartes: List[Tuple[str, str]] = []

    # En ESPERANDO_PLANTILLA no se editan título ni texto (no hay botón para guardarlos):
    # se editan en el paso siguiente.
    if sesion.estado == EstadoFlujo.ESPERANDO_PLANTILLA and (edita_titulo or edita_texto or edita_editor):
        if edita_titulo:
            descartes.append(("Título", "no se edita en este paso; vas a poder cambiarlo en el siguiente"))
        if edita_texto or edita_editor:
            descartes.append(("Texto", "no se edita en este paso; vas a poder cambiarlo en el siguiente"))
        edita_titulo = edita_texto = edita_editor = False

    edita_categoria = False
    categoria_id_nueva = None
    categoria_nombre_nuevo = None
    if permite_metadatos and es_continuar and categoria_difiere(req.categoria_id, cat_guardada):
        edita_categoria = True
        categoria_id_nueva, categoria_nombre_nuevo, err_cat = procesar_edicion_categoria(
            req.categoria_id,
            sesion.categorias_disponibles,
        )
        if err_cat:
            return ResultadoEdicion(ok=False, error=err_cat)
    elif es_revision and categoria_difiere(req.categoria_id, cat_guardada):
        cat_id_val, cat_nom_val, err_cat = procesar_edicion_categoria(
            req.categoria_id,
            sesion.categorias_disponibles,
        )
        if not err_cat and cat_id_val is not None:
            edita_categoria = True
            categoria_id_nueva = cat_id_val
            categoria_nombre_nuevo = cat_nom_val
        else:
            descartes.append(("Categoría", err_cat or "no es válida; se mantuvo la anterior"))

    edita_tags = False
    tags_nuevos = None
    aviso_priv_tags = None
    if permite_metadatos and es_continuar and tags_difiere(
        req.tags,
        tags_guardados,
        plantilla=plantilla_efectiva,
    ):
        edita_tags = True
        _, aviso_priv_tags = _sanitizar_tags_tematicos(req.tags or [], plantilla=plantilla_efectiva)
        tags_nuevos, err_tags = procesar_edicion_tags(
            req.tags,
            plantilla=plantilla_efectiva,
        )
        if err_tags:
            return ResultadoEdicion(ok=False, error=err_tags)
    elif es_revision and tags_difiere(
        req.tags,
        tags_guardados,
        plantilla=plantilla_efectiva,
    ):
        _, aviso_priv_tags_rev = _sanitizar_tags_tematicos(req.tags or [], plantilla=plantilla_efectiva)
        tags_val, err_tags = procesar_edicion_tags(
            req.tags,
            plantilla=plantilla_efectiva,
        )
        if not err_tags and tags_val is not None:
            edita_tags = True
            tags_nuevos = tags_val
            aviso_priv_tags = aviso_priv_tags_rev
        else:
            descartes.append(("Etiquetas", err_tags or "no son válidas; se mantuvieron las anteriores"))

    if (
        not edita_titulo
        and not edita_texto
        and not edita_tags
        and not edita_categoria
        and not edita_plantilla
        and not edita_editor
    ):
        return ResultadoEdicion(
            ok=True,
            aviso_privacidad=det_req,
            opciones_sugeridas=(["finalizar"] if es_edicion_final else None),
            cambios=[],
            descartes=descartes,
        )

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
            texto_req,
            sesion,
            titulo_contexto=titulo_nuevo or tit_guardado,
            det_req=det_req,
        )
        if err_txt:
            return ResultadoEdicion(ok=False, error=err_txt)

    kwargs: Dict[str, Any] = {}
    if edita_plantilla and tipo_plantilla_nueva is not None:
        kwargs["tipo_plantilla"] = tipo_plantilla_nueva
        if tags_nuevos is None:
            tematicos_previos = [
                t for t in tags_guardados
                if t and t.strip() and extraer_tipo_plantilla([t]) is None
            ]
            tags_nuevos = combinar_tags(tipo_plantilla_nueva, tematicos_previos)
            kwargs["tags"] = tags_nuevos
    if edita_categoria and categoria_id_nueva is not None:
        kwargs["categoria_id"] = categoria_id_nueva
        if categoria_nombre_nuevo is not None:
            kwargs["categoria_nombre"] = categoria_nombre_nuevo
    if tags_nuevos is not None:
        kwargs["tags"] = tags_nuevos
    if edita_titulo:
        kwargs["titulo"] = titulo_nuevo

    if edita_texto:
        kwargs["bloques_texto"] = bloques_nuevos
        kwargs["recursos"] = recursos_nuevos
        kwargs["ultimo_id_recurso"] = ultimo_id_nuevo
        # Con skill visible, la edición es de la Vista previa: no pisa el texto fuente del Editor
        # y el resultado de la skill sigue pendiente de adoptar.
        if txt_nuevo_limpio is not None and not tiene_skill_vis:
            kwargs["texto_base_limpio"] = txt_nuevo_limpio
            kwargs["texto_editor"] = txt_nuevo_limpio
            kwargs["texto_original"] = txt_nuevo_limpio

    if edita_editor:
        txt_editor_san = sanitizar_borrador(texto=req.texto_editor)["texto_sanitizado"].strip()
        kwargs["texto_editor"] = txt_editor_san
        kwargs["texto_original"] = txt_editor_san

    if kwargs:
        sesion.actualizar_contenido_borrador(**kwargs)

    partes_aviso_priv = [p for p in (aviso_priv_tit, aviso_priv_txt, aviso_priv_tags) if p]
    if not partes_aviso_priv and det_req:
        partes_aviso_priv.append(det_req)
    aviso_priv_total = "\n".join(partes_aviso_priv) if partes_aviso_priv else None

    cambios: List[Tuple[str, str]] = []
    if edita_titulo:
        cambios.append(("Título", f"«{titulo_nuevo}»"))
    if edita_texto:
        n = len(txt_nuevo_limpio or "")
        donde = "Texto de la Vista previa" if tiene_skill_vis else "Texto"
        cambios.append((donde, f"actualizado ({n} caracteres)"))
    if edita_editor:
        cambios.append(("Texto original del Editor", "actualizado"))
    if edita_categoria and categoria_id_nueva is not None:
        cambios.append(("Categoría", categoria_nombre_nuevo or str(categoria_id_nueva)))
    if edita_plantilla and tipo_plantilla_nueva:
        cambios.append(("Tipo de plantilla", tipo_plantilla_nueva))
    if edita_tags and tags_nuevos is not None:
        tematicos = [t for t in tags_nuevos if t and extraer_tipo_plantilla([t]) is None]
        cambios.append(("Etiquetas", ", ".join(tematicos) or "sin etiquetas temáticas"))

    return ResultadoEdicion(
        ok=True,
        opciones_sugeridas=(["finalizar"] if es_edicion_final else None),
        # Parte 3: en EDICION_FINAL el guardado es silencioso (sin aviso de estructura).
        aviso=(None if es_edicion_final else aviso_plantilla),
        aviso_privacidad=aviso_priv_total,
        titulo_nuevo=titulo_nuevo,
        bloques_nuevos=bloques_nuevos,
        recursos_nuevos=recursos_nuevos,
        txt_nuevo_limpio=txt_nuevo_limpio,
        ultimo_id_nuevo=ultimo_id_nuevo,
        categoria_id_nueva=categoria_id_nueva,
        categoria_nombre_nuevo=categoria_nombre_nuevo,
        tags_nuevos=tags_nuevos,
        tipo_plantilla_nueva=tipo_plantilla_nueva,
        cambios=cambios,
        descartes=descartes,
    )


def adoptar_resultado_skill_pendiente(sesion: SesionChat) -> None:
    """Si hay un resultado de skill pendiente, lo adopta como texto vigente del borrador y la sesión."""
    b = sesion.borrador
    if b is None:
        return

    if getattr(b, "resultado_skill_pendiente", False):
        bloques_adoptados = list(b.bloques_texto) if b.bloques_texto else []
        texto_adoptado = b.texto_limpio
        sesion.actualizar_contenido_borrador(
            bloques_texto=bloques_adoptados,
            texto_base_limpio=texto_adoptado,
            texto_editor=texto_adoptado,
            texto_original=texto_adoptado,
            resultado_skill_desactualizado=False,
            resultado_skill_pendiente=False,
        )
        b.skill_pendiente = None


_DIR_REFERENCIAS_PLANTILLAS = Path(__file__).resolve().parents[3] / "skills" / "plantillas" / "references"
# Solo para extraer piezas literales del archivo de plantilla (no se aplican como regex sobre el texto).
_RE_PLACEHOLDER_TPL = re.compile(r"\[[^\]\n]+\]")
_RE_ETIQUETA_BRACKET_TPL = re.compile(r"\*\*\[[^\]\n]+\][^*\n]*\*\*")
_RE_ETIQUETA_TPL = re.compile(r"\*\*([^*\[\n]+?:)\*\*")
_RE_LINEA_VACIA_ESTRUCTURA = re.compile(r"^[\s\-*>#\d.:()]*$")


def _norm_encabezado(linea: str) -> str:
    return linea.strip().lstrip("#").strip().strip("*").strip().rstrip(":").strip().lower()


@lru_cache(maxsize=None)
def _estructura_plantilla(plantilla: str) -> Tuple[frozenset, Tuple[str, ...], Tuple[str, ...], frozenset]:
    """Lee references/plantilla-<tipo>.md y devuelve, literal: (encabezados, etiquetas en negrita,
    placeholders, líneas de la plantilla). Se omite la cabecera interna (título y aclaración de metadatos)."""
    ruta = _DIR_REFERENCIAS_PLANTILLAS / f"plantilla-{(plantilla or '').strip().lower()}.md"
    try:
        crudo = ruta.read_text(encoding="utf-8")
    except OSError:
        return frozenset(), (), (), frozenset()
    lineas = [l for l in crudo.splitlines() if l.strip()]
    lineas = [
        l for l in lineas
        if not l.strip().lower().startswith("# plantilla de salida")
        and not l.strip().startswith("La salida debe contener")
    ]
    cuerpo = "\n".join(lineas)
    encabezados = frozenset(_norm_encabezado(l) for l in lineas if l.lstrip().startswith("#"))
    etiquetas_bracket = tuple(dict.fromkeys(_RE_ETIQUETA_BRACKET_TPL.findall(cuerpo)))
    etiquetas = tuple(dict.fromkeys(f"**{e}**" for e in _RE_ETIQUETA_TPL.findall(cuerpo)))
    placeholders = tuple(dict.fromkeys(_RE_PLACEHOLDER_TPL.findall(cuerpo)))
    return (
        encabezados,
        etiquetas_bracket + etiquetas,
        placeholders,
        frozenset(l.strip() for l in lineas),
    )


def texto_tiene_estructura_plantilla(texto: str, plantilla: Optional[str]) -> bool:
    """True si el texto trae encabezados o etiquetas literales de la plantilla indicada."""
    if not texto or not plantilla:
        return False
    encabezados, etiquetas, _, _ = _estructura_plantilla(plantilla)
    for linea in texto.splitlines():
        if linea.lstrip().startswith("#") and _norm_encabezado(linea) in encabezados:
            return True
    return any(e in texto for e in etiquetas)


def limpiar_estructura_plantilla(texto: str, plantilla: Optional[str]) -> str:
    """Quita de forma determinista la estructura de la plantilla anterior (encabezados, etiquetas en
    negrita y placeholders sin completar, tomados literalmente de references/plantilla-*.md),
    conservando todo lo que la persona escribió."""
    if not texto or not plantilla:
        return texto or ""
    encabezados, etiquetas, placeholders, lineas_tpl = _estructura_plantilla(plantilla)
    if not encabezados and not etiquetas:
        return texto
    salida: List[str] = []
    for linea in texto.splitlines():
        crudo = linea.strip()
        if crudo in lineas_tpl and crudo:
            continue
        if crudo and _norm_encabezado(crudo) in encabezados and (
            crudo.startswith("#") or crudo.startswith("**") or crudo == _norm_encabezado(crudo)
        ):
            continue
        nueva = linea
        for e in etiquetas:
            nueva = nueva.replace(e, "")
        for ph in placeholders:
            nueva = nueva.replace(ph, "")
        if nueva != linea and _RE_LINEA_VACIA_ESTRUCTURA.match(nueva):
            continue
        salida.append(nueva.rstrip() if nueva != linea else nueva)
    limpio = "\n".join(salida)
    limpio = re.sub(r"\n{3,}", "\n\n", limpio).strip()
    return limpio or texto


async def ejecutar_skill(
    sesion: SesionChat,
    req: ChatOrquestadorRequest,
    skill: str,
    es_reaplicacion: bool = False,
) -> ChatOrquestadorResponse:
    """Ejecuta la skill ('plantilla' o 'auditor') sobre el texto original del Editor.
    El resultado va solo a b.bloques_texto y sesion.bloques_texto (Vista previa).
    El texto original se preserva en texto_original, texto_editor y texto_base_limpio (Editor).
    No sincroniza sesion.texto_limpio ni sesion.texto con el resultado de la skill hasta 'Continuar'.
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
                "Para auditar el artículo, primero es necesario definir la **categoría** y al menos una **etiqueta** temática."
            )
            return construir_respuesta(sesion, msg_falta_meta, sesion.ultimas_opciones)

    # Encadenamiento: el auditor audita la salida de plantillas pendiente (Vista previa, con retoques).
    plantilla_pendiente_visible = (
        es_auditor
        and not es_reaplicacion
        and getattr(b, "resultado_skill_pendiente", False)
        and (getattr(b, "skill_pendiente", None) or "").lower() == "plantilla"
        and bool(b.texto_limpio)
    )
    if plantilla_pendiente_visible:
        texto_vigente = b.texto_limpio.strip()
    elif es_auditor and es_reaplicacion and (b.texto_editor or sesion.texto_editor):
        # Reauditar usa el Editor (entrada previa del auditor), no el original verdadero.
        texto_vigente = (b.texto_editor or sesion.texto_editor or "").strip()
    elif es_reaplicacion and (getattr(sesion, "texto_original", None) or getattr(b, "texto_original", None)):
        texto_vigente = (getattr(sesion, "texto_original", None) or getattr(b, "texto_original", None) or "").strip()
    elif getattr(b, "resultado_skill_pendiente", False) and (
        getattr(b, "texto_original", None)
        or getattr(sesion, "texto_original", None)
        or getattr(b, "texto_editor", None)
        or getattr(sesion, "texto_editor", None)
    ):
        texto_vigente = (
            b.texto_editor
            or sesion.texto_editor
            or b.texto_original
            or sesion.texto_original
            or ""
        ).strip()
    else:
        texto_vigente = (
            b.texto_editor
            or sesion.texto_editor
            or b.texto_limpio
            or sesion.texto_limpio
            or b.texto_base_limpio
            or sesion.texto
            or ""
        ).strip()

    texto_origen = texto_efectivo_sin_marcadores(texto_vigente)
    # Mismo límite que skills_habilitadas en la API REST: antes el texto largo se truncaba en silencio.
    if len(texto_origen) > TEXTO_MAX:
        msg_largo = (
            f"El texto tiene **{len(texto_origen)} caracteres** y supera el límite de **{TEXTO_MAX}** "
            f"para {'auditar' if es_auditor else 'aplicar la plantilla'}. Acortalo o dividilo y volvé a intentar."
        )
        return construir_respuesta(sesion, msg_largo, sesion.ultimas_opciones)
    # El auditor no pisa el original verdadero (solo lo lee plantillas al reaplicar).
    if not es_auditor or not (b.texto_original or sesion.texto_original):
        sesion.texto_original = texto_origen
        b.texto_original = texto_origen

    baco = getattr(req, "_baco_agent", None) or getattr(sesion, "_baco_agent", None)
    if baco is None:
        try:
            from baco.server.app.dependencies import get_baco_agent
            baco = get_baco_agent()
        except Exception:
            baco = None

    if baco is None or not callable(baco):
        msg_sin_agente = (
            "No pudimos **aplicar la plantilla** en este momento. Por favor, intentá nuevamente."
            if not es_auditor
            else "No pudimos **auditar el artículo** en este momento. Por favor, intentá nuevamente."
        )
        return construir_respuesta(sesion, msg_sin_agente, sesion.ultimas_opciones)

    bloques_anteriores = list(b.bloques_texto) if b.bloques_texto else []
    try:
        b.bloques_texto = [texto_origen] if texto_origen else []
        if es_auditor:
            from baco.server.services.agente_service import ejecutar_skill_validador
            dictamen, texto_corr =  await asyncio.wait_for(
                run_in_threadpool(ejecutar_skill_validador, b, baco), timeout=180
            )
            resultado = (texto_corr or dictamen or "").strip()
        else:
            from baco.server.services.agente_service import ejecutar_skill_plantillas
            resultado = (await asyncio.wait_for(
                run_in_threadpool(ejecutar_skill_plantillas, sesion.session_id, b, baco), timeout=180
            ) or "").strip()


        if not resultado:
            raise ValueError("La skill no devolvió contenido.")
    except Exception:
        b.bloques_texto = bloques_anteriores
        sesion.bloques_texto = list(bloques_anteriores)
        msg_error = (
            "No pudimos aplicar la **plantilla** en este momento. Por favor, intentá nuevamente."
            if not es_auditor
            else "No pudimos **auditar** el artículo en este momento. Por favor, intentá nuevamente."
        )
        return construir_respuesta(sesion, msg_error, sesion.ultimas_opciones)

    b.bloques_texto = [resultado]
    sesion.bloques_texto = [resultado]

    if not es_auditor or not (b.texto_original or sesion.texto_original):
        b.texto_original = texto_origen
        sesion.texto_original = texto_origen
    b.texto_editor = texto_origen
    sesion.texto_editor = texto_origen
    b.texto_base_limpio = texto_origen
    sesion.texto_limpio = texto_origen

    b.resultado_skill_desactualizado = False
    b.resultado_skill_pendiente = True
    b.skill_pendiente = skill_nombre
    b.skill_aplicada = skill_nombre
    sesion.skill_aplicada = skill_nombre

    if sesion.estado == EstadoFlujo.EDICION_FINAL:
        from baco.server.services.orquestador.mensajes import OPCIONES_EDICION_FINAL
        opciones = list(OPCIONES_EDICION_FINAL)
    else:
        # Contrato: después de la skill del paso solo queda Continuar (sin Volver).
        opciones = ["continuar"]
    if es_reaplicacion:
        msg = (
            "Reaplicamos la **plantilla** sobre el texto del **Editor**. El nuevo resultado está en la **Vista previa**; "
            "al tocar **Continuar** o **Finalizar** se toma solo la Vista previa y el Editor se reemplaza por ella."
            if not es_auditor
            else "Reauditamos el artículo con el texto del **Editor**. El nuevo resultado está en la **Vista previa**; "
            "al tocar **Continuar** o **Finalizar** se toma solo la Vista previa y el Editor se reemplaza por ella."
        )
    else:
        msg = (
            f"🤖 Apliqué la plantilla **{(b.tipo_plantilla or extraer_tipo_plantilla(b.tags or []) or '').capitalize()}**. El resultado está en la **Vista previa** y tu texto original "
            "quedó intacto en el **Editor**. Solo se enviará el texto de la Vista previa. Lo que cambies en el "
            "**Editor** solo se usa si volvés a aplicar la skill; al tocar **Continuar**, el Editor se reemplaza por la Vista previa. "
            "Tocá **Continuar** cuando esté listo."
            if not es_auditor
            else "🤖 Revisé el texto. El resultado está en la **Vista previa** y tu texto original quedó "
            "intacto en el **Editor**. Solo se enviará el texto de la Vista previa. Lo que cambies en el **Editor** "
            "solo se usa si volvés a auditar; al tocar **Continuar**, el Editor se reemplaza por la Vista previa. "
            "Tocá **Continuar** cuando esté listo."
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
        return construir_respuesta(sesion, "- Reaplicar skill?", sesion.ultimas_opciones)

    skill = (b.skill_pendiente or "plantilla").lower()
    return await ejecutar_skill(sesion, req, skill=skill, es_reaplicacion=True)
