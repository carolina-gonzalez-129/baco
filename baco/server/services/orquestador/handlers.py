from datetime import datetime, timezone
import re
from typing import Callable, Coroutine, Dict, Optional, Tuple
from starlette.concurrency import run_in_threadpool

from baco.server.config_limites import (
    TEXTO_MAX,
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
from baco.server.services.validar_articulo import sanitizar_borrador
from baco.server.services.orquestador.mensajes import (
    MSG_CONFORMIDAD_INVALIDADA,
    MSG_CONFORMIDAD_REGISTRADA,
    MSG_DESCARTAR_COINCIDENCIA_TITULO,
    MSG_ELEGIR_PLANTILLA,
    MSG_OPERACION_CANCELADA,
    MSG_OPCIONES_RECURSOS_SKILLS,
    OPCIONES_RECURSOS_SKILLS,
    MSG_PEDIR_EDICION,
    MSG_RECHAZADO,
    MSG_SIN_COINCIDENCIAS_TITULO,
    MSG_TEXTO_EN_EDICION,
    MSG_VOLVER_ENRIQUECER_O_DESCARTAR,
    MSG_VOLVER_METADATOS,
    MSG_VOLVER_PLANTILLA,
    MSG_VOLVER_TEXTO,
    MSG_VOLVER_TEXTO_ACTUALIZADO,
    MSG_VOLVER_TITULO,
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
    msg_pedir_categoria,
    msg_pedir_tag_adicional,
    msg_pedir_tags_y_categoria,
    msg_texto_vacio,
    prefijo_borrador_creado,
    prefijo_borrador_enriquecido,
)
from baco.server.services.orquestador.recursos_service import (
    _max_num_recurso,
    componer_texto_publicable,
    extraer_recursos_y_texto_limpio,
    fusionar_recursos,
    fusionar_texto_y_recursos_sin_colision,
    procesar_recursos_y_marcadores,
    sincronizar_recursos_con_marcadores,
    texto_efectivo_sin_marcadores,
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
                "No se encontró la coincidencia previa seleccionada. Por favor, ingresá el título de tu artículo:",
                [],
            )
        elegido = sesion.coincidencias[0]
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        texto_base_limpio, recs_base = extraer_recursos_y_texto_limpio(
            texto_base, ultimo_id=sesion.ultimo_id_recurso
        )
        if validar_longitud_maxima(texto_base_limpio, TEXTO_MAX_PERCENTIL_99, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX_PERCENTIL_99), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_enviado = (req.texto or "").strip()
        if texto_enviado:
            tl_env_remap, recursos, _ = procesar_recursos_y_marcadores(
                texto_enviado,
                recursos_previos=recs_base,
                ultimo_id=max(sesion.ultimo_id_recurso, _max_num_recurso(recs_base)),
                validar_marcadores_existentes=False,
            )
            texto_limpio, aviso_priv = consolidar_texto_enriquecimiento(texto_base_limpio, tl_env_remap)
            recursos = sincronizar_recursos_con_marcadores(texto_limpio, recursos)
        else:
            texto_limpio = texto_base_limpio
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

        texto_completo = componer_texto_publicable(texto_limpio, recursos)
        sesion.borrador = BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=elegido.id,
            articulo_original_url=elegido.url,
            titulo=titulo_borrador,
            texto=texto_completo,
            texto_limpio=texto_limpio,
            texto_base_limpio=texto_base_limpio,
            recursos=recursos,
            ultimo_id_recurso=max_id,
            contenido_adicional=list(sesion.contenido_adicional),
            tipo_plantilla=extraer_tipo_plantilla(tags_ini),
            categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
            tags=tags_ini,
            metadatos_anteriores=meta_ant,
            metadatos_heredados_revisados=False,
        )
        sesion.metadatos_anteriores = meta_ant
        sesion.metadatos_heredados_revisados = False
        sesion.actualizar_contenido_borrador(
            texto_limpio=texto_limpio,
            texto_base_limpio=texto_base_limpio,
            recursos=recursos,
            ultimo_id_recurso=max_id,
        )

        err = validar_longitud(texto_limpio, TEXTO_MIN, TEXTO_MAX_PERCENTIL_99, "texto")
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
            if c.tipo_coincidencia == "serie" or "serie" in getattr(c, "mensaje", "").lower():
                sesion.descarto_serie = True
            if c.id and c.id not in sesion.articulos_descartados_ids:
                sesion.articulos_descartados_ids.append(c.id)
        sesion.coincidencias = []
        texto_disponible = (req.texto or sesion.texto_limpio or sesion.texto or "").strip()
        if texto_disponible:
            txt_disp_limpio, recs_disp, _ = procesar_recursos_y_marcadores(
                texto_disponible,
                recursos_previos=sesion.recursos,
                ultimo_id=sesion.ultimo_id_recurso,
                validar_marcadores_existentes=False,
            )
            recs_disp = sincronizar_recursos_con_marcadores(txt_disp_limpio, recs_disp)
        else:
            txt_disp_limpio, recs_disp = "", sesion.recursos

        if txt_disp_limpio and len(texto_efectivo_sin_marcadores(txt_disp_limpio)) >= TEXTO_MIN:
            # Condición sine qua non: habiendo recibido título y texto, al descartar
            # la coincidencia de título la búsqueda por duplicados continúa sobre el texto.
            sanit_txt = sanitizar_borrador(texto=txt_disp_limpio, titulo=sesion.titulo)
            texto_sanitizado = sanit_txt["texto_sanitizado"]
            aviso_privacidad = sanit_txt.get("aviso_privacidad")
            max_id = max(sesion.ultimo_id_recurso, _max_num_recurso(recs_disp))
            sesion.actualizar_contenido_borrador(
                texto_limpio=texto_sanitizado,
                recursos=recs_disp,
                ultimo_id_recurso=max_id,
            )
            texto_busqueda = texto_efectivo_sin_marcadores(texto_sanitizado)

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

            # Si evaluar_texto no arrojó coincidencias, se crea el borrador nuevo y avanza
            txt_rec = componer_texto_publicable(sesion.texto_limpio, sesion.recursos)
            sesion.contenido_adicional = []
            sesion.borrador = BorradorSesion(
                modo="nuevo",
                titulo=sesion.titulo,
                texto=txt_rec,
                texto_limpio=sesion.texto_limpio,
                recursos=sesion.recursos,
                ultimo_id_recurso=max_id,
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
            MSG_VOLVER_TITULO,
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
                MSG_VOLVER_ENRIQUECER_O_DESCARTAR,
                ops,
            )
        sesion.estado = EstadoFlujo.ESPERANDO_TITULO
        return construir_respuesta(
            sesion,
            MSG_VOLVER_TITULO,
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
                    " Descartamos el artículo existente. Ingresá el texto o los pasos para redactar tu propio artículo:",
                    ["confirmar_texto", "volver"],
                )

    ops_texto = (
        ["confirmar_texto", "descartar", "volver"]
        if (sesion.borrador and sesion.borrador.modo == "enriquecimiento")
        else ["confirmar_texto", "volver"]
    )
    prefijo_resultado_recursos = ""
    if opcion == "quitar_recursos":
        sesion.recursos = {}
        sesion.orden_multimedia = []
        sesion.posiciones = []
        if sesion.texto_en_edicion:
            sesion.texto_en_edicion = re.sub(r"\[\[recurso:[a-zA-Z0-9_\-]+\]\]\s*", "", sesion.texto_en_edicion).strip()
        if sesion.texto_limpio:
            sesion.texto_limpio = re.sub(r"\[\[recurso:[a-zA-Z0-9_\-]+\]\]\s*", "", sesion.texto_limpio).strip()
        if sesion.borrador is not None:
            sesion.borrador.recursos = {}
            sesion.borrador.orden_multimedia = []
            sesion.borrador.posiciones = []
            if sesion.borrador.texto_limpio:
                sesion.borrador.texto_limpio = re.sub(r"\[\[recurso:[a-zA-Z0-9_\-]+\]\]\s*", "", sesion.borrador.texto_limpio).strip()
        prefijo_resultado_recursos = "Se quitaron los recursos multimedia. Las skills del agente quedan habilitadas para este borrador.\n\n"
        es_confirmacion = True
    elif opcion == "seguir_con_recursos":
        prefijo_resultado_recursos = "Continuamos conservando los recursos multimedia en el borrador (las skills de asistencia quedan deshabilitadas).\n\n"
        es_confirmacion = True
    else:
        es_confirmacion = opcion == "confirmar_texto" or (
            req.accion and req.accion.strip().lower() in ("confirmar_texto", "confirmar texto", "confirmar")
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
        frag_tl, recs_combinados, _ = procesar_recursos_y_marcadores(
            fragmento,
            recursos_previos=recursos_prev,
            ultimo_id=ultimo_id_prev,
            validar_marcadores_existentes=False,
        )
        sanit_frag = sanitizar_borrador(texto=frag_tl, titulo=sesion.titulo)
        fragmento_limpio = sanit_frag["texto_sanitizado"]
        aviso_priv_frag = sanit_frag.get("aviso_privacidad")

        if req.texto is not None:
            nuevo_borrador_txt = fragmento_limpio
        elif sesion.texto_en_edicion:
            nuevo_borrador_txt = f"{sesion.texto_en_edicion}\n\n{fragmento_limpio}".strip()
        else:
            nuevo_borrador_txt = fragmento_limpio

        largo_efectivo = len(texto_efectivo_sin_marcadores(nuevo_borrador_txt))
        if largo_efectivo > TEXTO_MAX_PERCENTIL_99:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
            return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX_PERCENTIL_99, intento), ops_texto)

        max_id_frag = max(ultimo_id_prev, _max_num_recurso(recs_combinados))
        sesion.actualizar_contenido_borrador(
            texto_en_edicion=nuevo_borrador_txt,
            texto_limpio=nuevo_borrador_txt,
            recursos=recs_combinados,
            ultimo_id_recurso=max_id_frag,
            categoria_id=req.categoria_id,
            tags=req.tags,
        )

        if bool(recs_combinados):
            return construir_respuesta(
                sesion,
                MSG_OPCIONES_RECURSOS_SKILLS,
                OPCIONES_RECURSOS_SKILLS,
                aviso_privacidad=aviso_priv_frag,
            )

        if largo_efectivo > TEXTO_MAX:
            msg_edicion = (
                f"Guardé tu texto en edición ({largo_efectivo} / {TEXTO_MAX_PERCENTIL_99} caracteres). "
                f"Tené en cuenta que al superar los {TEXTO_MAX} caracteres, las skills del agente quedan deshabilitadas. "
                "Podés seguir escribiendo o pegando más contenido, y cuando esté listo tocá 'Confirmar texto'."
            )
        else:
            msg_edicion = (
                f"Guardé tu texto en edición ({largo_efectivo} / {TEXTO_MAX_PERCENTIL_99} caracteres). "
                "Podés seguir escribiendo o pegando más contenido, y cuando esté listo tocá 'Confirmar texto'."
            )
        return construir_respuesta(sesion, msg_edicion, ops_texto, aviso_privacidad=aviso_priv_frag)

    if req.texto is not None:
        texto_raw = req.texto.strip()
        if (
            sesion.texto_en_edicion
            and req.texto.strip() != sesion.texto_en_edicion.strip()
            and (sesion.borrador is None or sesion.borrador.modo != "enriquecimiento")
        ):
            texto_raw = f"{sesion.texto_en_edicion}\n\n{req.texto.strip()}".strip()
    elif req.mensaje is not None and req.mensaje.strip().lower() not in (
        "confirmar_texto", "confirmar texto", "confirmar",
        "quitar_recursos", "quitar recursos", "seguir_con_recursos", "seguir con recursos"
    ):
        texto_raw = req.mensaje.strip()
        if sesion.texto_en_edicion and req.mensaje.strip() != sesion.texto_en_edicion.strip():
            texto_raw = f"{sesion.texto_en_edicion}\n\n{req.mensaje.strip()}".strip()
    else:
        texto_raw = (sesion.texto_limpio or sesion.texto_en_edicion or "").strip()

    if opcion == "quitar_recursos":
        texto_raw = re.sub(r"\[\[recurso:[a-zA-Z0-9_\-]+\]\]\s*", "", texto_raw).strip()

    if not texto_raw:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO")
        return construir_respuesta(sesion, msg_texto_vacio(intento), ops_texto)

    sesion.limpiar_fallos("ESPERANDO_TEXTO")
    sesion.texto_en_edicion = ""
    if sesion.borrador is not None:
        sesion.borrador.texto_en_edicion = ""
    actualizar_metadatos_sesion(sesion, req)

    if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
        texto_base = ""
        if sesion.borrador.texto_base_limpio:
            texto_base = sesion.borrador.texto_base_limpio.strip()
        elif sesion.coincidencias and sesion.coincidencias[0].texto_original:
            texto_base, _ = extraer_recursos_y_texto_limpio(sesion.coincidencias[0].texto_original.strip())
        elif sesion.borrador.texto_limpio:
            texto_base = sesion.borrador.texto_limpio.strip()

        ultimo_id_enriq = max(
            sesion.ultimo_id_recurso,
            sesion.borrador.ultimo_id_recurso,
            _max_num_recurso(sesion.borrador.recursos),
        )
        tl_aporte_remap, recursos, err_marcadores = procesar_recursos_y_marcadores(
            texto_raw,
            recursos_previos=sesion.borrador.recursos,
            ultimo_id=ultimo_id_enriq,
        )
        if err_marcadores:
            return construir_respuesta(sesion, err_marcadores, ["volver"])

        texto_limpio, aviso_priv = consolidar_texto_enriquecimiento(texto_base, tl_aporte_remap)
        largo_efectivo = len(texto_efectivo_sin_marcadores(texto_limpio))

        if largo_efectivo < TEXTO_MIN:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MIN")
            return construir_respuesta(sesion, msg_error_longitud_minima("texto", TEXTO_MIN, intento), [])

        if largo_efectivo > TEXTO_MAX_PERCENTIL_99:
            intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
            return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX_PERCENTIL_99, intento), [])

        if bool(recursos) and opcion not in ("quitar_recursos", "seguir_con_recursos", "confirmar_texto"):
            sesion.actualizar_contenido_borrador(
                texto_limpio=texto_limpio,
                texto_base_limpio=texto_limpio,
                texto_en_edicion=texto_limpio,
                recursos=recursos,
            )
            return construir_respuesta(
                sesion,
                MSG_OPCIONES_RECURSOS_SKILLS,
                OPCIONES_RECURSOS_SKILLS,
            )

        recursos_finales = sincronizar_recursos_con_marcadores(texto_limpio, recursos)
        max_id_enriq = max(
            ultimo_id_enriq,
            _max_num_recurso(recursos),
            _max_num_recurso(sesion.borrador.recursos),
        )
        sesion.actualizar_contenido_borrador(
            texto_limpio=texto_limpio,
            texto_base_limpio=texto_limpio,
            recursos=recursos_finales,
            ultimo_id_recurso=max_id_enriq,
            categoria_id=req.categoria_id,
            tags=req.tags,
        )
        pref_enriq = f"{prefijo_resultado_recursos}{prefijo_borrador_creado(sesion.borrador.articulo_original_id)}"
        return avanzar_a_metadatos_o_revision(
            sesion, pref_enriq, aviso_privacidad=aviso_priv
        )

    texto_limpio, recursos, err_marcadores = procesar_recursos_y_marcadores(
        texto_raw,
        recursos_previos=sesion.recursos,
        ultimo_id=sesion.ultimo_id_recurso,
        mensaje_error_custom="El texto contiene marcadores no válidos ({marcadores}). Los recursos multimedia deben adjuntarse mediante enlaces o subida de archivos, no escribiendo marcadores manualmente.",
    )
    if err_marcadores:
        sesion.registrar_fallo("MARCADORES_MANUALES")
        return construir_respuesta(sesion, err_marcadores, ["volver"])

    if bool(recursos) and opcion not in ("quitar_recursos", "seguir_con_recursos", "confirmar_texto"):
        max_id_nuevo = max(sesion.ultimo_id_recurso, _max_num_recurso(recursos))
        sesion.actualizar_contenido_borrador(
            texto_limpio=texto_limpio,
            texto_en_edicion=texto_limpio,
            recursos=recursos,
            ultimo_id_recurso=max_id_nuevo,
        )
        return construir_respuesta(
            sesion,
            MSG_OPCIONES_RECURSOS_SKILLS,
            OPCIONES_RECURSOS_SKILLS,
        )

    largo_efectivo = len(texto_efectivo_sin_marcadores(texto_limpio))
    if largo_efectivo < TEXTO_MIN:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MIN")
        return construir_respuesta(sesion, msg_error_longitud_minima("texto", TEXTO_MIN, intento), [])

    if largo_efectivo > TEXTO_MAX_PERCENTIL_99:
        intento = sesion.registrar_fallo("ESPERANDO_TEXTO_MAX")
        return construir_respuesta(sesion, msg_error_longitud_maxima("texto", TEXTO_MAX_PERCENTIL_99, intento), [])

    sanit_txt = sanitizar_borrador(texto=texto_limpio, titulo=sesion.titulo)
    texto_sanitizado = sanit_txt["texto_sanitizado"]
    aviso_privacidad = sanit_txt.get("aviso_privacidad")

    recursos_finales = sincronizar_recursos_con_marcadores(texto_sanitizado, recursos)
    max_id_nuevo = max(sesion.ultimo_id_recurso, _max_num_recurso(recursos))
    sesion.actualizar_contenido_borrador(
        texto_limpio=texto_sanitizado,
        recursos=recursos_finales,
        ultimo_id_recurso=max_id_nuevo,
    )
    texto_busqueda = texto_efectivo_sin_marcadores(texto_sanitizado)

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

    txt_rec = componer_texto_publicable(sesion.texto_limpio, sesion.recursos)
    sesion.contenido_adicional = []
    sesion.borrador = BorradorSesion(
        modo="nuevo",
        titulo=sesion.titulo,
        texto=txt_rec,
        texto_limpio=sesion.texto_limpio,
        recursos=sesion.recursos,
        ultimo_id_recurso=max_id_nuevo,
        contenido_adicional=[],
        tipo_plantilla=extraer_tipo_plantilla(sesion.tags),
        categoria_id=sesion.categoria_id,
        tags=list(sesion.tags),
    )
    sesion.texto = txt_rec
    pref_final = f"{prefijo_resultado_recursos}{PREFIJO_SIN_DUPLICADOS}"
    return avanzar_a_metadatos_o_revision(
        sesion, pref_final, aviso_privacidad=aviso_privacidad
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
                "No se encontró el artículo coincidente para enriquecer. Tocá 'continuar' para usar tu propio texto:",
                ["continuar", "reiniciar"],
            )
        elegido = sesion.coincidencias[0]
        texto_db, cat_db, tags_db = await cargar_datos_articulo(buscador, elegido.id)
        texto_base = (texto_db or "").strip()
        elegido.texto_original = texto_base

        texto_base_limpio, recs_base = extraer_recursos_y_texto_limpio(texto_base)
        if validar_longitud_maxima(texto_base_limpio, TEXTO_MAX_PERCENTIL_99, "texto"):
            return construir_respuesta(sesion, msg_articulo_muy_largo(TEXTO_MAX_PERCENTIL_99), ["descartar", "reiniciar"])

        tags_ini = req.tags if req.tags is not None else (tags_db or sesion.tags)
        texto_aporte = (req.texto or "").strip() or (sesion.texto or "").strip() or (sesion.texto_limpio or "").strip()
        tl_aporte_remap, recursos, _ = procesar_recursos_y_marcadores(
            texto_aporte,
            recursos_previos=recs_base,
            ultimo_id=max(sesion.ultimo_id_recurso, _max_num_recurso(recs_base)),
            validar_marcadores_existentes=False,
        )
        if texto_base_limpio and tl_aporte_remap and texto_base_limpio not in tl_aporte_remap:
            tl_aporte_remap = f"{texto_base_limpio}\n\n{tl_aporte_remap}".strip()
        texto_limpio, aviso_priv = consolidar_texto_enriquecimiento(texto_base_limpio, tl_aporte_remap)

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

        recursos_finales = sincronizar_recursos_con_marcadores(texto_limpio, recursos)
        max_id = max(sesion.ultimo_id_recurso, _max_num_recurso(recursos), _max_num_recurso(recs_base))
        texto_completo = componer_texto_publicable(texto_limpio, recursos_finales)
        sesion.borrador = BorradorSesion(
            modo="enriquecimiento",
            articulo_original_id=elegido.id,
            articulo_original_url=elegido.url,
            titulo=titulo_borrador,
            texto=texto_completo,
            texto_limpio=texto_limpio,
            texto_base_limpio=texto_base_limpio,
            recursos=recursos_finales,
            ultimo_id_recurso=max_id,
            contenido_adicional=list(sesion.contenido_adicional),
            tipo_plantilla=extraer_tipo_plantilla(tags_ini),
            categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
            tags=tags_ini,
            metadatos_anteriores=meta_ant,
            metadatos_heredados_revisados=False,
        )
        sesion.metadatos_anteriores = meta_ant
        sesion.metadatos_heredados_revisados = False
        sesion.actualizar_contenido_borrador(
            texto_limpio=texto_limpio,
            texto_base_limpio=texto_base_limpio,
            recursos=recursos_finales,
            ultimo_id_recurso=max_id,
        )
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
        max_id = max(sesion.ultimo_id_recurso, _max_num_recurso(sesion.recursos))
        sesion.contenido_adicional = []
        sesion.borrador = BorradorSesion(
            modo="nuevo",
            titulo=sesion.titulo,
            texto=txt_rec,
            texto_limpio=txt_limp,
            recursos=sesion.recursos,
            ultimo_id_recurso=max_id,
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
            MSG_VOLVER_TEXTO,
            ["volver"],
        )

    intento = sesion.registrar_fallo("DECISION_TEXTO")
    return construir_respuesta(sesion, msg_opcion_invalida(intento), OPCIONES_ENRIQUECER_CONTINUAR)


async def handle_esperando_plantilla(
    sesion: SesionChat, req: ChatOrquestadorRequest, opcion: str, buscador: BuscadorDuplicados
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if opcion == "volver":
        sesion.limpiar_fallos("ESPERANDO_PLANTILLA")
        if b and b.metadatos_anteriores:
            b.metadatos_heredados_revisados = False
            sesion.metadatos_heredados_revisados = False
            ant = b.metadatos_anteriores
            b.categoria_id = ant.get("categoria_id")
            b.tags = list(ant.get("tags") or [])
            b.tipo_plantilla = extraer_tipo_plantilla(b.tags)
            sesion.categoria_id = b.categoria_id
            sesion.tags = list(b.tags)
            return avanzar_a_metadatos_o_revision(sesion)
        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return construir_respuesta(
            sesion,
            MSG_VOLVER_TEXTO_ACTUALIZADO,
            ["confirmar_texto", "volver"],
        )

    if req.categoria_id is not None:
        b.categoria_id = req.categoria_id

    if b and req.texto is not None and req.texto.strip():
        ultimo_id_p = max(sesion.ultimo_id_recurso, b.ultimo_id_recurso, _max_num_recurso(b.recursos))
        tl_plant, recs_plant, _ = procesar_recursos_y_marcadores(
            req.texto.strip(),
            recursos_previos=b.recursos,
            ultimo_id=ultimo_id_p,
            validar_marcadores_existentes=False,
        )
        recs_finales_plant = sincronizar_recursos_con_marcadores(tl_plant, recs_plant)
        sesion.actualizar_contenido_borrador(
            texto_limpio=tl_plant,
            texto_base_limpio=tl_plant if b.modo == "enriquecimiento" else None,
            recursos=recs_finales_plant,
            ultimo_id_recurso=max(ultimo_id_p, _max_num_recurso(recs_finales_plant)),
        )

    opcion_plantilla = opcion or req.texto or req.mensaje or ""
    plantilla = extraer_tipo_plantilla(req.tags or [], opcion_plantilla)
    if not plantilla:
        return construir_respuesta(sesion, MSG_ELEGIR_PLANTILLA, OPCIONES_PLANTILLAS)

    b.tipo_plantilla = plantilla
    b.tags = combinar_tags(plantilla, b.tags, req.tags or [])
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id
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
            MSG_VOLVER_PLANTILLA,
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

    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id

    b.tags = combinar_tags(b.tipo_plantilla, b.tags, nuevos_tags)
    sesion.tags = list(b.tags)
    if b.categoria_id is not None:
        sesion.categoria_id = b.categoria_id

    tags_faltan = len(b.tags) < 2
    cat_falta = b.categoria_id is None

    if tags_faltan or cat_falta:
        intento = sesion.registrar_fallo("ESPERANDO_METADATOS")
        if tags_faltan and cat_falta:
            msg = msg_pedir_tags_y_categoria(b.tipo_plantilla or "", intento)
        elif cat_falta:
            msg = msg_pedir_categoria(intento)
        else:
            msg = msg_pedir_tag_adicional(b.tipo_plantilla or "", intento)
        return construir_respuesta(sesion, msg, ["volver"])

    sesion.limpiar_fallos("ESPERANDO_METADATOS")
    msg, ops = validar_borrador(sesion, PREFIJO_METADATOS_REGISTRADOS)
    return construir_respuesta(sesion, msg, ops)


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

    if opcion in ("editar", "sanitizar", "conforme") or hubo_cambios:
        sesion.confirmando_rechazo = False
        return None

    return construir_respuesta(
        sesion,
        "Por favor confirmá si querés descartar el artículo tocando 'confirmar_rechazo' o 'volver' para continuar trabajando en él.",
        ["confirmar_rechazo", "volver"],
    )


def _gestionar_metadatos_heredados(
    sesion: SesionChat, opcion: str
) -> Optional[ChatOrquestadorResponse]:
    """Aísla la resolución de aceptar_metadatos / rechazar_metadatos."""
    b = sesion.borrador
    if not b or not b.metadatos_anteriores:
        return None

    if opcion in ("aceptar", "aceptar_metadatos"):
        b.metadatos_heredados_revisados = True
        sesion.metadatos_heredados_revisados = True
        return avanzar_a_metadatos_o_revision(sesion, prefijo="Se confirmaron los metadatos de la versión anterior. ")

    if opcion in ("rechazar_metadatos",) or (
        opcion == "rechazar" and not b.metadatos_heredados_revisados
    ):
        b.metadatos_heredados_revisados = True
        sesion.metadatos_heredados_revisados = True
        b.tipo_plantilla = None
        b.categoria_id = None
        b.tags = []
        sesion.categoria_id = None
        sesion.tags = []
        return avanzar_a_metadatos_o_revision(sesion, prefijo="Se descartaron los metadatos heredados. ")

    return None


def _ejecutar_sanitizacion_borrador(
    sesion: SesionChat, req: ChatOrquestadorRequest, tenia_conformidad: bool
) -> ChatOrquestadorResponse:
    """Ejecuta la sanitización sobre el borrador actual (explícita o silenciosa)."""
    b = sesion.borrador
    if b is None:
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    txt_a_sanit = req.texto or b.texto_limpio or b.texto
    ultimo_id_sanit = max(sesion.ultimo_id_recurso, b.ultimo_id_recurso, _max_num_recurso(b.recursos))
    tl_sanit_in, recs_sanit_comb, _ = procesar_recursos_y_marcadores(
        txt_a_sanit,
        recursos_previos=b.recursos,
        ultimo_id=ultimo_id_sanit,
        validar_marcadores_existentes=False,
    )

    if b.modo == "enriquecimiento" and (
        b.texto_base_limpio or (sesion.coincidencias and sesion.coincidencias[0].texto_original)
    ):
        texto_base_limpio = (
            b.texto_base_limpio
            if b.texto_base_limpio
            else extraer_recursos_y_texto_limpio(sesion.coincidencias[0].texto_original.strip())[0]
        )
        txt_sanitizado, aviso_sanit = consolidar_texto_enriquecimiento(texto_base_limpio, tl_sanit_in)
        limpio_tit = sanitizar_borrador(texto="", titulo=req.titulo or b.titulo)
        titulo_sanitizado = limpio_tit["titulo_sanitizado"]
    else:
        limpio = sanitizar_borrador(texto=tl_sanit_in, titulo=req.titulo or b.titulo)
        titulo_sanitizado = limpio["titulo_sanitizado"]
        txt_sanitizado = limpio["texto_sanitizado"]
        aviso_sanit = limpio.get("aviso_privacidad")

    recs_sanit_finales = sincronizar_recursos_con_marcadores(txt_sanitizado, recs_sanit_comb)
    max_id = max(ultimo_id_sanit, _max_num_recurso(recs_sanit_comb))
    sesion.actualizar_contenido_borrador(
        titulo=titulo_sanitizado,
        texto_limpio=txt_sanitizado,
        texto_base_limpio=txt_sanitizado if b.modo == "enriquecimiento" else None,
        recursos=recs_sanit_finales,
        ultimo_id_recurso=max_id,
    )
    b.conforme = False
    b.conforme_en = None
    sesion.estado = EstadoFlujo.REVISION_BORRADOR

    if tenia_conformidad:
        b.conformidad_invalidada = True
        prefijo = f"{MSG_CONFORMIDAD_INVALIDADA}\n\n"
    else:
        prefijo = PREFIJO_DATOS_SANITIZADOS

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_sanit)


def _aplicar_mutaciones_borrador(
    sesion: SesionChat,
    req: ChatOrquestadorRequest,
    texto_edicion: Optional[str] = None,
    tenia_conformidad: bool = False,
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

    if req.titulo is not None:
        tit_nuevo = req.titulo.strip()
        err_tit = validar_longitud_maxima(tit_nuevo, TITULO_MAX, "título")
        if err_tit:
            return construir_respuesta(sesion, err_tit, ops_actuales)
        sanit_tit = sanitizar_borrador(texto="", titulo=tit_nuevo)
        titulo_nuevo = sanit_tit["titulo_sanitizado"]
        if sanit_tit.get("aviso_privacidad"):
            aviso_priv_edicion = sanit_tit.get("aviso_privacidad")

    recursos_nuevos = None
    txt_nuevo_limpio = None
    ultimo_id_nuevo = None

    if texto_edicion is not None:
        txt_nuevo = texto_edicion.strip()
        ultimo_id_edit = max(sesion.ultimo_id_recurso, b.ultimo_id_recurso, _max_num_recurso(b.recursos))
        txt_proc, recs_comb, err_marcadores = procesar_recursos_y_marcadores(
            txt_nuevo,
            recursos_previos=b.recursos,
            ultimo_id=ultimo_id_edit,
        )
        if err_marcadores:
            return construir_respuesta(sesion, err_marcadores, ops_actuales)

        if b.modo == "enriquecimiento" and (
            b.texto_base_limpio or (sesion.coincidencias and sesion.coincidencias[0].texto_original)
        ):
            texto_base_limpio = (
                b.texto_base_limpio
                if b.texto_base_limpio
                else extraer_recursos_y_texto_limpio(sesion.coincidencias[0].texto_original.strip())[0]
            )
            txt_verif, aviso_txt = consolidar_texto_enriquecimiento(texto_base_limpio, txt_proc)
        else:
            sanit_edit = sanitizar_borrador(texto=txt_proc, titulo=titulo_nuevo or b.titulo)
            txt_verif = sanit_edit["texto_sanitizado"]
            aviso_txt = sanit_edit.get("aviso_privacidad")

        if aviso_txt:
            aviso_priv_edicion = f"{aviso_priv_edicion}\n{aviso_txt}" if aviso_priv_edicion else aviso_txt

        err_txt = validar_longitud_maxima(txt_verif, TEXTO_MAX_PERCENTIL_99, "texto")
        if err_txt:
            return construir_respuesta(sesion, err_txt, ops_actuales)

        txt_nuevo_limpio = txt_verif
        recursos_nuevos = sincronizar_recursos_con_marcadores(txt_verif, recs_comb)
        ultimo_id_nuevo = max(ultimo_id_edit, _max_num_recurso(recs_comb))

    tags_nuevos = None
    plantilla_nueva = None
    if req.tags is not None:
        plantilla_nueva = extraer_tipo_plantilla(req.tags) or b.tipo_plantilla
        tags_nuevos = combinar_tags(plantilla_nueva, req.tags)

    sesion.actualizar_contenido_borrador(
        titulo=titulo_nuevo,
        texto_limpio=txt_nuevo_limpio,
        texto_base_limpio=txt_nuevo_limpio if b.modo == "enriquecimiento" else None,
        recursos=recursos_nuevos,
        ultimo_id_recurso=ultimo_id_nuevo,
        categoria_id=req.categoria_id,
        tags=tags_nuevos,
        tipo_plantilla=plantilla_nueva,
    )

    b.conforme = False
    b.conforme_en = None
    sesion.estado = EstadoFlujo.REVISION_BORRADOR

    if tenia_conformidad:
        b.conformidad_invalidada = True
        prefijo = f"{MSG_CONFORMIDAD_INVALIDADA}\n\n"
    else:
        prefijo = PREFIJO_BORRADOR_ACTUALIZADO

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_priv_edicion)


def _registrar_conformidad(sesion: SesionChat) -> ChatOrquestadorResponse:
    """Registra la conformidad del usuario aplicando sanitización silenciosa final si corresponde."""
    b = sesion.borrador
    if b is None:
        return construir_respuesta(sesion, MSG_RECHAZADO, OPCIONES_REINICIAR)

    b.metadatos_heredados_revisados = True
    sesion.metadatos_heredados_revisados = True

    if not sesion.validacion:
        validar_borrador(sesion)
    if not sesion.validacion or not sesion.validacion.valido:
        msg, ops = validar_borrador(sesion, PREFIJO_ERROR_CONFORMIDAD)
        return construir_respuesta(sesion, msg, ops)

    if b.modo == "enriquecimiento" and (
        b.texto_base_limpio or (sesion.coincidencias and sesion.coincidencias[0].texto_original)
    ):
        texto_base_limpio = (
            b.texto_base_limpio
            if b.texto_base_limpio
            else extraer_recursos_y_texto_limpio(sesion.coincidencias[0].texto_original.strip())[0]
        )
        txt_conf, aviso_priv_conf = consolidar_texto_enriquecimiento(texto_base_limpio, b.texto_limpio)
        limpio_tit = sanitizar_borrador(texto="", titulo=b.titulo)
        titulo_conf = limpio_tit["titulo_sanitizado"]
        texto_limpio_conf = txt_conf
        aviso_privacidad_final = aviso_priv_conf or limpio_tit.get("aviso_privacidad")
    else:
        limpio = sanitizar_borrador(texto=b.texto_limpio, titulo=b.titulo)
        titulo_conf = limpio["titulo_sanitizado"]
        texto_limpio_conf = limpio["texto_sanitizado"]
        aviso_privacidad_final = limpio.get("aviso_privacidad")

    sesion.actualizar_contenido_borrador(titulo=titulo_conf, texto_limpio=texto_limpio_conf)
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
        aviso_privacidad=aviso_privacidad_final,
    )


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

    # 1. Flujo de confirmación de rechazo
    resp_rechazo = _resolver_flujo_rechazo(sesion, opcion, hubo_cambios)
    if resp_rechazo is not None:
        return resp_rechazo

    # 2. Gestión de metadatos heredados de versión previa
    resp_meta = _gestionar_metadatos_heredados(sesion, opcion)
    if resp_meta is not None:
        return resp_meta

    # 3. Acción explícita o silenciosa de sanitización
    if opcion == "sanitizar":
        return _ejecutar_sanitizacion_borrador(sesion, req, tenia_conformidad)

    # 4. Mutaciones y edición de campos del borrador
    if hubo_cambios:
        return _aplicar_mutaciones_borrador(sesion, req, texto_edicion, tenia_conformidad)

    # 5. Opciones estándar del estado de revisión
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
            return construir_respuesta(sesion, MSG_VOLVER_ENRIQUECER_O_DESCARTAR, ops)
        sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
        return construir_respuesta(sesion, MSG_VOLVER_METADATOS, ["volver"])

    if opcion == "conforme":
        return _registrar_conformidad(sesion)

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
