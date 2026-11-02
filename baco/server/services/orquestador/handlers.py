import re
from typing import Callable, Coroutine, Dict, Optional, Tuple

from starlette.concurrency import run_in_threadpool

from baco.server.config_limites import (
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    EstadoFlujo,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.mensajes import (
    MSG_DESCARTAR_COINCIDENCIA_TITULO,
    MSG_ELEGIR_PLANTILLA,
    MSG_OPERACION_CANCELADA,
    MSG_PEDIR_EDICION,
    MSG_RECHAZADO,
    MSG_SIN_COINCIDENCIAS_TITULO,
    MSG_TEXTO_EN_EDICION,
    MSG_USAR_CONTINUAR,
    OPCIONES_ENRIQUECER_CONTINUAR,
    OPCIONES_ENRIQUECER_DESCARTAR,
    OPCIONES_SERIE_DECISION,
    OPCIONES_PLANTILLAS,
    OPCIONES_REINICIAR,
    OPCIONES_FINALIZADO,
    MSG_BORRADOR_FINALIZADO,
    OPCIONES_REVISION_BLOQUEANTE,
    OPCIONES_REVISION_VALIDO,
    PREFIJO_BORRADOR_ACTUALIZADO,
    PREFIJO_CONTINUAR_PROPIO,
    PREFIJO_DATOS_SANITIZADOS,
    PREFIJO_ERROR_CONFORMIDAD,
    PREFIJO_METADATOS_REGISTRADOS,
    PREFIJO_SIN_DUPLICADOS,
    msg_actualizar_serie_cargado,
    msg_articulo_muy_largo,
    msg_coincidencia,
    msg_enriquecer_cargado,
    msg_error_longitud_maxima,
    msg_error_longitud_minima,
    msg_opcion_invalida,
    msg_pedir_categoria,
    msg_pedir_metadatos,
    msg_categoria_ambigua,
    msg_categoria_no_encontrada,
    msg_pedir_tag_adicional,
    msg_pedir_tags_y_categoria,
    msg_texto_vacio,
    prefijo_borrador_creado,
)
from baco.server.services.orquestador.recursos_service import (
    _max_num_recurso,
    extraer_recursos_y_bloques_texto,
    fusionar_bloques_y_recursos_sin_colision,
    procesar_recursos_y_bloques,
    texto_efectivo_sin_marcadores,
)
from baco.server.services.orquestador.retroceso import (
    resetear_enriquecimiento_descartado,
    retroceder,
)
from baco.server.services.orquestador.sesion import SesionChat, clave_busqueda
from baco.server.services.orquestador.continuar import (
    _registrar_finalizado,
    continuar,
    continuar_desde_revision,
)
from baco.server.services.orquestador.validaciones import (
    DICCIONARIO_OFICIAL_CATEGORIAS,
    actualizar_metadatos_sesion,
    cargar_datos_articulo,
    combinar_tags,
    consolidar_texto_enriquecimiento,
    construir_respuesta,
    extraer_tipo_plantilla,
    normalizar_coincidencias,
    parsear_metadatos_mensaje,
    resolver_categoria,
    validar_borrador,
    validar_longitud,
    validar_longitud_maxima,
    verificar_compuerta_avance,
)
from baco.server.services.validar_articulo import sanitizar_borrador
from baco.server.services.orquestador.edicion import (
    _sanitizar_tags_tematicos,
    aplicar_edicion_campos,
    categoria_difiere,
    plantilla_difiere,
    tags_difiere,
    texto_difiere,
    tiene_resultado_skill_visible,
    titulo_difiere,
)


async def handle_esperando_titulo(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    titulo = (req.titulo or req.mensaje or "").strip()
    sanit_tit = sanitizar_borrador(texto="", titulo=titulo, sanitizar_redundancia_titulo=False)
    titulo = (sanit_tit["titulo_sanitizado"] or titulo).strip()
    aviso_priv = sanit_tit.get("aviso_privacidad") or getattr(req, "aviso_privacidad_detectado", None)

    if not titulo:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(
            sesion,
            msg_error_longitud_minima("título", TITULO_MIN, intento),
            [],
            aviso_privacidad=aviso_priv,
        )

    if len(titulo) < TITULO_MIN:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(
            sesion,
            msg_error_longitud_minima("título", TITULO_MIN, intento),
            [],
            aviso_privacidad=aviso_priv,
        )

    if len(titulo) > TITULO_MAX:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(
            sesion,
            msg_error_longitud_maxima("título", TITULO_MAX, intento),
            [],
            aviso_privacidad=aviso_priv,
        )

    sesion.limpiar_fallos("ESPERANDO_TITULO")
    sesion.titulo = titulo
    actualizar_metadatos_sesion(sesion, req)

    clave_tit = clave_busqueda("titulo", titulo)
    omitir_tit = clave_tit in sesion.busquedas_descartadas
    if omitir_tit:
        res_tit = None
    else:
        res_tit = await run_in_threadpool(buscador.evaluar_titulo, titulo, 1)
    if res_tit and res_tit.get("coincidencias"):
        es_serie = "serie" in (res_tit.get("mensaje") or "").lower()
        coincs = normalizar_coincidencias(
            res_tit["coincidencias"],
            mensaje=res_tit.get("mensaje", ""),
            tipo_coincidencia="serie" if es_serie else "duplicado",
        )
        coincs = [c for c in coincs if c.id not in sesion.articulos_descartados_ids and not (sesion.descarto_serie and c.tipo_coincidencia == "serie")]
        if coincs:
            sesion.coincidencias = coincs
            sesion.estado = EstadoFlujo.DECISION_TITULO
            primero = sesion.coincidencias[0]
            ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
            return construir_respuesta(
                sesion,
                msg_coincidencia(res_tit["mensaje"], primero.titulo, primero.url),
                ops,
                aviso_privacidad=aviso_priv,
            )

    sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
    return construir_respuesta(
        sesion,
        f"Omití las coincidencias que ya descartaste. {MSG_SIN_COINCIDENCIAS_TITULO.replace('No encontré nada similar', 'No encontré nada nuevo')}" if omitir_tit else MSG_SIN_COINCIDENCIAS_TITULO,
        ["confirmar_texto", "volver"],
        aviso_privacidad=aviso_priv,
    )


def _consolidar_bloques_y_recursos_enriquecimiento(
    bloques_base: list[str],
    recs_base: Dict[str, object],
    texto_aporte_raw: str,
    ultimo_id: int = 0,
    validar_marcadores_existentes: bool = True,
    forzar_preservar_base: bool = False,
) -> Tuple[list[str], Dict[str, object], Optional[str], Optional[str]]:

    texto_base_limpio = "\n\n".join(bloques_base).strip()
    raw = (texto_aporte_raw or "").strip()
    if not raw:
        return list(bloques_base), dict(recs_base), None, None

    if validar_marcadores_existentes:
        marcadores_encontrados = re.findall(r"\[\[(?:recurso:([a-zA-Z0-9_\-]+)|(R\d+))\]\]", raw)
        invalidos = []
        for m_rec, m_r in marcadores_encontrados:
            if m_r:
                invalidos.append(f"[[{m_r}]]")
            elif m_rec and m_rec not in (recs_base or {}):
                invalidos.append(f"[[recurso:{m_rec}]]")
        if invalidos:
            msg_err = (
                f"El texto contiene marcadores no válidos ({', '.join(invalidos)}). "
                "Los recursos multimedia deben adjuntarse mediante enlaces o subida de archivos, no escribiendo marcadores manualmente."
            )
            return list(bloques_base), dict(recs_base), None, msg_err

    bloques_aporte, recs_nuevos = extraer_recursos_y_bloques_texto(
        raw,
        recursos_previos=recs_base,  # type: ignore[arg-type]
        ultimo_id=max(ultimo_id, _max_num_recurso(recs_base)),  # type: ignore[arg-type]
    )
    tl_aporte = "\n\n".join(bloques_aporte).strip()

    es_adicion_separada = bool(
        texto_base_limpio
        and tl_aporte
        and texto_base_limpio not in tl_aporte
        and (forzar_preservar_base or len(tl_aporte) <= 70)
    )

    if es_adicion_separada:
        sanit = sanitizar_borrador(texto=tl_aporte)
        aviso_priv = sanit.get("aviso_privacidad")
        bloques_aporte_san = [
            sanitizar_borrador(texto=b)["texto_sanitizado"].strip()
            for b in bloques_aporte
            if b.strip()
        ]
        bloques_aporte_san = [b for b in bloques_aporte_san if b]

        hay_recurso_al_final_base = any(
            getattr(r, "posicion", 0) == len(bloques_base) - 1
            for r in (recs_base or {}).values()
        )
        if not bloques_base:
            bloques_finales = bloques_aporte_san
            offset_pos = 0
        elif hay_recurso_al_final_base or not bloques_aporte_san:
            bloques_finales = list(bloques_base) + bloques_aporte_san
            offset_pos = len(bloques_base)
        else:
            # Regla 6: adiciones con bloques existentes se agregan al final del último bloque de texto
            fusion_ultimo = f"{bloques_base[-1]}\n\n{bloques_aporte_san[0]}".strip()
            bloques_finales = list(bloques_base[:-1]) + [fusion_ultimo] + bloques_aporte_san[1:]
            offset_pos = len(bloques_base) - 1

        recs_nuevos_desplazados = {}
        for k, r in recs_nuevos.items():
            pos_orig = getattr(r, "posicion", 0)
            nueva_pos = (pos_orig + offset_pos) if pos_orig >= 0 else max(0, offset_pos - 1)
            recs_nuevos_desplazados[k] = r.model_copy(update={"posicion": nueva_pos})

        bloques_fused, recs_fused = fusionar_bloques_y_recursos_sin_colision(
            bloques_finales,
            recs_base,  # type: ignore[arg-type]
            recs_nuevos_desplazados,
            ultimo_id=max(ultimo_id, _max_num_recurso(recs_base)),  # type: ignore[arg-type]
        )
        return bloques_fused, recs_fused, aviso_priv, None

    texto_consolidado, aviso_priv = consolidar_texto_enriquecimiento(texto_base_limpio, tl_aporte)
    bloques_consolidados = (
        [b.strip() for b in re.split(r"\n\s*\n", texto_consolidado) if b.strip()]
        if texto_consolidado.strip()
        else []
    )
    bloques_fused, recs_fused = fusionar_bloques_y_recursos_sin_colision(
        bloques_consolidados,
        recs_base,  # type: ignore[arg-type]
        recs_nuevos,
        ultimo_id=max(ultimo_id, _max_num_recurso(recs_base)),  # type: ignore[arg-type]
    )
    return bloques_fused, recs_fused, aviso_priv, None


async def handle_decision_titulo(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    actualizar_metadatos_sesion(sesion, req)
    if opcion in ("enriquecer", "actualizar"):
        sesion.limpiar_fallos("DECISION_TITULO")
        if not sesion.coincidencias:
            sesion.estado = EstadoFlujo.ESPERANDO_TITULO
            return construir_respuesta(
                sesion,
                "No se encontró la coincidencia previa seleccionada. Por favor, ingresá el título de tu artículo:",
                [],
            )
        elegido = sesion.coincidencias[0]
        if (
            sesion.borrador is not None
            and sesion.borrador.modo == 'enriquecimiento'
            and sesion.borrador.articulo_original_id == elegido.id
        ):
            if req.texto is not None and req.texto.strip():
                texto_enviado = sanitizar_borrador(texto=req.texto.strip())["texto_sanitizado"].strip()
                sesion.borrador.texto_editor = texto_enviado
                sesion.texto_editor = texto_enviado
                sesion.texto_en_edicion = texto_enviado
            if req.tags is not None:
                sesion.borrador.tags = list(req.tags)
                sesion.tags = list(req.tags)
            if req.categoria_id is not None:
                sesion.borrador.categoria_id = req.categoria_id
                sesion.categoria_id = req.categoria_id
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            es_serie = elegido.tipo_coincidencia == 'serie' or opcion == 'actualizar'
            msg_carga = (
                msg_actualizar_serie_cargado(elegido.id, elegido.titulo)
                if es_serie
                else msg_enriquecer_cargado(elegido.id, elegido.titulo)
            )
            return construir_respuesta(
                sesion,
                msg_carga,
                ['confirmar_texto', 'descartar', 'volver'],
            )
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        bloques_base, recs_base = extraer_recursos_y_bloques_texto(
            texto_base, ultimo_id=sesion.ultimo_id_recurso
        )
        texto_base_limpio = "\n\n".join(bloques_base).strip()
        if validar_longitud_maxima(texto_base_limpio, TEXTO_MAX_PERCENTIL_99, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX_PERCENTIL_99), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_enviado = (req.texto or "").strip()
        # Enriquecer/actualizar por título:
        # El Editor contiene ÚNICAMENTE lo escrito por la persona (texto_enviado, normalmente "")
        # La Vista previa arranca con los bloques y recursos del artículo original
        bloques_finales = list(bloques_base)
        recursos = recs_base
        aviso_priv = None

        max_id = max(sesion.ultimo_id_recurso, _max_num_recurso(recursos))

        es_serie = elegido.tipo_coincidencia == "serie" or opcion == "actualizar"
        titulo_borrador = (sesion.titulo or req.titulo or elegido.titulo).strip() if es_serie else elegido.titulo

        nom_cat = DICCIONARIO_OFICIAL_CATEGORIAS.get(cat_db, f"Categoría {cat_db}") if cat_db else "Sin categoría"
        meta_ant = {
            "categoria_id": cat_db,
            "categoria_nombre": nom_cat,
            "tags": list(tags_db or []),
        } if (cat_db or tags_db) else None

        sesion.borrador = BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=elegido.id,
            articulo_original_url=elegido.url,
            titulo=titulo_borrador,
            bloques_texto=bloques_finales,
            texto_base_limpio=texto_base_limpio,
            texto_editor=texto_enviado,
            recursos=recursos,
            ultimo_id_recurso=max_id,
            contenido_adicional=list(sesion.contenido_adicional),
            tipo_plantilla=extraer_tipo_plantilla(tags_ini),
            categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
            tags=tags_ini,
            metadatos_anteriores=meta_ant,
            metadatos_heredados_revisados=False,
        )
        sesion.texto_editor = texto_enviado
        sesion.texto_en_edicion = texto_enviado
        sesion.metadatos_anteriores = meta_ant
        sesion.metadatos_heredados_revisados = False
        sesion.actualizar_contenido_borrador(
            bloques_texto=list(sesion.borrador.bloques_texto),
            texto_base_limpio=texto_base_limpio,
            texto_editor=texto_enviado,
            recursos=dict(sesion.borrador.recursos),
            ultimo_id_recurso=max_id,
        )
        texto_limpio = sesion.borrador.texto_limpio

        err = validar_longitud(texto_limpio, TEXTO_MIN, TEXTO_MAX_PERCENTIL_99, "texto")
        if err:
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            return construir_respuesta(sesion, err, ["confirmar_texto", "descartar", "volver"])

        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        sesion.texto_en_edicion = texto_enviado
        msg_carga = (
            msg_actualizar_serie_cargado(elegido.id, elegido.titulo)
            if es_serie
            else msg_enriquecer_cargado(elegido.id, elegido.titulo)
        )
        return construir_respuesta(
            sesion,
            msg_carga,
            ["confirmar_texto", "descartar", "volver"],
            aviso_privacidad=aviso_priv,
        )

    if opcion in ("descartar", "continuar"):
        sesion.limpiar_fallos("DECISION_TITULO")
        if sesion.titulo:
            sesion.busquedas_descartadas.add(clave_busqueda("titulo", sesion.titulo))
        for c in sesion.coincidencias:
            if c.tipo_coincidencia == "serie" or "serie" in getattr(c, "mensaje", "").lower():
                sesion.descarto_serie = True
            if c.id and c.id not in sesion.articulos_descartados_ids:
                sesion.articulos_descartados_ids.append(c.id)
        sesion.coincidencias = []
        texto_disponible = (req.texto or sesion.texto_limpio or sesion.texto or "").strip()
        if texto_disponible:
            bloques_disp, recs_disp, _ = procesar_recursos_y_bloques(
                texto_disponible,
                recursos_previos=sesion.recursos,
                ultimo_id=sesion.ultimo_id_recurso,
                validar_marcadores_existentes=False,
            )
            txt_disp_limpio = "\n\n".join(bloques_disp).strip()
        else:
            bloques_disp, txt_disp_limpio, recs_disp = [], "", sesion.recursos

        if txt_disp_limpio and len(texto_efectivo_sin_marcadores(txt_disp_limpio)) >= TEXTO_MIN:
            sanit_txt = sanitizar_borrador(texto=txt_disp_limpio, titulo=sesion.titulo)
            aviso_privacidad = sanit_txt.get("aviso_privacidad")
            bloques_san = [
                sanitizar_borrador(texto=b)["texto_sanitizado"].strip()
                for b in bloques_disp
                if b.strip()
            ]
            bloques_san = [b for b in bloques_san if b]
            max_id = max(sesion.ultimo_id_recurso, _max_num_recurso(recs_disp))
            sesion.actualizar_contenido_borrador(
                bloques_texto=bloques_san,
                recursos=recs_disp,
                ultimo_id_recurso=max_id,
            )
            texto_busqueda = texto_efectivo_sin_marcadores(sesion.texto_limpio)
            clave_txt = clave_busqueda("texto", texto_busqueda)
            omitir_txt = clave_txt in sesion.busquedas_descartadas
            if omitir_txt:
                res_txt = None
            else:
                res_txt = await run_in_threadpool(
                    buscador.evaluar_texto, texto_busqueda, True, sesion.titulo, 1, sesion.descarto_serie
                )
            if res_txt and res_txt.get("coincidencias"):
                coincs = normalizar_coincidencias(
                    res_txt["coincidencias"], mensaje=res_txt.get("mensaje", ""), tipo_coincidencia="semantico"
                )
                coincs = [c for c in coincs if c.id not in sesion.articulos_descartados_ids and not (sesion.descarto_serie and c.tipo_coincidencia == "serie")]
                if coincs:
                    sesion.coincidencias = coincs
                    sesion.estado = EstadoFlujo.DECISION_TEXTO
                    primero = sesion.coincidencias[0]
                    return construir_respuesta(
                        sesion,
                        msg_coincidencia(res_txt["mensaje"], primero.titulo, primero.url),
                        OPCIONES_ENRIQUECER_CONTINUAR,
                        aviso_privacidad=aviso_privacidad,
                    )

            sesion.contenido_adicional = []
            sesion.borrador = BorradorSesion(
                modo="nuevo",
                titulo=sesion.titulo,
                bloques_texto=sesion.bloques_texto,
                recursos=sesion.recursos,
                ultimo_id_recurso=max_id,
                contenido_adicional=[],
                tipo_plantilla=(sesion.borrador.tipo_plantilla if sesion.borrador else None) or extraer_tipo_plantilla(sesion.tags),
                categoria_id=req.categoria_id or sesion.categoria_id,
                tags=list(req.tags or sesion.tags),
            )
            sesion.texto = sesion.borrador.texto_alineado_discourse
            pref = (
                f"Omití las coincidencias que ya descartaste. {PREFIJO_SIN_DUPLICADOS}"
                if omitir_txt
                else PREFIJO_SIN_DUPLICADOS
            )
            return continuar(
                sesion, prefijo=pref, aviso_privacidad=aviso_privacidad
            )

        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(sesion, MSG_DESCARTAR_COINCIDENCIA_TITULO, ["confirmar_texto", "volver"])

    if opcion == "volver":
        return retroceder(sesion)

    intento = sesion.registrar_fallo("DECISION_TITULO")
    elegido = sesion.coincidencias[0] if sesion.coincidencias else None
    es_serie = elegido and elegido.tipo_coincidencia == "serie"
    ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
    return construir_respuesta(sesion, msg_opcion_invalida(intento), ops)


async def handle_esperando_texto(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    if opcion == "volver":
        return retroceder(sesion)

    if opcion in ("descartar", "continuar"):
        resetear_enriquecimiento_descartado(sesion, agregar_a_descartados=True, texto_extra=req.texto)

        texto_directo = (req.texto or "").strip()
        if not texto_directo:
            return construir_respuesta(
                sesion,
                " Descartamos el artículo existente. Ingresá el texto o los pasos para redactar tu propio artículo:",
                ["confirmar_texto", "volver"],
            )

    ops_texto = (
        ["confirmar_texto", "descartar", "volver"]
        if (sesion.borrador and sesion.borrador.modo == "enriquecimiento")
        else ["confirmar_texto", "volver"]
    )
    es_confirmacion = (
        opcion == "confirmar_texto"
        or (req.accion and req.accion.strip().lower() in ("confirmar_texto", "confirmar texto", "confirmar"))
        or (opcion in ("descartar", "continuar") and bool(req.texto and req.texto.strip()))
    )

    if not es_confirmacion:
        fragmento = (req.texto if req.texto is not None else (req.mensaje or "")).strip()
        if not fragmento:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO")
            return construir_respuesta(sesion, msg_texto_vacio(intento), ops_texto)

        recursos_prev = (
            sesion.borrador.recursos
            if (sesion.borrador is not None and sesion.borrador.recursos)
            else sesion.recursos
        )
        ultimo_id_prev = max(
            sesion.ultimo_id_recurso,
            sesion.borrador.ultimo_id_recurso if sesion.borrador else 0,
            _max_num_recurso(recursos_prev),
        )
        bloques_frag, recs_nuevos_frag = extraer_recursos_y_bloques_texto(
            fragmento,
            recursos_previos=recursos_prev,
            ultimo_id=ultimo_id_prev,
        )
        frag_tl = "\n\n".join(bloques_frag).strip()
        sanit_frag = sanitizar_borrador(texto=frag_tl, titulo=sesion.titulo)
        fragmento_limpio = sanit_frag["texto_sanitizado"]
        aviso_priv_frag = sanit_frag.get("aviso_privacidad")

        bloques_existentes = (
            list(sesion.borrador.bloques_texto)
            if (sesion.borrador is not None and sesion.borrador.bloques_texto)
            else list(sesion.bloques_texto)
        )
        if req.texto is not None:
            nuevos_bloques = [b.strip() for b in bloques_frag if b.strip()]
            nuevos_bloques = [sanitizar_borrador(texto=b)["texto_sanitizado"].strip() for b in nuevos_bloques]
            nuevos_bloques = [b for b in nuevos_bloques if b]
            nuevo_borrador_txt = "\n\n".join(nuevos_bloques).strip()
            _, recs_combinados = fusionar_bloques_y_recursos_sin_colision(
                nuevos_bloques, recursos_prev, recs_nuevos_frag, ultimo_id=ultimo_id_prev
            )
        elif bloques_existentes:

            ultimo_bloque = f"{bloques_existentes[-1]}\n\n{fragmento_limpio}".strip() if fragmento_limpio else bloques_existentes[-1]
            nuevos_bloques = list(bloques_existentes[:-1]) + ([ultimo_bloque] if ultimo_bloque else [])
            nuevo_borrador_txt = "\n\n".join(nuevos_bloques).strip()
            offset_pos = max(0, len(nuevos_bloques) - 1)
            recs_frag_offset = {
                k: r.model_copy(update={"posicion": offset_pos}) for k, r in recs_nuevos_frag.items()
            }
            _, recs_combinados = fusionar_bloques_y_recursos_sin_colision(
                nuevos_bloques, recursos_prev, recs_frag_offset, ultimo_id=ultimo_id_prev
            )
        elif sesion.texto_en_edicion:
            nuevo_borrador_txt = f"{sesion.texto_en_edicion}\n\n{fragmento_limpio}".strip()
            nuevos_bloques = [nuevo_borrador_txt] if nuevo_borrador_txt else []
            _, recs_combinados = fusionar_bloques_y_recursos_sin_colision(
                nuevos_bloques, recursos_prev, recs_nuevos_frag, ultimo_id=ultimo_id_prev
            )
        else:
            nuevo_borrador_txt = fragmento_limpio
            nuevos_bloques = [b.strip() for b in bloques_frag if b.strip()]
            nuevos_bloques = [sanitizar_borrador(texto=b)["texto_sanitizado"].strip() for b in nuevos_bloques]
            nuevos_bloques = [b for b in nuevos_bloques if b]
            _, recs_combinados = fusionar_bloques_y_recursos_sin_colision(
                nuevos_bloques, recursos_prev, recs_nuevos_frag, ultimo_id=ultimo_id_prev
            )

        largo_efectivo = len(texto_efectivo_sin_marcadores(nuevo_borrador_txt))
        if largo_efectivo > TEXTO_MAX_PERCENTIL_99:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
            return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX_PERCENTIL_99, intento), ops_texto)

        max_id_frag = max(ultimo_id_prev, _max_num_recurso(recs_combinados))
        sesion.actualizar_contenido_borrador(
            bloques_texto=nuevos_bloques,
            texto_en_edicion=nuevo_borrador_txt,
            texto_editor=fragmento_limpio if req.texto is not None else None,
            recursos=recs_combinados,
            ultimo_id_recurso=max_id_frag,
            categoria_id=req.categoria_id,
            tags=req.tags,
        )

        msg_edicion = MSG_TEXTO_EN_EDICION
        return construir_respuesta(sesion, msg_edicion, ops_texto, aviso_privacidad=aviso_priv_frag)

    if req.texto is not None:
        texto_raw = req.texto.strip()
    elif req.mensaje is not None and req.mensaje.strip().lower() not in (
        "confirmar_texto", "confirmar texto", "confirmar",
    ):
        texto_raw = req.mensaje.strip()
        if sesion.texto_en_edicion and req.mensaje.strip() != sesion.texto_en_edicion.strip():
            texto_raw = f"{sesion.texto_en_edicion}\n\n{req.mensaje.strip()}".strip()
    else:
        texto_raw = (sesion.texto_limpio or sesion.texto_en_edicion or "").strip()

    if not texto_raw:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO")
        return construir_respuesta(sesion, msg_texto_vacio(intento), ops_texto)

    sesion.limpiar_fallos("ESPERANDO_TEXTO")
    sesion.texto_en_edicion = ""
    if sesion.borrador is not None:
        sesion.borrador.texto_en_edicion = ""
    actualizar_metadatos_sesion(sesion, req)

    if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
        ultimo_id_enriq = max(
            sesion.ultimo_id_recurso,
            sesion.borrador.ultimo_id_recurso,
            _max_num_recurso(sesion.borrador.recursos),
        )
        bloques_base_enriq = list(sesion.borrador.bloques_texto or [])
        texto_base_limpio = sesion.borrador.texto_base_limpio or "\n\n".join(bloques_base_enriq)
        # Regla 6: Adiciones breves (<= 70 chars) que no contienen la base se agregan al final
        if bloques_base_enriq and len(texto_raw) <= 70 and texto_base_limpio not in texto_raw:
            bloques_enriq, recursos_finales, aviso_priv, _ = _consolidar_bloques_y_recursos_enriquecimiento(
                bloques_base_enriq,
                sesion.borrador.recursos,
                texto_raw,
                ultimo_id=ultimo_id_enriq,
                validar_marcadores_existentes=True,
                forzar_preservar_base=True,
            )
            aviso_priv = aviso_priv or getattr(req, "aviso_privacidad_detectado", None)
        else:
            # Edición manual del editor: tiene prioridad sobre la concatenación cruda y respeta borrados
            bloques_raw, recs_nuevos = extraer_recursos_y_bloques_texto(
                texto_raw,
                recursos_previos=sesion.borrador.recursos,
                ultimo_id=ultimo_id_enriq,
            )
            parrafos_base = (
                {p.strip() for p in re.split(r"\n\s*\n", texto_base_limpio) if p.strip()}
                if texto_base_limpio
                else set()
            )
            bloques_san = []
            avisos_priv = []
            for b in bloques_raw:
                b_strip = b.strip()
                if not b_strip:
                    continue
                if texto_base_limpio and (b_strip == texto_base_limpio or b_strip in parrafos_base):
                    bloques_san.append(b_strip)
                elif texto_base_limpio and texto_base_limpio in b_strip:
                    txt_cons, av = consolidar_texto_enriquecimiento(texto_base_limpio, b_strip)
                    bloques_san.append(txt_cons)
                    if av:
                        avisos_priv.append(av)
                else:
                    s_b = sanitizar_borrador(texto=b_strip)
                    bloques_san.append(s_b["texto_sanitizado"].strip())
                    if s_b.get("aviso_privacidad"):
                        avisos_priv.append(s_b["aviso_privacidad"])
            aviso_priv = (avisos_priv[0] if avisos_priv else None) or getattr(req, "aviso_privacidad_detectado", None)
            bloques_enriq, recursos_finales = fusionar_bloques_y_recursos_sin_colision(
                bloques_san,
                sesion.borrador.recursos,
                recs_nuevos,
                ultimo_id=ultimo_id_enriq,
            )
        texto_limpio = "\n\n".join(bloques_enriq).strip()
        largo_efectivo = len(texto_efectivo_sin_marcadores(texto_limpio))

        sesion.texto_limpio = texto_limpio
        sesion.texto_en_edicion = texto_limpio

        if largo_efectivo < TEXTO_MIN:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MIN")
            return construir_respuesta(
                sesion,
                msg_error_longitud_minima("texto", TEXTO_MIN, intento),
                [],
                aviso_privacidad=aviso_priv,
            )

        if largo_efectivo > TEXTO_MAX_PERCENTIL_99:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
            return construir_respuesta(
                sesion,
                msg_error_longitud_maxima("texto", TEXTO_MAX_PERCENTIL_99, intento),
                [],
                aviso_privacidad=aviso_priv,
            )

        max_id_enriq = max(
            ultimo_id_enriq,
            _max_num_recurso(recursos_finales),  # type: ignore[arg-type]
            _max_num_recurso(sesion.borrador.recursos),
        )
        sesion.actualizar_contenido_borrador(
            bloques_texto=bloques_enriq,
            texto_base_limpio=texto_limpio,
            recursos=recursos_finales,  # type: ignore[arg-type]
            ultimo_id_recurso=max_id_enriq,
            categoria_id=req.categoria_id,
            tags=req.tags,
            texto_editor=sanitizar_borrador(texto=req.texto)["texto_sanitizado"].strip() if req.texto is not None else None,
        )
        pref_enriq = prefijo_borrador_creado(sesion.borrador.articulo_original_id)
        return continuar(
            sesion, prefijo=pref_enriq, aviso_privacidad=aviso_priv
        )

    bloques_proc, recursos_finales, err_marcadores = procesar_recursos_y_bloques(
        texto_raw,
        recursos_previos=sesion.recursos,
        ultimo_id=sesion.ultimo_id_recurso,
        mensaje_error_custom="El texto contiene marcadores no válidos ({marcadores}). Los recursos multimedia deben adjuntarse mediante enlaces o subida de archivos, no escribiendo marcadores manualmente.",
    )
    if err_marcadores:
        sesion.registrar_fallo("MARCADORES_MANUALES")
        return construir_respuesta(sesion, err_marcadores, ["volver"])

    texto_limpio = "\n\n".join(bloques_proc).strip()
    sanit_txt = sanitizar_borrador(texto=texto_limpio, titulo=sesion.titulo, sanitizar_redundancia_titulo=False)
    texto_limpio = sanit_txt["texto_sanitizado"]
    if sanit_txt.get("titulo_sanitizado"):
        sesion.titulo = sanit_txt["titulo_sanitizado"]
    aviso_privacidad = sanit_txt.get("aviso_privacidad") or getattr(req, "aviso_privacidad_detectado", None)
    bloques_san = [
        sanitizar_borrador(texto=b)["texto_sanitizado"].strip()
        for b in bloques_proc
        if b.strip()
    ]
    bloques_san = [b for b in bloques_san if b]

    largo_efectivo = len(texto_efectivo_sin_marcadores(texto_limpio))
    if largo_efectivo < TEXTO_MIN:
        sesion.texto_limpio = texto_limpio
        sesion.texto_en_edicion = texto_limpio
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MIN")
        return construir_respuesta(
            sesion,
            msg_error_longitud_minima("texto", TEXTO_MIN, intento),
            [],
            aviso_privacidad=aviso_privacidad,
        )

    if largo_efectivo > TEXTO_MAX_PERCENTIL_99:
        sesion.texto_limpio = texto_limpio
        sesion.texto_en_edicion = texto_limpio
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
        return construir_respuesta(
            sesion,
            msg_error_longitud_maxima("texto", TEXTO_MAX_PERCENTIL_99, intento),
            [],
            aviso_privacidad=aviso_privacidad,
        )

    sesion.texto_limpio = texto_limpio
    sesion.texto_en_edicion = ""
    max_id_nuevo = max(sesion.ultimo_id_recurso, _max_num_recurso(recursos_finales))
    sesion.actualizar_contenido_borrador(
        bloques_texto=bloques_san,
        recursos=recursos_finales,
        ultimo_id_recurso=max_id_nuevo,
        texto_editor=sanitizar_borrador(texto=req.texto)["texto_sanitizado"].strip() if req.texto is not None else None,
    )
    texto_busqueda = texto_efectivo_sin_marcadores(sesion.texto_limpio)
    clave_txt = clave_busqueda("texto", texto_busqueda)
    omitir_txt = clave_txt in sesion.busquedas_descartadas
    if omitir_txt:
        res_txt = None
    else:
        res_txt = await run_in_threadpool(
            buscador.evaluar_texto, texto_busqueda, True, sesion.titulo, 1, sesion.descarto_serie
        )
    if res_txt and res_txt.get("coincidencias"):
        coincs = normalizar_coincidencias(
            res_txt["coincidencias"], mensaje=res_txt.get("mensaje", ""), tipo_coincidencia="semantico"
        )
        coincs = [c for c in coincs if c.id not in sesion.articulos_descartados_ids and not (sesion.descarto_serie and c.tipo_coincidencia == "serie")]
        if coincs:
            sesion.coincidencias = coincs
            sesion.estado = EstadoFlujo.DECISION_TEXTO
            primero = sesion.coincidencias[0]
            return construir_respuesta(
                sesion,
                msg_coincidencia(res_txt["mensaje"], primero.titulo, primero.url),
                OPCIONES_ENRIQUECER_CONTINUAR,
                aviso_privacidad=aviso_privacidad,
            )

    sesion.contenido_adicional = []
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=sesion.titulo,
        bloques_texto=sesion.bloques_texto,
        recursos=sesion.recursos,
        ultimo_id_recurso=max_id_nuevo,
        contenido_adicional=[],
        tipo_plantilla=(sesion.borrador.tipo_plantilla if sesion.borrador else None) or extraer_tipo_plantilla(sesion.tags),
        categoria_id=sesion.categoria_id,
        tags=list(sesion.tags),
    )
    sesion.texto = sesion.borrador.texto_alineado_discourse
    pref_descarte = "Omití las coincidencias que ya descartaste. " if omitir_txt else ""
    pref_final = f"{pref_descarte}{PREFIJO_SIN_DUPLICADOS}"
    return continuar(
        sesion, prefijo=pref_final, aviso_privacidad=aviso_privacidad
    )


async def handle_decision_texto(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    actualizar_metadatos_sesion(sesion, req)

    if opcion in ("enriquecer", "actualizar"):
        sesion.limpiar_fallos("DECISION_TEXTO")
        if not sesion.coincidencias:
            return construir_respuesta(
                sesion,
                "No se encontró el artículo coincidente para enriquecer. Tocá **Continuar con mi texto** para usar tu propio texto:",
                ["continuar", "reiniciar"],
            )
        elegido = sesion.coincidencias[0]
        if (
            sesion.borrador is not None
            and sesion.borrador.modo == 'enriquecimiento'
            and sesion.borrador.articulo_original_id == elegido.id
        ):
            if req.texto is not None and req.texto.strip():
                texto_enviado = sanitizar_borrador(texto=req.texto.strip())["texto_sanitizado"].strip()
                sesion.borrador.texto_editor = texto_enviado
                sesion.texto_editor = texto_enviado
                sesion.texto_en_edicion = texto_enviado
            if req.tags is not None:
                sesion.borrador.tags = list(req.tags)
                sesion.tags = list(req.tags)
            if req.categoria_id is not None:
                sesion.borrador.categoria_id = req.categoria_id
                sesion.categoria_id = req.categoria_id
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            es_serie = elegido.tipo_coincidencia == 'serie' or opcion == 'actualizar'
            msg_carga = (
                msg_actualizar_serie_cargado(elegido.id, elegido.titulo)
                if es_serie
                else msg_enriquecer_cargado(elegido.id, elegido.titulo)
            )
            return construir_respuesta(
                sesion,
                msg_carga,
                ['confirmar_texto', 'descartar', 'volver'],
            )
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        bloques_base, recs_base = extraer_recursos_y_bloques_texto(texto_base)
        texto_base_limpio = "\n\n".join(bloques_base).strip()
        if validar_longitud_maxima(texto_base_limpio, TEXTO_MAX_PERCENTIL_99, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX_PERCENTIL_99), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_aporte = (req.texto or "").strip() or (sesion.texto_editor or "").strip() or (sesion.texto or "").strip() or (sesion.texto_limpio or "").strip()
        # Enriquecer/actualizar por texto:
        # El Editor contiene ÚNICAMENTE el texto escrito por la persona (texto_aporte)
        # La Vista previa arranca ÚNICAMENTE con los bloques del artículo original existente (sin fusionar automáticamente el nuevo texto)
        bloques_finales = list(bloques_base)
        texto_limpio = texto_base_limpio
        aviso_priv = None

        bloques_frag, recs_nuevos_frag = extraer_recursos_y_bloques_texto(
            texto_aporte,
            recursos_previos=recs_base,
            ultimo_id=max(sesion.ultimo_id_recurso, _max_num_recurso(recs_base)),
        )
        _, recursos_finales = fusionar_bloques_y_recursos_sin_colision(
            bloques_base, recs_base, recs_nuevos_frag, ultimo_id=max(sesion.ultimo_id_recurso, _max_num_recurso(recs_base))
        )

        if validar_longitud_maxima(texto_limpio, TEXTO_MAX_PERCENTIL_99, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX_PERCENTIL_99), ["descartar", "reiniciar"])

        es_serie = elegido.tipo_coincidencia == "serie" or opcion == "actualizar"
        titulo_borrador = (sesion.titulo or req.titulo or elegido.titulo).strip() if es_serie else elegido.titulo

        nom_cat = DICCIONARIO_OFICIAL_CATEGORIAS.get(cat_db, f"Categoría {cat_db}") if cat_db else "Sin categoría"
        meta_ant = {
            "categoria_id": cat_db,
            "categoria_nombre": nom_cat,
            "tags": list(tags_db or []),
        } if (cat_db or tags_db) else None

        max_id = max(
            sesion.ultimo_id_recurso,
            _max_num_recurso(recursos_finales),  # type: ignore[arg-type]
            _max_num_recurso(recs_base),
        )
        sesion.borrador = BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=elegido.id,
            articulo_original_url=elegido.url,
            titulo=titulo_borrador,
            bloques_texto=bloques_finales,
            texto_base_limpio=texto_base_limpio,
            texto_editor=texto_aporte,
            recursos=recursos_finales,  # type: ignore[arg-type]
            ultimo_id_recurso=max_id,
            contenido_adicional=list(sesion.contenido_adicional),
            tipo_plantilla=extraer_tipo_plantilla(tags_ini),
            categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
            tags=tags_ini,
            metadatos_anteriores=meta_ant,
            metadatos_heredados_revisados=False,
        )
        sesion.texto_editor = texto_aporte
        sesion.texto_en_edicion = texto_aporte
        sesion.metadatos_anteriores = meta_ant
        sesion.metadatos_heredados_revisados = False
        sesion.actualizar_contenido_borrador(
            bloques_texto=list(sesion.borrador.bloques_texto),
            texto_base_limpio=texto_base_limpio,
            texto_editor=texto_aporte,
            recursos=dict(sesion.borrador.recursos),
            ultimo_id_recurso=max_id,
        )
        texto_limpio = sesion.borrador.texto_limpio

        err = validar_longitud(texto_limpio, TEXTO_MIN, TEXTO_MAX_PERCENTIL_99, "texto")
        if err:
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            return construir_respuesta(sesion, err, ["confirmar_texto", "descartar", "volver"])

        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        sesion.texto_en_edicion = texto_aporte
        msg_carga = (
            msg_actualizar_serie_cargado(elegido.id, elegido.titulo)
            if es_serie
            else msg_enriquecer_cargado(elegido.id, elegido.titulo)
        )
        return construir_respuesta(
            sesion,
            msg_carga,
            ["confirmar_texto", "descartar", "volver"],
            aviso_privacidad=aviso_priv,
        )

    if opcion in ("continuar", "descartar"):
        sesion.limpiar_fallos("DECISION_TEXTO")
        texto_buscado = texto_efectivo_sin_marcadores(sesion.texto_limpio or sesion.texto or "")
        if texto_buscado:
            sesion.busquedas_descartadas.add(clave_busqueda("texto", texto_buscado))
        for c in sesion.coincidencias:
            if c.id and c.id not in sesion.articulos_descartados_ids:
                sesion.articulos_descartados_ids.append(c.id)
        sesion.coincidencias = []
        bloques_propios = list(sesion.bloques_texto) if sesion.bloques_texto else (
            [sesion.texto_limpio.strip()] if (sesion.texto_limpio or "").strip() else []
        )
        max_id = max(sesion.ultimo_id_recurso, _max_num_recurso(sesion.recursos))
        sesion.contenido_adicional = []
        sesion.borrador = BorradorSesion(
            modo="nuevo",
            titulo=sesion.titulo,
            bloques_texto=bloques_propios,
            recursos=sesion.recursos,
            ultimo_id_recurso=max_id,
            contenido_adicional=[],
            tipo_plantilla=(sesion.borrador.tipo_plantilla if sesion.borrador else None) or extraer_tipo_plantilla(sesion.tags),
            categoria_id=sesion.categoria_id,
            tags=list(sesion.tags),
        )
        sesion.texto = sesion.borrador.texto_alineado_discourse
        return continuar(sesion, prefijo=PREFIJO_CONTINUAR_PROPIO)

    if opcion == "volver":
        return retroceder(sesion)

    intento = sesion.registrar_fallo("DECISION_TEXTO")
    return construir_respuesta(sesion, msg_opcion_invalida(intento), OPCIONES_ENRIQUECER_CONTINUAR)


async def handle_esperando_plantilla(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if opcion == "volver":
        return retroceder(sesion)

    cat_guardada = b.categoria_id if b else sesion.categoria_id
    if categoria_difiere(req.categoria_id, cat_guardada):
        res_cat = resolver_categoria(req.categoria_id, sesion.categorias_disponibles)
        if res_cat.categoria_id is not None:
            b.categoria_id = res_cat.categoria_id
            b.categoria_nombre = res_cat.categoria_nombre
            sesion.categoria_id = res_cat.categoria_id
            sesion.categoria_nombre = res_cat.categoria_nombre
        else:
            b.categoria_id = req.categoria_id

    tit_guardado = (b.titulo if b else sesion.titulo) or ""
    tiene_skill_vis = tiene_resultado_skill_visible(b)
    txt_guardado = (
        b.texto_editor
        if (b and b.texto_editor and tiene_skill_vis)
        else (b.texto_limpio if b else (sesion.texto_limpio or sesion.texto))
    ) or ""
    edita_txt_req = texto_difiere(req.texto, txt_guardado, titulo_contexto=tit_guardado)

    if b and req.texto is not None and req.texto.strip() and edita_txt_req:
        ultimo_id_p = max(sesion.ultimo_id_recurso, b.ultimo_id_recurso, _max_num_recurso(b.recursos))
        bloques_plant, recs_plant, _ = procesar_recursos_y_bloques(
            req.texto.strip(),
            recursos_previos=b.recursos,
            ultimo_id=ultimo_id_p,
            validar_marcadores_existentes=False,
        )
        tl_plant = "\n\n".join(bloques_plant).strip()
        sesion.actualizar_contenido_borrador(
            bloques_texto=bloques_plant,
            texto_base_limpio=tl_plant if b.modo == "enriquecimiento" else None,
            recursos=recs_plant,
            ultimo_id_recurso=max(ultimo_id_p, _max_num_recurso(recs_plant)),
        )

    texto_para_plantilla = req.texto if edita_txt_req else None
    opcion_plantilla = opcion or req.tipo_plantilla or req.mensaje or texto_para_plantilla or ""
    plantilla = extraer_tipo_plantilla(req.tags or [], opcion_plantilla)
    if not plantilla and b and b.tipo_plantilla and opcion in ("continuar", "continuar_revision"):
        plantilla = b.tipo_plantilla
    if not plantilla:
        return construir_respuesta(sesion, MSG_ELEGIR_PLANTILLA, OPCIONES_PLANTILLAS)

    b.tipo_plantilla = plantilla
    tags_previos = [
        t
        for t in b.tags
        if extraer_tipo_plantilla([t]) is None or extraer_tipo_plantilla([t]) == plantilla
    ]
    tags_req_sanit, aviso_priv_tags = _sanitizar_tags_tematicos(req.tags or [], plantilla=plantilla)
    b.tags = combinar_tags(plantilla, tags_previos, tags_req_sanit)
    sesion.tags = list(b.tags)
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id
    return continuar(sesion)


async def handle_esperando_metadatos(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if opcion in ("aceptar", "aceptar_metadatos", "rechazar_metadatos"):
        resp_meta = continuar(sesion, opcion=opcion)
        if resp_meta is not None:
            return resp_meta
    if opcion == "volver":
        return retroceder(sesion)

    plantilla_guardada = (
        (b.tipo_plantilla if b else sesion.tipo_plantilla)
        or extraer_tipo_plantilla((b.tags if b else sesion.tags) or [])
    )
    if req.tipo_plantilla is not None:
        try:
            if plantilla_difiere(req.tipo_plantilla, plantilla_guardada):
                nueva_plantilla = req.tipo_plantilla.strip().lower()
                b.tipo_plantilla = nueva_plantilla
                sesion.tipo_plantilla = nueva_plantilla
                tematicos_prev = [
                    t for t in b.tags
                    if t and t.strip() and extraer_tipo_plantilla([t]) is None
                ]
                b.tags = combinar_tags(nueva_plantilla, tematicos_prev)
                sesion.tags = list(b.tags)
        except ValueError as e:
            return construir_respuesta(sesion, str(e), ["volver"])

    cat_guardada = b.categoria_id if b else sesion.categoria_id
    edita_cat = categoria_difiere(req.categoria_id, cat_guardada)
    cat_invalida = False
    if edita_cat and req.categoria_id is not None:
        res_dir = resolver_categoria(req.categoria_id, sesion.categorias_disponibles)
        if res_dir.categoria_id is not None:
            b.categoria_id = res_dir.categoria_id
            b.categoria_nombre = res_dir.categoria_nombre
            sesion.categoria_id = res_dir.categoria_id
            sesion.categoria_nombre = res_dir.categoria_nombre
        else:
            cat_invalida = True

    tit_guardado = (b.titulo if b else sesion.titulo) or ""
    tiene_skill_vis = tiene_resultado_skill_visible(b)
    txt_guardado = (
        b.texto_editor
        if (b and b.texto_editor and tiene_skill_vis)
        else (b.texto_limpio if b else (sesion.texto_limpio or sesion.texto))
    ) or ""
    edita_txt_req = texto_difiere(req.texto, txt_guardado, titulo_contexto=tit_guardado)
    texto_fallback_efectivo = req.texto if edita_txt_req else None

    tags_guardados = list(b.tags) if b else list(sesion.tags)
    edita_tags_req = tags_difiere(req.tags, tags_guardados, plantilla=b.tipo_plantilla)

    # Turno 2 (Categoría): Si ya tenemos al menos 2 tags (o al menos 1 temático además de plantilla) y falta la categoría,
    # y el usuario envía un texto por chat (sin cambiar categoria_id ni tags por estructurado),
    # el texto se evalúa exclusivamente contra el vocabulario de categorías.
    tags_tematicos = [t for t in b.tags if t != b.tipo_plantilla]
    if (
        (len(tags_tematicos) >= 1 or len(b.tags) >= 2)
        and b.categoria_id is None
        and not edita_cat
        and not edita_tags_req
    ):
        texto_chat = (req.mensaje or texto_fallback_efectivo or req.accion or "").strip()
        if texto_chat and texto_chat != "volver":
            res_chat = resolver_categoria(texto_chat, sesion.categorias_disponibles)
            if res_chat.estado == "asignado":
                b.categoria_id = res_chat.categoria_id
                b.categoria_nombre = res_chat.categoria_nombre
                sesion.categoria_id = res_chat.categoria_id
                sesion.categoria_nombre = res_chat.categoria_nombre
                return continuar(sesion, prefijo=PREFIJO_METADATOS_REGISTRADOS)
            elif res_chat.estado == "ambiguo":
                intento = sesion.registrar_fallo("ESPERANDO_METADATOS")
                cands = [c.nombre for c in res_chat.candidatos]
                msg = msg_categoria_ambigua(texto_chat, cands)
                return construir_respuesta(sesion, msg, cands + ["volver"])
            elif res_chat.estado == "no_encontrado":
                intento = sesion.registrar_fallo("ESPERANDO_METADATOS")
                sugs = [c.nombre for c in res_chat.candidatos]
                msg = msg_categoria_no_encontrada(texto_chat, sugs)
                return construir_respuesta(sesion, msg, ["volver"])
            else:
                intento = sesion.registrar_fallo("ESPERANDO_METADATOS")
                msg = msg_pedir_categoria(intento)
                return construir_respuesta(sesion, msg, ["volver"])
        elif not texto_chat:
            intento = sesion.registrar_fallo("ESPERANDO_METADATOS")
            msg = msg_pedir_categoria(intento)
            return construir_respuesta(sesion, msg, ["volver"])

    texto_fuente = req.mensaje or texto_fallback_efectivo or req.accion
    tags_req_para_parsear = req.tags if edita_tags_req else None
    aviso_priv_tags = None
    if tags_req_para_parsear is not None:
        tags_req_para_parsear, aviso_priv_tags = _sanitizar_tags_tematicos(
            tags_req_para_parsear,
            plantilla=b.tipo_plantilla,
        )

    cat_req_para_parsear = (
        req.categoria_id
        if (edita_cat and not cat_invalida)
        else None
    )
    nuevos_tags, cat_res, cat_nom = parsear_metadatos_mensaje(
        req.mensaje,
        tags_req_para_parsear,
        cat_req_para_parsear,
        texto_fallback=texto_fuente,
        categorias_disponibles=sesion.categorias_disponibles,
        tags_disponibles=sesion.tags_disponibles,
    )
    if req.mensaje and nuevos_tags:
        nuevos_tags, aviso_msg_tags = _sanitizar_tags_tematicos(nuevos_tags, plantilla=b.tipo_plantilla)
        if aviso_msg_tags and not aviso_priv_tags:
            aviso_priv_tags = aviso_msg_tags

    if cat_res is not None and not cat_invalida:
        b.categoria_id = cat_res
        b.categoria_nombre = cat_nom

    if b.categoria_id is None and sesion.categoria_id is not None and not cat_invalida:
        b.categoria_id = sesion.categoria_id
        b.categoria_nombre = sesion.categoria_nombre

    if edita_tags_req and req.tags is not None:
        b.tags = combinar_tags(b.tipo_plantilla, nuevos_tags)
    elif nuevos_tags:
        b.tags = combinar_tags(b.tipo_plantilla, b.tags, nuevos_tags)
    else:
        b.tags = combinar_tags(b.tipo_plantilla, b.tags)
    sesion.tags = list(b.tags)
    if b.categoria_id is not None and not cat_invalida:
        sesion.categoria_id = b.categoria_id
        if not b.categoria_nombre:
            res_sync = resolver_categoria(b.categoria_id, sesion.categorias_disponibles)
            b.categoria_nombre = res_sync.categoria_nombre
        sesion.categoria_nombre = b.categoria_nombre

    tags_faltan = len(b.tags) < 2
    cat_falta = b.categoria_id is None or cat_invalida

    if tags_faltan or cat_falta:
        intento = sesion.registrar_fallo("ESPERANDO_METADATOS")
        if tags_faltan and cat_falta:
            msg = msg_pedir_tags_y_categoria(b.tipo_plantilla or "", intento)
        elif cat_falta:
            msg = msg_pedir_categoria(intento)
        else:
            msg = msg_pedir_tag_adicional(b.tipo_plantilla or "", intento)
        return construir_respuesta(sesion, msg, ["volver"], aviso_privacidad=aviso_priv_tags)

    return continuar(sesion, prefijo=PREFIJO_METADATOS_REGISTRADOS)


def _resolver_flujo_rechazo(
    sesion: SesionChat, opcion: str, hubo_cambios: bool = False
) -> Optional[ChatOrquestadorResponse]:
    """Encapsula la guarda y el cambio a EstadoFlujo.RECHAZADO cuando sesion.confirmando_rechazo está activo."""
    if not getattr(sesion, "confirmando_rechazo", False):
        return None

    if opcion in ("confirmar_rechazo", "rechazar"):
        sesion.confirmando_rechazo = False
        sesion.estado = EstadoFlujo.RECHAZADO
        sesion.borrador = None
        sesion.contenido_adicional = []
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    if opcion == "volver":
        sesion.confirmando_rechazo = False
        msg, ops = validar_borrador(sesion)
        return construir_respuesta(
            sesion,
            f"{MSG_OPERACION_CANCELADA}{msg}",
            ops,
        )

    if opcion in ("editar", "sanitizar") or hubo_cambios:
        sesion.confirmando_rechazo = False
        return None

    return construir_respuesta(
        sesion,
        "Por favor confirmá si querés descartar el artículo tocando **Sí, descartar** o **Volver** para continuar trabajando en él.",
        ["confirmar_rechazo", "volver"],
    )


def _ejecutar_sanitizacion_borrador(
    sesion: SesionChat, req: ChatOrquestadorRequest
) -> ChatOrquestadorResponse:
    """Ejecuta la sanitización sobre el borrador actual (explícita o silenciosa)."""
    b = sesion.borrador
    if b is None:
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    txt_a_sanit = req.texto or b.texto_limpio or b.texto_alineado_discourse
    ultimo_id_sanit = max(sesion.ultimo_id_recurso, b.ultimo_id_recurso, _max_num_recurso(b.recursos))
    bloques_sanit_in, recs_sanit_comb, _ = procesar_recursos_y_bloques(
        txt_a_sanit,
        recursos_previos=b.recursos,
        ultimo_id=ultimo_id_sanit,
        validar_marcadores_existentes=False,
    )
    tl_sanit_in = "\n\n".join(bloques_sanit_in).strip()

    limpio = sanitizar_borrador(texto=tl_sanit_in, titulo=req.titulo or b.titulo)
    titulo_sanitizado = limpio["titulo_sanitizado"]
    txt_sanitizado = limpio["texto_sanitizado"]
    aviso_sanit = limpio.get("aviso_privacidad")
    bloques_sanitizados = [
        sanitizar_borrador(texto=bl)["texto_sanitizado"].strip()
        for bl in bloques_sanit_in
        if bl.strip()
    ]
    bloques_sanitizados = [bl for bl in bloques_sanitizados if bl]

    max_id = max(ultimo_id_sanit, _max_num_recurso(recs_sanit_comb))
    sesion.actualizar_contenido_borrador(
        titulo=titulo_sanitizado,
        bloques_texto=bloques_sanitizados,
        texto_base_limpio=txt_sanitizado if b.modo == "enriquecimiento" else None,
        recursos=recs_sanit_comb,
        ultimo_id_recurso=max_id,
    )
    sesion.estado = EstadoFlujo.REVISION_BORRADOR

    prefijo = PREFIJO_DATOS_SANITIZADOS

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_sanit)


def _aplicar_mutaciones_borrador(
    sesion: SesionChat,
    req: ChatOrquestadorRequest,
    texto_edicion: Optional[str] = None,
) -> ChatOrquestadorResponse:
    """Aísla el parseo y actualización de título, texto, tags y categoría cuando hubo_cambios es True."""
    b = sesion.borrador
    if b is None:
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    ops_actuales = (
        OPCIONES_REVISION_VALIDO
        if (sesion.validacion and sesion.validacion.valido)
        else OPCIONES_REVISION_BLOQUEANTE
    )
    aviso_priv_edicion = None
    titulo_nuevo = None

    if req.titulo is not None and titulo_difiere(req.titulo, b.titulo):
        tit_nuevo = req.titulo.strip()
        err_tit = validar_longitud_maxima(tit_nuevo, TITULO_MAX, "título")
        if err_tit:
            return construir_respuesta(sesion, err_tit, ops_actuales)
        sanit_tit = sanitizar_borrador(texto="", titulo=tit_nuevo)
        titulo_nuevo = sanit_tit["titulo_sanitizado"]
        if sanit_tit.get("aviso_privacidad"):
            aviso_priv_edicion = sanit_tit.get("aviso_privacidad")

    recursos_nuevos = None
    bloques_nuevos = None
    txt_nuevo_limpio = None
    ultimo_id_nuevo = None

    if texto_edicion is not None and texto_difiere(texto_edicion, b.texto_limpio, titulo_contexto=titulo_nuevo or b.titulo):
        txt_nuevo = texto_edicion.strip()
        ultimo_id_edit = max(sesion.ultimo_id_recurso, b.ultimo_id_recurso, _max_num_recurso(b.recursos))
        bloques_proc, recs_comb, err_marcadores = procesar_recursos_y_bloques(
            txt_nuevo,
            recursos_previos=b.recursos,
            ultimo_id=ultimo_id_edit,
        )
        if err_marcadores:
            return construir_respuesta(sesion, err_marcadores, ops_actuales)

        txt_proc = "\n\n".join(bloques_proc).strip()
        sanit_edit = sanitizar_borrador(texto=txt_proc, titulo=titulo_nuevo or b.titulo)
        txt_verif = sanit_edit["texto_sanitizado"]
        aviso_txt = sanit_edit.get("aviso_privacidad")
        bloques_nuevos = [
            sanitizar_borrador(texto=bl)["texto_sanitizado"].strip()
            for bl in bloques_proc
            if bl.strip()
        ]
        bloques_nuevos = [bl for bl in bloques_nuevos if bl]

        det_req = getattr(req, "aviso_privacidad_detectado", None)
        aviso_efectivo = aviso_txt or det_req
        if aviso_efectivo:
            aviso_priv_edicion = f"{aviso_priv_edicion}\n{aviso_efectivo}" if aviso_priv_edicion else aviso_efectivo

        err_txt = validar_longitud_maxima(txt_verif, TEXTO_MAX_PERCENTIL_99, "texto")
        if err_txt:
            return construir_respuesta(sesion, err_txt, ops_actuales)

        txt_nuevo_limpio = txt_verif
        # Los recursos existentes se conservan al editar texto (solo se eliminan explícitamente)
        recursos_nuevos = recs_comb
        ultimo_id_nuevo = max(ultimo_id_edit, _max_num_recurso(recs_comb))

    tags_nuevos = None
    plantilla_nueva = None
    if req.tags is not None:
        plantilla_nueva = b.tipo_plantilla or extraer_tipo_plantilla(req.tags)
        tags_filtrados = [
            t
            for t in req.tags
            if extraer_tipo_plantilla([t]) is None or extraer_tipo_plantilla([t]) == plantilla_nueva
        ]
        tags_nuevos = combinar_tags(plantilla_nueva, tags_filtrados)

    categoria_id_nueva = None
    categoria_nombre_nuevo = None
    if req.categoria_id is not None and req.categoria_id != b.categoria_id:
        res_cat = resolver_categoria(req.categoria_id, sesion.categorias_disponibles)
        if res_cat.categoria_id is not None:
            categoria_id_nueva = res_cat.categoria_id
            categoria_nombre_nuevo = res_cat.categoria_nombre

    sesion.actualizar_contenido_borrador(
        titulo=titulo_nuevo,
        bloques_texto=bloques_nuevos,
        texto_base_limpio=txt_nuevo_limpio if b.modo == "enriquecimiento" else None,
        recursos=recursos_nuevos,
        ultimo_id_recurso=ultimo_id_nuevo,
        categoria_id=categoria_id_nueva,
        categoria_nombre=categoria_nombre_nuevo,
        tags=tags_nuevos,
        tipo_plantilla=plantilla_nueva,
    )

    sesion.estado = EstadoFlujo.REVISION_BORRADOR

    prefijo = PREFIJO_BORRADOR_ACTUALIZADO

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_priv_edicion)


async def handle_revision_borrador(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    texto_edicion = req.texto if req.texto is not None else req.texto_editor
    if texto_edicion is None and opcion == "editar" and req.mensaje and req.mensaje.strip().lower() != "editar":
        texto_edicion = req.mensaje

    hubo_cambios = any(v is not None for v in (req.titulo, texto_edicion, req.categoria_id, req.tags))

    # 1. Flujo de confirmación de rechazo
    resp_rechazo = _resolver_flujo_rechazo(sesion, opcion, hubo_cambios)
    if resp_rechazo is not None:
        return resp_rechazo

    # 2. Gestión de metadatos heredados de versión previa
    if opcion in ("aceptar", "aceptar_metadatos", "rechazar_metadatos") or (
        opcion == "rechazar" and b is not None and b.metadatos_anteriores and not b.metadatos_heredados_revisados
    ):
        resp_meta = continuar(sesion, opcion=opcion)
        if resp_meta is not None:
            return resp_meta

    # 3. Acción explícita o silenciosa de sanitización
    if opcion == "sanitizar":
        return _ejecutar_sanitizacion_borrador(sesion, req)

    if opcion == "volver":
        return retroceder(sesion)

    if hubo_cambios:
        req_edicion = req
        if req.texto is None and texto_edicion is not None:
            req_edicion = req.model_copy(update={"texto": texto_edicion})
        res_edicion = aplicar_edicion_campos(sesion, req_edicion)
        if not res_edicion.ok:
            ops = (
                OPCIONES_REVISION_VALIDO
                if (sesion.validacion and sesion.validacion.valido)
                else OPCIONES_REVISION_BLOQUEANTE
            )
            return construir_respuesta(sesion, res_edicion.error or "", ops)

        if req.categoria_id is not None and b is not None:
            res_cat = resolver_categoria(req.categoria_id, sesion.categorias_disponibles)
            if res_cat.categoria_id is not None:
                b.categoria_id = res_cat.categoria_id
                b.categoria_nombre = res_cat.categoria_nombre
                sesion.categoria_id = res_cat.categoria_id
                sesion.categoria_nombre = res_cat.categoria_nombre

        if req.tags is not None and b is not None:
            plantilla_actual = b.tipo_plantilla or extraer_tipo_plantilla(req.tags)
            tags_filtrados = [
                t
                for t in req.tags
                if extraer_tipo_plantilla([t]) is None or (plantilla_actual and extraer_tipo_plantilla([t]) == plantilla_actual)
            ]
            tags_nuevos = combinar_tags(plantilla_actual, tags_filtrados)
            b.tags = tags_nuevos
            sesion.tags = tags_nuevos

        if opcion in ("continuar_revision", "continuar"):
            return continuar_desde_revision(sesion)



        if opcion not in ("editar", "aplicar_plantilla", "auditar", "rechazar", "confirmar_rechazo"):
            prefijo = PREFIJO_BORRADOR_ACTUALIZADO
            msg, ops = validar_borrador(sesion, prefijo)
            return construir_respuesta(sesion, msg, ops, aviso_privacidad=res_edicion.aviso_privacidad)

    # 5. Opciones estándar del estado de revisión
    if opcion == "editar":
        ops = (
            OPCIONES_REVISION_VALIDO
            if (sesion.validacion and sesion.validacion.valido)
            else OPCIONES_REVISION_BLOQUEANTE
        )
        return construir_respuesta(sesion, MSG_PEDIR_EDICION, ops)

    if opcion == "volver":
        return retroceder(sesion)

    if opcion == "aplicar_plantilla":
        from baco.server.services.orquestador.edicion import ejecutar_skill
        return await ejecutar_skill(sesion, req, "plantilla")

    if opcion == "auditar":
        from baco.server.services.orquestador.edicion import ejecutar_skill
        return await ejecutar_skill(sesion, req, "auditor")

    if opcion in ("continuar_revision", "continuar"):
        return continuar_desde_revision(sesion)



    if opcion == "rechazar":
        sesion.confirmando_rechazo = True
        return construir_respuesta(
            sesion,
            "¿Estás seguro de que querés descartar todo el artículo? Se perderán los cambios realizados en esta sesión.",
            ["confirmar_rechazo", "volver"],
        )

    if opcion == "confirmar_rechazo":
        sesion.confirmando_rechazo = False
        sesion.estado = EstadoFlujo.RECHAZADO
        sesion.borrador = None
        sesion.contenido_adicional = []
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    msg, ops = validar_borrador(sesion)
    return construir_respuesta(sesion, msg, ops)


async def handle_edicion_final(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if b is None:
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    # 1. Volver: regresa a revisión final y se registra en retroceso.py
    if opcion == "volver":
        return retroceder(sesion)

    # 2. Reutilizá edicion.py; validá solo los campos modificados
    res_edicion = getattr(req, "_res_edicion", None)
    if res_edicion is None:
        texto_edicion = req.texto if req.texto is not None else req.texto_editor
        hubo_cambios = any(
            v is not None
            for v in (req.titulo, texto_edicion, req.categoria_id, req.tags, req.tipo_plantilla)
        )
        if hubo_cambios:
            req_edicion = req
            if req.texto is None and texto_edicion is not None:
                req_edicion = req.model_copy(update={"texto": texto_edicion})
            res_edicion = aplicar_edicion_campos(sesion, req_edicion)
            if not res_edicion.ok:
                from baco.server.services.orquestador.mensajes import OPCIONES_EDICION_FINAL
                return construir_respuesta(sesion, res_edicion.error or "", OPCIONES_EDICION_FINAL)

    # 3. Si en EDICION_FINAL cambia el tipo de plantilla y había una skill aplicada,
    # handlers.py (no continuar.py) la reaplica automáticamente desde texto_original.
    cambio_plantilla = bool(res_edicion and res_edicion.tipo_plantilla_nueva is not None)
    habia_skill = bool(
        getattr(b, "skill_aplicada", None)
        or getattr(b, "skill_pendiente", None)
        or getattr(sesion, "skill_aplicada", None)
        or getattr(b, "resultado_skill_pendiente", False)
        or getattr(b, "resultado_skill_desactualizado", False)
    )

    if cambio_plantilla and habia_skill:
        # Si texto_original no existe en la sesión, no lo crees: detenete y reportalo.
        if not hasattr(sesion, "texto_original") or sesion.texto_original is None:
            raise ValueError("texto_original no existe en la sesión")

        skill_nombre = (
            getattr(b, "skill_aplicada", None)
            or getattr(b, "skill_pendiente", None)
            or getattr(sesion, "skill_aplicada", None)
            or "plantilla"
        )
        from baco.server.services.orquestador.edicion import ejecutar_skill
        resp_skill = await ejecutar_skill(sesion, req, skill=skill_nombre, es_reaplicacion=True)
        if opcion == "finalizar":
            return _registrar_finalizado(sesion)
        return resp_skill

    # 4. Solo "Finalizar" de EDICION_FINAL llama a _registrar_finalizado
    if opcion == "finalizar":
        return _registrar_finalizado(sesion)

    # 5. Edición u otra interacción en EDICION_FINAL:
    # Botones: solo "Finalizar" y "Volver". Mensajes en mensajes.py.
    from baco.server.services.orquestador.mensajes import MSG_EDICION_FINAL, OPCIONES_EDICION_FINAL
    aviso_priv = res_edicion.aviso_privacidad if res_edicion else None
    mensaje = (res_edicion.aviso if res_edicion and res_edicion.aviso else MSG_EDICION_FINAL)
    return construir_respuesta(sesion, mensaje, OPCIONES_EDICION_FINAL, aviso_privacidad=aviso_priv)


EstadoHandler = Callable[
    [SesionChat, ChatOrquestadorRequest, str, BuscadorDuplicados],
    Coroutine[None, None, ChatOrquestadorResponse],
]

STATE_HANDLERS: Dict[EstadoFlujo, EstadoHandler] = {
    EstadoFlujo.ESPERANDO_TITULO: handle_esperando_titulo,
    EstadoFlujo.DECISION_TITULO: handle_decision_titulo,
    EstadoFlujo.ESPERANDO_TEXTO: handle_esperando_texto,
    EstadoFlujo.DECISION_TEXTO: handle_decision_texto,
    EstadoFlujo.ESPERANDO_PLANTILLA: handle_esperando_plantilla,
    EstadoFlujo.ESPERANDO_METADATOS: handle_esperando_metadatos,
    EstadoFlujo.REVISION_BORRADOR: handle_revision_borrador,
    EstadoFlujo.SUBSANANDO_BORRADOR: handle_revision_borrador,
    EstadoFlujo.EDICION_FINAL: handle_edicion_final,
}
