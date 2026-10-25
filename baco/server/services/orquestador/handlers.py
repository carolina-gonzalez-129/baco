from datetime import datetime, timezone
from typing import Callable, Coroutine, Dict
from starlette.concurrency import run_in_threadpool

from baco.server.config_limites import (
    TEXTO_MAX,
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
from baco.server.services.validar_articulo import sanitizar_borrador
from baco.server.services.orquestador.mensajes import (
    MSG_CONFORMIDAD_INVALIDADA,
    MSG_CONFORMIDAD_REGISTRADA,
    MSG_DESCARTAR_COINCIDENCIA_TITULO,
    MSG_ELEGIR_PLANTILLA,
    MSG_PEDIR_EDICION,
    MSG_RECHAZADO,
    MSG_SIN_COINCIDENCIAS_TITULO,
    MSG_TEXTO_EN_EDICION,
    OPCIONES_ENRIQUECER_CONTINUAR,
    OPCIONES_ENRIQUECER_DESCARTAR,
    OPCIONES_SERIE_DECISION,
    OPCIONES_PLANTILLAS,
    OPCIONES_REINICIAR,
    OPCIONES_CONFORMIDAD,
    OPCIONES_REVISION_BLOQUEANTE,
    OPCIONES_REVISION_VALIDO,
    PREFIJO_BORRADOR_ACTUALIZADO,
    PREFIJO_CONTINUAR_PROPIO,
    PREFIJO_DATOS_SANITIZADOS,
    PREFIJO_ERROR_CONFORMIDAD,
    PREFIJO_METADATOS_REGISTRADOS,
    PREFIJO_SIN_DUPLICADOS,
    msg_actualizar_serie_cargado,
    msg_articulo_conforme,
    msg_articulo_muy_largo,
    msg_coincidencia,
    msg_enriquecer_cargado,
    msg_error_longitud_maxima,
    msg_error_longitud_minima,
    msg_opcion_invalida,
    msg_pedir_tag_adicional,
    msg_texto_vacio,
    prefijo_borrador_creado,
    prefijo_borrador_enriquecido,
)
from baco.server.services.orquestador.recursos_service import (
    componer_texto_publicable,
    extraer_recursos_y_texto_limpio,
    fusionar_recursos,
)
from baco.server.services.orquestador.sesion import SesionChat
from baco.server.services.orquestador.validaciones import (
    DICCIONARIO_OFICIAL_CATEGORIAS,
    actualizar_metadatos_sesion,
    avanzar_a_metadatos_o_revision,
    cargar_datos_articulo,
    combinar_tags,
    consolidar_texto_enriquecimiento,
    construir_respuesta,
    extraer_tipo_plantilla,
    normalizar_coincidencias,
    parsear_metadatos_mensaje,
    validar_borrador,
    validar_longitud,
    validar_longitud_maxima,
)


async def handle_esperando_titulo(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    titulo = (req.titulo or req.mensaje or "").strip()
    if not titulo:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(sesion, msg_error_longitud_minima("título", TITULO_MIN, intento), [])

    if len(titulo) < TITULO_MIN:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(sesion, msg_error_longitud_minima("título", TITULO_MIN, intento), [])

    if len(titulo) > TITULO_MAX:
        intento = sesion.registrar_fallo("ESPERANDO_TITULO")
        return construir_respuesta(sesion, msg_error_longitud_maxima("título", TITULO_MAX, intento), [])

    sesion.limpiar_fallos("ESPERANDO_TITULO")
    sesion.titulo = titulo
    actualizar_metadatos_sesion(sesion, req)

    res_tit = await run_in_threadpool(buscador.evaluar_titulo, titulo, 1)
    if res_tit and res_tit.get("coincidencias"):
        es_serie = "serie" in (res_tit.get("mensaje") or "").lower()
        coincs = normalizar_coincidencias(
            res_tit["coincidencias"],
            mensaje=res_tit.get("mensaje", ""),
            tipo_coincidencia="serie" if es_serie else "duplicado",
        )
        if coincs:
            sesion.coincidencias = coincs
            sesion.estado = EstadoFlujo.DECISION_TITULO
            primero = sesion.coincidencias[0]
            ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
            return construir_respuesta(
                sesion,
                msg_coincidencia(res_tit["mensaje"], primero.titulo, primero.url),
                ops,
            )

    sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
    return construir_respuesta(sesion, MSG_SIN_COINCIDENCIAS_TITULO, ["confirmar_texto", "volver"])


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
                "[Placeholder] No se encontró la coincidencia previa seleccionada. Por favor, ingresá el título de tu artículo:",
                [],
            )
        elegido = sesion.coincidencias[0]
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        texto_base_limpio, recs_base = extraer_recursos_y_texto_limpio(texto_base)
        if validar_longitud_maxima(texto_base_limpio, TEXTO_MAX, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_enviado = (req.texto or "").strip()
        texto_consolidado, aviso_priv = consolidar_texto_enriquecimiento(texto_base, texto_enviado)
        texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto_consolidado)

        es_serie = elegido.tipo_coincidencia == "serie" or opcion == "actualizar"
        titulo_borrador = (sesion.titulo or req.titulo or elegido.titulo).strip() if es_serie else elegido.titulo

        nom_cat = DICCIONARIO_OFICIAL_CATEGORIAS.get(cat_db, f"Categoría {cat_db}") if cat_db else "Sin categoría"
        meta_ant = {
            "categoria_id": cat_db,
            "categoria_nombre": nom_cat,
            "tags": list(tags_db or []),
        } if (cat_db or tags_db) else None

        texto_completo = texto_base if not texto_enviado else texto_consolidado
        sesion.borrador = BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=elegido.id,
            articulo_original_url=elegido.url,
            titulo=titulo_borrador,
            texto=texto_completo,
            texto_limpio=texto_limpio,
            recursos=recursos,
            contenido_adicional=list(sesion.contenido_adicional),
            tipo_plantilla=extraer_tipo_plantilla(tags_ini),
            categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
            tags=tags_ini,
            metadatos_anteriores=meta_ant,
            metadatos_heredados_revisados=False,
        )
        sesion.metadatos_anteriores = meta_ant
        sesion.metadatos_heredados_revisados = False
        sesion.texto = texto_completo
        sesion.texto_limpio = texto_limpio
        sesion.recursos = recursos

        err = validar_longitud(texto_limpio, TEXTO_MIN, TEXTO_MAX, "texto")
        if err:
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            return construir_respuesta(sesion, err, ["confirmar_texto", "descartar", "volver"])

        prefijo = (
            (msg_actualizar_serie_cargado(elegido.id, elegido.titulo) + "\n\n")
            if es_serie
            else (msg_enriquecer_cargado(elegido.id, elegido.titulo) + "\n\n")
        )

        if not texto_enviado:
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            sesion.texto_en_edicion = texto_base_limpio
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

        return avanzar_a_metadatos_o_revision(
            sesion, prefijo_borrador_creado(elegido.id), aviso_privacidad=aviso_priv
        )

    if opcion in ("descartar", "continuar"):
        sesion.limpiar_fallos("DECISION_TITULO")
        for c in sesion.coincidencias:
            if c.id and c.id not in sesion.articulos_descartados_ids:
                sesion.articulos_descartados_ids.append(c.id)
        sesion.coincidencias = []
        texto_disponible = (req.texto or sesion.texto or "").strip()

        if texto_disponible and len(texto_disponible) >= TEXTO_MIN:
            # Condición sine qua non: habiendo recibido título y texto, al descartar
            # la coincidencia de título la búsqueda por duplicados continúa sobre el texto.
            txt_disp_limpio, recs_disp = extraer_recursos_y_texto_limpio(texto_disponible)
            sesion.texto = txt_disp_limpio
            sesion.texto_limpio = txt_disp_limpio
            sesion.recursos = recs_disp
            sanit_txt = sanitizar_borrador(texto=txt_disp_limpio)
            texto_busqueda = sanit_txt["texto_sanitizado"]
            aviso_privacidad = sanit_txt.get("aviso_privacidad")

            res_txt = await run_in_threadpool(buscador.evaluar_texto, texto_busqueda, True, sesion.titulo, 1)
            if res_txt and res_txt.get("coincidencias"):
                coincs = normalizar_coincidencias(
                    res_txt["coincidencias"], mensaje=res_txt.get("mensaje", ""), tipo_coincidencia="semantico"
                )
                coincs = [c for c in coincs if c.id not in sesion.articulos_descartados_ids]
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

            # Si evaluar_texto no arrojó coincidencias, se crea el borrador nuevo y avanza
            txt_rec = componer_texto_publicable(sesion.texto_limpio, sesion.recursos)
            sesion.contenido_adicional = []
            sesion.borrador = BorradorSesion(
                modo="nuevo",
                titulo=sesion.titulo,
                texto=txt_rec,
                texto_limpio=sesion.texto_limpio,
                recursos=sesion.recursos,
                contenido_adicional=[],
                tipo_plantilla=extraer_tipo_plantilla(sesion.tags),
                categoria_id=req.categoria_id or sesion.categoria_id,
                tags=list(req.tags or sesion.tags),
            )
            sesion.texto = txt_rec
            return avanzar_a_metadatos_o_revision(
                sesion, PREFIJO_SIN_DUPLICADOS, aviso_privacidad=aviso_privacidad
            )

        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(sesion, MSG_DESCARTAR_COINCIDENCIA_TITULO, ["confirmar_texto", "volver"])

    if opcion == "volver":
        sesion.limpiar_fallos("DECISION_TITULO")
        sesion.coincidencias = []
        sesion.estado = EstadoFlujo.ESPERANDO_TITULO
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Ingresá un nuevo título para tu artículo:",
            [],
        )

    intento = sesion.registrar_fallo("DECISION_TITULO")
    elegido = sesion.coincidencias[0] if sesion.coincidencias else None
    es_serie = elegido and elegido.tipo_coincidencia == "serie"
    ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
    return construir_respuesta(sesion, msg_opcion_invalida(intento), ops)


async def handle_esperando_texto(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    if opcion == "volver":
        sesion.limpiar_fallos("ESPERANDO_TEXTO")
        sesion.texto_en_edicion = ""
        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            sesion.estado = EstadoFlujo.DECISION_TITULO
            elegido = sesion.coincidencias[0] if sesion.coincidencias else None
            es_serie = elegido and elegido.tipo_coincidencia == "serie"
            ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
            return construir_respuesta(
                sesion,
                "[Placeholder] Volvemos al paso anterior. ¿Deseás enriquecer el artículo encontrado o descartarlo?",
                ops,
            )
        sesion.estado = EstadoFlujo.ESPERANDO_TITULO
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Ingresá un nuevo título para tu artículo:",
            [],
        )

    if opcion in ("descartar", "continuar"):
        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            if sesion.borrador.articulo_original_id and sesion.borrador.articulo_original_id not in sesion.articulos_descartados_ids:
                sesion.articulos_descartados_ids.append(sesion.borrador.articulo_original_id)
            for c in sesion.coincidencias:
                if c.id and c.id not in sesion.articulos_descartados_ids:
                    sesion.articulos_descartados_ids.append(c.id)
            sesion.borrador = None
            sesion.contenido_adicional = []
            sesion.coincidencias = []
            sesion.texto_en_edicion = ""
            sesion.limpiar_fallos("ESPERANDO_TEXTO")
            texto_directo = (req.texto or "").strip()
            if not texto_directo:
                return construir_respuesta(
                    sesion,
                    "[Placeholder] Descartamos el artículo existente. Ingresá el texto o los pasos para redactar tu propio artículo:",
                    ["confirmar_texto", "volver"],
                )

    ops_texto = (
        ["confirmar_texto", "descartar", "volver"]
        if (sesion.borrador and sesion.borrador.modo == "enriquecimiento")
        else ["confirmar_texto", "volver"]
    )
    es_confirmacion = opcion == "confirmar_texto" or (
        req.accion and req.accion.strip().lower() in ("confirmar_texto", "confirmar texto", "confirmar")
    )

    if not es_confirmacion:
        fragmento = (req.texto if req.texto is not None else (req.mensaje or "")).strip()
        if not fragmento:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO")
            return construir_respuesta(sesion, msg_texto_vacio(intento), ops_texto)

        if req.texto is not None:
            nuevo_borrador_txt = fragmento
        elif sesion.texto_en_edicion:
            nuevo_borrador_txt = f"{sesion.texto_en_edicion}\n\n{fragmento}".strip()
        else:
            nuevo_borrador_txt = fragmento

        if len(nuevo_borrador_txt) > TEXTO_MAX:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
            return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX, intento), ops_texto)

        sesion.texto_en_edicion = nuevo_borrador_txt
        if sesion.borrador is not None:
            sesion.borrador.texto_en_edicion = nuevo_borrador_txt
        if req.categoria_id is not None:
            sesion.categoria_id = req.categoria_id
        if req.tags is not None:
            sesion.tags = req.tags

        msg_edicion = (
            f"Guardé tu texto en edición ({len(nuevo_borrador_txt)} / {TEXTO_MAX} caracteres). "
            "Podés seguir escribiendo o pegando más contenido, y cuando esté listo tocá 'Confirmar texto'."
        )
        return construir_respuesta(sesion, msg_edicion, ops_texto)

    if req.texto is not None:
        texto_raw = req.texto.strip()
        if (
            sesion.texto_en_edicion
            and req.texto.strip() != sesion.texto_en_edicion.strip()
            and (sesion.borrador is None or sesion.borrador.modo != "enriquecimiento")
        ):
            texto_raw = f"{sesion.texto_en_edicion}\n\n{req.texto.strip()}".strip()
    elif req.mensaje is not None and req.mensaje.strip().lower() not in ("confirmar_texto", "confirmar texto", "confirmar"):
        texto_raw = req.mensaje.strip()
        if sesion.texto_en_edicion and req.mensaje.strip() != sesion.texto_en_edicion.strip():
            texto_raw = f"{sesion.texto_en_edicion}\n\n{req.mensaje.strip()}".strip()
    else:
        texto_raw = (sesion.texto_en_edicion or "").strip()

    if not texto_raw:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO")
        return construir_respuesta(sesion, msg_texto_vacio(intento), ops_texto)

    if len(texto_raw) > TEXTO_MAX:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
        return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX, intento), ops_texto)

    sesion.limpiar_fallos("ESPERANDO_TEXTO")
    sesion.texto_en_edicion = ""
    if sesion.borrador is not None:
        sesion.borrador.texto_en_edicion = ""
    actualizar_metadatos_sesion(sesion, req)

    if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
        texto_base = ""
        if sesion.coincidencias and sesion.coincidencias[0].texto_original:
            # Solo el texto del original; sus recursos ya viven en borrador.recursos
            texto_base, _ = extraer_recursos_y_texto_limpio(sesion.coincidencias[0].texto_original.strip())
        elif sesion.borrador.texto_limpio:
            texto_base = sesion.borrador.texto_limpio.strip()

        texto_consolidado, aviso_priv = consolidar_texto_enriquecimiento(texto_base, texto_raw)
        texto_limpio, recursos_aporte = extraer_recursos_y_texto_limpio(texto_consolidado)
        # La lista multimedia del panel se conserva; el aporte solo suma recursos nuevos
        recursos = fusionar_recursos(sesion.borrador.recursos, recursos_aporte)

        if len(texto_limpio) < TEXTO_MIN:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MIN")
            return construir_respuesta(sesion, msg_error_longitud_minima("texto", TEXTO_MIN, intento), [])

        if len(texto_limpio) > TEXTO_MAX:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
            return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX, intento), [])

        texto_reconstruido = componer_texto_publicable(texto_limpio, recursos)
        sesion.borrador.texto = texto_reconstruido
        sesion.borrador.texto_limpio = texto_limpio
        sesion.borrador.recursos = recursos
        sesion.texto = texto_reconstruido
        sesion.texto_limpio = texto_limpio
        sesion.recursos = recursos
        if req.categoria_id is not None:
            sesion.borrador.categoria_id = req.categoria_id
        if req.tags is not None:
            sesion.borrador.tags = req.tags
        return avanzar_a_metadatos_o_revision(
            sesion, prefijo_borrador_creado(sesion.borrador.articulo_original_id), aviso_privacidad=aviso_priv
        )

    texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto_raw)

    if len(texto_limpio) < TEXTO_MIN:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MIN")
        return construir_respuesta(sesion, msg_error_longitud_minima("texto", TEXTO_MIN, intento), [])

    if len(texto_limpio) > TEXTO_MAX:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
        return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX, intento), [])

    sesion.texto = texto_limpio
    sesion.texto_limpio = texto_limpio
    sesion.recursos = recursos

    sanit_txt = sanitizar_borrador(texto=texto_limpio)
    texto_busqueda = sanit_txt["texto_sanitizado"]
    aviso_privacidad = sanit_txt.get("aviso_privacidad")

    res_txt = await run_in_threadpool(buscador.evaluar_texto, texto_busqueda, True, sesion.titulo, 1)
    if res_txt and res_txt.get("coincidencias"):
        coincs = normalizar_coincidencias(
            res_txt["coincidencias"], mensaje=res_txt.get("mensaje", ""), tipo_coincidencia="semantico"
        )
        coincs = [c for c in coincs if c.id not in sesion.articulos_descartados_ids]
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

    txt_rec = componer_texto_publicable(sesion.texto_limpio, sesion.recursos)
    sesion.contenido_adicional = []
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=sesion.titulo,
        texto=txt_rec,
        texto_limpio=sesion.texto_limpio,
        recursos=sesion.recursos,
        contenido_adicional=[],
        tipo_plantilla=extraer_tipo_plantilla(sesion.tags),
        categoria_id=sesion.categoria_id,
        tags=list(sesion.tags),
    )
    sesion.texto = txt_rec
    return avanzar_a_metadatos_o_revision(
        sesion, PREFIJO_SIN_DUPLICADOS, aviso_privacidad=aviso_privacidad
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
                "[Placeholder] No se encontró el artículo coincidente para enriquecer. Tocá 'continuar' para usar tu propio texto:",
                ["continuar", "reiniciar"],
            )
        elegido = sesion.coincidencias[0]
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        texto_base_limpio, recs_base = extraer_recursos_y_texto_limpio(texto_base)
        if validar_longitud_maxima(texto_base_limpio, TEXTO_MAX, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_aporte = (req.texto or sesion.texto_limpio or sesion.texto or "").strip()
        texto_enriquecido, aviso_priv = consolidar_texto_enriquecimiento(texto_base, texto_aporte)
        texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto_enriquecido)
        if not req.texto:
            # El aporte salió de texto_limpio: sus recursos estaban guardados aparte en la sesión
            recursos = fusionar_recursos(recursos, sesion.recursos)

        if validar_longitud_maxima(texto_limpio, TEXTO_MAX, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX), ["descartar", "reiniciar"])

        es_serie = elegido.tipo_coincidencia == "serie" or opcion == "actualizar"
        titulo_borrador = (sesion.titulo or req.titulo or elegido.titulo).strip() if es_serie else elegido.titulo

        nom_cat = DICCIONARIO_OFICIAL_CATEGORIAS.get(cat_db, f"Categoría {cat_db}") if cat_db else "Sin categoría"
        meta_ant = {
            "categoria_id": cat_db,
            "categoria_nombre": nom_cat,
            "tags": list(tags_db or []),
        } if (cat_db or tags_db) else None

        texto_completo = texto_enriquecido
        sesion.borrador = BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=elegido.id,
            articulo_original_url=elegido.url,
            titulo=titulo_borrador,
            texto=texto_completo,
            texto_limpio=texto_limpio,
            recursos=recursos,
            contenido_adicional=list(sesion.contenido_adicional),
            tipo_plantilla=extraer_tipo_plantilla(tags_ini),
            categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
            tags=tags_ini,
            metadatos_anteriores=meta_ant,
            metadatos_heredados_revisados=False,
        )
        sesion.metadatos_anteriores = meta_ant
        sesion.metadatos_heredados_revisados = False
        sesion.texto = texto_completo
        sesion.texto_limpio = texto_limpio
        sesion.recursos = recursos
        return avanzar_a_metadatos_o_revision(
            sesion, prefijo_borrador_enriquecido(elegido.id), aviso_privacidad=aviso_priv
        )

    if opcion in ("continuar", "descartar"):
        sesion.limpiar_fallos("DECISION_TEXTO")
        for c in sesion.coincidencias:
            if c.id and c.id not in sesion.articulos_descartados_ids:
                sesion.articulos_descartados_ids.append(c.id)
        sesion.coincidencias = []
        txt_limp = sesion.texto_limpio or sesion.texto
        txt_rec = componer_texto_publicable(txt_limp, sesion.recursos)
        sesion.contenido_adicional = []
        sesion.borrador = BorradorSesion(
            modo="nuevo",
            titulo=sesion.titulo,
            texto=txt_rec,
            texto_limpio=txt_limp,
            recursos=sesion.recursos,
            contenido_adicional=[],
            tipo_plantilla=extraer_tipo_plantilla(sesion.tags),
            categoria_id=sesion.categoria_id,
            tags=list(sesion.tags),
        )
        sesion.texto = txt_rec
        return avanzar_a_metadatos_o_revision(sesion, PREFIJO_CONTINUAR_PROPIO)

    if opcion == "volver":
        sesion.limpiar_fallos("DECISION_TEXTO")
        sesion.coincidencias = []
        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Ingresá el texto corregido para tu artículo:",
            ["volver"],
        )

    intento = sesion.registrar_fallo("DECISION_TEXTO")
    return construir_respuesta(sesion, msg_opcion_invalida(intento), OPCIONES_ENRIQUECER_CONTINUAR)


async def handle_esperando_plantilla(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    if opcion == "volver":
        sesion.limpiar_fallos("ESPERANDO_PLANTILLA")
        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Ingresá el texto actualizado para tu artículo:",
            ["confirmar_texto", "volver"],
        )

    b = sesion.borrador
    if req.categoria_id is not None:
        b.categoria_id = req.categoria_id

    opcion_plantilla = opcion or req.texto or req.mensaje or ""
    plantilla = extraer_tipo_plantilla(req.tags or [], opcion_plantilla)
    if not plantilla:
        return construir_respuesta(sesion, MSG_ELEGIR_PLANTILLA, OPCIONES_PLANTILLAS)

    b.tipo_plantilla = plantilla
    b.tags = combinar_tags(plantilla, b.tags, req.tags or [])
    if b.categoria_id is None:
        b.categoria_id = sesion.categoria_id or 1
    return avanzar_a_metadatos_o_revision(sesion)


async def handle_esperando_metadatos(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if opcion == "volver":
        sesion.limpiar_fallos("ESPERANDO_METADATOS")
        sesion.estado = EstadoFlujo.ESPERANDO_PLANTILLA
        if b:
            b.tipo_plantilla = None
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos a la selección de formato. ¿Qué plantilla preferís para este artículo?",
            OPCIONES_PLANTILLAS,
        )

    if req.categoria_id is not None:
        b.categoria_id = req.categoria_id

    texto_fuente = req.mensaje or req.texto or req.accion
    nuevos_tags, cat_res = parsear_metadatos_mensaje(
        req.mensaje,
        req.tags,
        req.categoria_id,
        texto_fallback=texto_fuente,
        categorias_disponibles=sesion.categorias_disponibles,
        tags_disponibles=sesion.tags_disponibles,
    )
    if cat_res is not None:
        b.categoria_id = cat_res

    if b.categoria_id is None:
        b.categoria_id = sesion.categoria_id or 1

    b.tags = combinar_tags(b.tipo_plantilla, b.tags, nuevos_tags)
    sesion.tags = list(b.tags)
    if len(b.tags) < 2:
        intento = sesion.registrar_fallo("ESPERANDO_METADATOS")
        return construir_respuesta(sesion, msg_pedir_tag_adicional(b.tipo_plantilla or "", intento), [])

    sesion.limpiar_fallos("ESPERANDO_METADATOS")
    msg, ops = validar_borrador(sesion, PREFIJO_METADATOS_REGISTRADOS)
    return construir_respuesta(sesion, msg, ops)


async def handle_revision_borrador(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    tenia_conformidad = bool(
        (b and b.conforme)
        or (b and getattr(b, "conformidad_invalidada", False))
        or (sesion.estado == EstadoFlujo.CONFORMIDAD_USUARIO)
        or (b and b.texto_original_conforme is not None and b.texto != b.texto_original_conforme)
    )
    texto_edicion = req.texto
    if texto_edicion is None and opcion == "editar" and req.mensaje and req.mensaje.strip().lower() != "editar":
        texto_edicion = req.mensaje

    hubo_cambios = any(v is not None for v in (req.titulo, texto_edicion, req.categoria_id, req.tags))

    if sesion.confirmando_rechazo:
        if opcion in ("confirmar_rechazo", "rechazar"):
            sesion.confirmando_rechazo = False
            sesion.estado = EstadoFlujo.RECHAZADO
            return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)
        if opcion == "volver":
            sesion.confirmando_rechazo = False
            msg, ops = validar_borrador(sesion)
            return construir_respuesta(
                sesion,
                "[Placeholder] Operación cancelada. Mantenemos tu borrador intacto:\n\n" + msg,
                ops,
            )
        if opcion in ("editar", "sanitizar", "conforme") or hubo_cambios:
            sesion.confirmando_rechazo = False
        else:
            return construir_respuesta(
                sesion,
                "[Placeholder] Por favor confirmá si querés descartar el artículo tocando 'confirmar_rechazo' o 'volver' para continuar trabajando en él.",
                ["confirmar_rechazo", "volver"],
            )

    if opcion == "sanitizar":
        txt_a_sanit = req.texto or b.texto_limpio or b.texto
        limpio = sanitizar_borrador(texto=txt_a_sanit, titulo=req.titulo or b.titulo)
        b.titulo = limpio["titulo_sanitizado"]
        b.texto_limpio = limpio["texto_sanitizado"]
        b.texto = componer_texto_publicable(b.texto_limpio, b.recursos)
        b.conforme = False
        b.conforme_en = None
        sesion.estado = EstadoFlujo.REVISION_BORRADOR
        sesion.texto = b.texto
        sesion.texto_limpio = b.texto_limpio
        if tenia_conformidad:
            b.conformidad_invalidada = True
            prefijo = f"{MSG_CONFORMIDAD_INVALIDADA}\n\n"
        else:
            prefijo = PREFIJO_DATOS_SANITIZADOS
        msg, ops = validar_borrador(sesion, prefijo)
        return construir_respuesta(sesion, msg, ops, aviso_privacidad=limpio.get("aviso_privacidad"))

    if hubo_cambios:
        ops_actuales = (
            OPCIONES_REVISION_VALIDO
            if (sesion.validacion and sesion.validacion.valido)
            else OPCIONES_REVISION_BLOQUEANTE
        )
        if req.titulo is not None:
            tit_nuevo = req.titulo.strip()
            err_tit = validar_longitud_maxima(tit_nuevo, TITULO_MAX, "título")
            if err_tit:
                return construir_respuesta(sesion, err_tit, ops_actuales)
            b.titulo = tit_nuevo

        if texto_edicion is not None:
            txt_nuevo = texto_edicion.strip()
            txt_nuevo_limpio, nuevos_recursos = extraer_recursos_y_texto_limpio(txt_nuevo)
            recursos_combinados = fusionar_recursos(b.recursos, nuevos_recursos)
            # texto_limpio es solo texto: no hay marcadores que verificar ni restaurar
            txt_verif, adv = txt_nuevo_limpio, []
            err_txt = validar_longitud_maxima(txt_verif, TEXTO_MAX, "texto")
            if err_txt:
                return construir_respuesta(sesion, err_txt, ops_actuales)
            b.texto_limpio = txt_verif
            b.recursos = recursos_combinados
            b.texto = componer_texto_publicable(b.texto_limpio, b.recursos)
            b.conforme = False
            b.conforme_en = None
            sesion.estado = EstadoFlujo.REVISION_BORRADOR
            if adv:
                b.advertencias_recursos.extend(adv)
            sesion.texto = b.texto
            sesion.texto_limpio = b.texto_limpio
            sesion.recursos = recursos_combinados

        if req.categoria_id is not None:
            b.categoria_id = req.categoria_id
        if req.tags is not None:
            plantilla_nueva = extraer_tipo_plantilla(req.tags) or b.tipo_plantilla
            b.tipo_plantilla = plantilla_nueva
            b.tags = combinar_tags(plantilla_nueva, req.tags)

        if tenia_conformidad:
            b.conformidad_invalidada = True
            prefijo = f"{MSG_CONFORMIDAD_INVALIDADA}\n\n"
        else:
            prefijo = PREFIJO_BORRADOR_ACTUALIZADO
        msg, ops = validar_borrador(sesion, prefijo)
        return construir_respuesta(sesion, msg, ops)

    if opcion == "editar":
        ops = (
            OPCIONES_REVISION_VALIDO
            if (sesion.validacion and sesion.validacion.valido)
            else OPCIONES_REVISION_BLOQUEANTE
        )
        return construir_respuesta(sesion, MSG_PEDIR_EDICION, ops)

    if opcion == "volver":
        sesion.limpiar_fallos("REVISION_BORRADOR")
        if b and b.modo == "enriquecimiento":
            sesion.estado = EstadoFlujo.DECISION_TITULO
            elegido = sesion.coincidencias[0] if sesion.coincidencias else None
            es_serie = elegido and elegido.tipo_coincidencia == "serie"
            ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
            return construir_respuesta(
                sesion,
                "[Placeholder] Volvemos al paso anterior. ¿Deseás enriquecer el artículo encontrado o descartarlo?",
                ops,
            )
        sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
        return construir_respuesta(
            sesion,
            "[Placeholder] Volvemos al paso anterior. Podés redefinir las etiquetas o tags para clasificar tu artículo:",
            ["volver"],
        )

    if opcion == "conforme":
        if b:
            b.metadatos_heredados_revisados = True
        sesion.metadatos_heredados_revisados = True
        if not sesion.validacion:
            validar_borrador(sesion)
        if not sesion.validacion or not sesion.validacion.valido:
            msg, ops = validar_borrador(sesion, PREFIJO_ERROR_CONFORMIDAD)
            return construir_respuesta(sesion, msg, ops)
        limpio = sanitizar_borrador(texto=b.texto, titulo=b.titulo)
        b.titulo = limpio["titulo_sanitizado"]
        b.texto = limpio["texto_sanitizado"]
        b.conforme = True
        b.conforme_en = datetime.now(timezone.utc).isoformat()
        b.texto_original_conforme = b.texto
        b.conformidad_invalidada = False
        sesion.estado = EstadoFlujo.CONFORMIDAD_USUARIO
        if sesion.validacion and sesion.validacion.status == "Listo con ajustes sugeridos":
            mensaje_conforme = (
                f"{MSG_CONFORMIDAD_REGISTRADA}\n\n"
                "(observaciones de estilo confirmadas por el redactor)."
            )
        else:
            mensaje_conforme = MSG_CONFORMIDAD_REGISTRADA
        return construir_respuesta(
            sesion,
            mensaje_conforme,
            OPCIONES_CONFORMIDAD,
            aviso_privacidad=limpio.get("aviso_privacidad"),
        )

    if opcion in ("aceptar", "aceptar_metadatos") and b and b.metadatos_anteriores:
        b.metadatos_heredados_revisados = True
        sesion.metadatos_heredados_revisados = True
        msg, ops = validar_borrador(sesion, "Se confirmaron los metadatos de la versión anterior. ")
        return construir_respuesta(sesion, msg, ops)

    if opcion in ("rechazar_metadatos",) or (
        opcion == "rechazar" and b and b.metadatos_anteriores and not b.metadatos_heredados_revisados
    ):
        b.metadatos_heredados_revisados = True
        sesion.metadatos_heredados_revisados = True
        b.categoria_id = None
        b.tags = []
        sesion.categoria_id = None
        sesion.tags = []
        msg, ops = validar_borrador(sesion, "Se descartaron los metadatos heredados. ")
        return construir_respuesta(sesion, msg, ops)

    if opcion == "copiar_borrador":
        return construir_respuesta(
            sesion,
            MSG_CONFORMIDAD_REGISTRADA,
            OPCIONES_CONFORMIDAD,
        )

    if opcion == "rechazar":
        sesion.confirmando_rechazo = True
        return construir_respuesta(
            sesion,
            "[Placeholder] ¿Estás seguro de que querés descartar todo el artículo? Se perderán los cambios realizados en esta sesión.",
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
}
