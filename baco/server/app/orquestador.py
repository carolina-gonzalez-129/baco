from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional
import uuid
from starlette.concurrency import run_in_threadpool
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    CoincidenciaArticulo,
    EstadoFlujo,
)
from baco.server.schemas.validacion import ValidarFormatoResponse
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.validar_articulo import (
    sanitizar_borrador,
    validar_texto_y_estructura_post_duplicados,
)

MENSAJE_BIENVENIDA = (
    "Hola, soy Baco, agente encargado en asistirte en la carga de documentación "
    "a la base de conocimiento de Finnegans. ¿Sobre qué te gustaría publicar?"
)

TTL_SESION = timedelta(minutes=30)
SESIONES: dict[str, "SesionChat"] = {}


@dataclass
class SesionChat:
    session_id: str
    estado: EstadoFlujo = EstadoFlujo.ESPERANDO_TITULO
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    titulo: str = ""
    texto: str = ""
    categoria_id: int = 1
    tags: List[str] = field(default_factory=list)
    coincidencias: List[CoincidenciaArticulo] = field(default_factory=list)
    borrador: Optional[BorradorSesion] = None
    validacion: Optional[ValidarFormatoResponse] = None


def _limpiar_sesiones_expiradas(ahora: datetime) -> None:
    expiradas = [sid for sid, s in SESIONES.items() if (ahora - s.updated_at) > TTL_SESION]
    for sid in expiradas:
        SESIONES.pop(sid, None)


def _obtener_sesion(session_id: Optional[str]) -> tuple[SesionChat, bool]:
    ahora = datetime.now(timezone.utc)
    _limpiar_sesiones_expiradas(ahora)

    if session_id and session_id in SESIONES:
        sesion = SESIONES[session_id]
        sesion.updated_at = ahora
        return sesion, False

    sid = session_id or str(uuid.uuid4())
    nueva = SesionChat(session_id=sid, updated_at=ahora)
    SESIONES[sid] = nueva
    return nueva, True


def obtener_borrador_aprobado(session_id: Optional[str]) -> Optional[BorradorSesion]:
    ahora = datetime.now(timezone.utc)
    _limpiar_sesiones_expiradas(ahora)

    if not session_id or session_id not in SESIONES:
        return None

    sesion = SESIONES[session_id]
    if sesion.estado != EstadoFlujo.APROBADO or sesion.borrador is None:
        return None

    sesion.updated_at = ahora
    limpio = sanitizar_borrador(texto=sesion.borrador.texto, titulo=sesion.borrador.titulo)
    sesion.borrador.titulo = limpio["titulo_sanitizado"]
    sesion.borrador.texto = limpio["texto_sanitizado"]
    return sesion.borrador.model_copy(deep=True)


async def _cargar_datos_articulo(
    buscador: BuscadorDuplicados, articulo_id: int
) -> tuple[str, Optional[int], List[str]]:
    if not hasattr(buscador, "obtener_articulo"):
        return "", None, []
    art_db = await run_in_threadpool(buscador.obtener_articulo, articulo_id)
    if isinstance(art_db, dict):
        tags_db = [str(t).strip() for t in (art_db.get("tags") or []) if str(t).strip()]
        return (art_db.get("texto") or "").strip(), art_db.get("categoria_id"), tags_db
    return "", None, []


def _extraer_tipo_plantilla(tags: List[str], texto_opcion: str = "") -> Optional[Literal["instructivo", "soluciones"]]:
    candidatos = [texto_opcion.strip().lower()] + [t.strip().lower() for t in (tags or [])]
    for c in candidatos:
        if c in ("instructivo", "instructivos"):
            return "instructivo"
        if c in ("soluciones", "solucion", "solución"):
            return "soluciones"
    return None


def _combinar_tags(plantilla: Optional[str], *listas_tags: List[str]) -> List[str]:
    resultado: List[str] = []
    vistos: set[str] = set()
    if plantilla:
        resultado.append(plantilla)
        vistos.add(plantilla.lower())
    for lista in listas_tags:
        for t in (lista or []):
            limpio = t.strip()
            if not limpio:
                continue
            clave = limpio.lower()
            if clave in ("instructivos", "instructivo") and plantilla == "instructivo":
                continue
            if clave in ("soluciones", "solucion", "solución") and plantilla == "soluciones":
                continue
            if clave not in vistos:
                vistos.add(clave)
                resultado.append(limpio)
    return resultado


def _normalizar_coincidencias(filas: list) -> List[CoincidenciaArticulo]:
    if not filas:
        return []
    f = filas[0]
    if isinstance(f, dict):
        return [CoincidenciaArticulo(id=int(f["id"]), titulo=str(f["titulo"]), url=str(f["url"]))]
    return [CoincidenciaArticulo(id=int(f[0]), titulo=str(f[1]), url=str(f[2]))]


def _validar_borrador(sesion: SesionChat, prefijo: str = "") -> tuple[str, List[str]]:
    b = sesion.borrador
    res = validar_texto_y_estructura_post_duplicados(
        ArticuloSchema(
            id=b.articulo_original_id or 0,
            titulo=b.titulo,
            texto=b.texto,
            categoria_id=b.categoria_id,
            tags=[Tag(name=t) for t in b.tags],
            url=b.articulo_original_url,
        )
    )
    valido = res["status"] != "Pendiente"
    sesion.validacion = ValidarFormatoResponse(
        valido=valido,
        status=res["status"],
        titulo_sanitizado=res.get("titulo_sanitizado"),
        texto_sanitizado=res.get("texto_sanitizado"),
        findings=res.get("findings", []),
        resumen={"longitud_texto": res["longitud_texto"], "tags_count": res["tags_count"]},
    )
    sesion.estado = EstadoFlujo.REVISION_BORRADOR

    detalle = "\n".join(f"- [{f['severity']}] {f['description']} ({f['action']})" for f in res["findings"])
    if not valido:
        msg = f"{prefijo}El borrador tiene observaciones bloqueantes:\n{detalle}\nEditá el borrador o sanitizalo para poder aprobar."
        return msg, ["editar", "sanitizar", "rechazar", "reiniciar"]

    obs = f"\nSugerencias:\n{detalle}\n" if detalle else " "
    msg = f"{prefijo}El borrador fue validado ({res['status']}).{obs}¿Confirmás aprobar o rechazar la publicación?"
    return msg, ["aprobar", "editar", "sanitizar", "rechazar", "reiniciar"]


def _avanzar_a_metadatos_o_revision(sesion: SesionChat, prefijo: str = "") -> ChatOrquestadorResponse:
    b = sesion.borrador
    plantilla = b.tipo_plantilla or _extraer_tipo_plantilla(b.tags)
    if plantilla:
        b.tipo_plantilla = plantilla
        b.tags = _combinar_tags(plantilla, b.tags)

    if not b.tipo_plantilla:
        sesion.estado = EstadoFlujo.ESPERANDO_PLANTILLA
        return _respuesta(
            sesion,
            f"{prefijo}¿Qué tipo de plantilla corresponde aplicar a este artículo: 'instructivo' o 'soluciones'?",
            ["instructivo", "soluciones"],
        )

    if len(b.tags) < 2:
        sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
        return _respuesta(
            sesion,
            f"{prefijo}Plantilla '{b.tipo_plantilla}' seleccionada. Ingresá al menos un tag temático adicional (ej. 'ventas', 'facturacion', separados por coma si son varios) y opcionalmente el ID de categoría.",
            [],
        )

    msg, ops = _validar_borrador(sesion, prefijo)
    return _respuesta(sesion, msg, ops)


def _interpretar_opcion(req: ChatOrquestadorRequest) -> str:
    bruto = (req.accion or req.mensaje or "").strip().lower()
    mapa = {
        "si": "enriquecer", "sí": "enriquecer", "1": "enriquecer", "enriquecer": "enriquecer",
        "no": "descartar", "2": "descartar", "descartar": "descartar", "continuar": "continuar",
        "aprobar": "aprobar", "apruebo": "aprobar",
        "rechazar": "rechazar", "rechazo": "rechazar", "cancelar": "rechazar",
        "sanitizar": "sanitizar", "editar": "editar",
        "reiniciar": "reiniciar", "cambiar tema": "reiniciar", "cambiar de tema": "reiniciar",
        "instructivo": "instructivo", "instructivos": "instructivo",
        "soluciones": "soluciones", "solucion": "soluciones", "solución": "soluciones",
    }
    return mapa.get(bruto, bruto)


def _respuesta(sesion: SesionChat, mensaje: str, opciones: List[str]) -> ChatOrquestadorResponse:
    return ChatOrquestadorResponse(
        session_id=sesion.session_id,
        estado=sesion.estado,
        mensaje=mensaje,
        opciones=opciones,
        coincidencias=sesion.coincidencias if sesion.estado in (EstadoFlujo.DECISION_TITULO, EstadoFlujo.DECISION_TEXTO) else [],
        borrador=sesion.borrador,
        validacion=sesion.validacion,
    )


async def manejar_turno(req: ChatOrquestadorRequest, buscador: BuscadorDuplicados) -> ChatOrquestadorResponse:
    sesion, es_nueva = _obtener_sesion(req.session_id)
    opcion = _interpretar_opcion(req)

    if opcion == "reiniciar":
        SESIONES.pop(sesion.session_id, None)
        sesion, _ = _obtener_sesion(sesion.session_id)
        return _respuesta(sesion, MENSAJE_BIENVENIDA, [])

    # Paso 1: Mensaje de bienvenida si recién inicia y no envió título aún
    entrada_titulo = (req.titulo or req.mensaje or "").strip()
    if es_nueva and not entrada_titulo and not req.accion:
        return _respuesta(sesion, MENSAJE_BIENVENIDA, [])

    # Paso 2 y 3: ESPERANDO_TITULO -> buscar_duplicados solo con el título (mejor coincidencia única)
    if sesion.estado == EstadoFlujo.ESPERANDO_TITULO:
        if len(entrada_titulo) < 10:
            return _respuesta(sesion, "Por favor, ingresá un título descriptivo de al menos 10 caracteres.", [])

        sesion.titulo = entrada_titulo
        if req.categoria_id is not None:
            sesion.categoria_id = req.categoria_id
        if req.tags is not None:
            sesion.tags = req.tags

        res_tit = await run_in_threadpool(buscador.evaluar_titulo, entrada_titulo, 1)
        if res_tit and res_tit.get("coincidencias"):
            sesion.coincidencias = _normalizar_coincidencias(res_tit["coincidencias"])
            sesion.estado = EstadoFlujo.DECISION_TITULO
            primero = sesion.coincidencias[0]
            msg = f"{res_tit['mensaje']} ({primero.titulo} - {primero.url})"
            return _respuesta(sesion, msg, ["enriquecer", "descartar"])

        sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
        return _respuesta(sesion, "No encontré coincidencias por título. Ingresá el texto del artículo.", [])

    # Paso 4a: DECISION_TITULO -> enriquecer o descartar
    if sesion.estado == EstadoFlujo.DECISION_TITULO:
        if opcion == "enriquecer":
            elegido = sesion.coincidencias[0]
            texto_db, cat_db, tags_db = await _cargar_datos_articulo(buscador, elegido.id)
            texto_inicial = (req.texto or texto_db or sesion.texto).strip()
            tags_iniciales = req.tags if req.tags is not None else (tags_db or sesion.tags)
            sesion.borrador = BorradorSesion(
                modo="enriquecimiento",
                articulo_original_id=elegido.id,
                articulo_original_url=elegido.url,
                titulo=elegido.titulo,
                texto=texto_inicial,
                tipo_plantilla=_extraer_tipo_plantilla(tags_iniciales),
                categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
                tags=tags_iniciales,
            )
            if not texto_inicial:
                sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
                return _respuesta(
                    sesion,
                    f"Seleccionaste enriquecer el artículo #{elegido.id}. Ingresá el texto del borrador.",
                    [],
                )
            return _avanzar_a_metadatos_o_revision(sesion, f"Borrador de sesión creado sobre #{elegido.id}. ")

        if opcion in ("descartar", "continuar"):
            sesion.estado = EstadoFlujo.ESPERANDO_TEXTO
            return _respuesta(sesion, "Descartamos la coincidencia por título. Ingresá el texto del artículo.", [])

        return _respuesta(sesion, "Elegí 'enriquecer' el artículo existente o 'descartar' para ingresar tu texto.", ["enriquecer", "descartar"])

    # Paso 4b: ESPERANDO_TEXTO -> si ya eligió enriquecer, no deduplica texto; si no, buscar_duplicados con el texto
    if sesion.estado == EstadoFlujo.ESPERANDO_TEXTO:
        texto_in = (req.texto or req.mensaje or "").strip()
        if not texto_in:
            return _respuesta(sesion, "El texto no puede estar vacío. Ingresá el contenido del artículo.", [])

        sesion.texto = texto_in
        if req.categoria_id is not None:
            sesion.categoria_id = req.categoria_id
        if req.tags is not None:
            sesion.tags = req.tags

        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            sesion.borrador.texto = texto_in
            if req.categoria_id is not None:
                sesion.borrador.categoria_id = req.categoria_id
            if req.tags is not None:
                sesion.borrador.tags = req.tags
            return _avanzar_a_metadatos_o_revision(
                sesion, f"Borrador de sesión creado sobre #{sesion.borrador.articulo_original_id}. "
            )

        res_txt = await run_in_threadpool(buscador.evaluar_texto, texto_in, True, sesion.titulo, 1)
        if res_txt and res_txt.get("coincidencias"):
            sesion.coincidencias = _normalizar_coincidencias(res_txt["coincidencias"])
            sesion.estado = EstadoFlujo.DECISION_TEXTO
            primero = sesion.coincidencias[0]
            msg = f"{res_txt['mensaje']} ({primero.titulo} - {primero.url})"
            return _respuesta(sesion, msg, ["enriquecer", "continuar"])

        sesion.borrador = BorradorSesion(
            modo="nuevo",
            titulo=sesion.titulo,
            texto=sesion.texto,
            tipo_plantilla=_extraer_tipo_plantilla(sesion.tags),
            categoria_id=sesion.categoria_id,
            tags=list(sesion.tags),
        )
        return _avanzar_a_metadatos_o_revision(sesion, "Sin duplicados en el contenido. ")

    # Paso 4c: DECISION_TEXTO -> enriquecer o rechazar ambas opciones y continuar con su texto
    if sesion.estado == EstadoFlujo.DECISION_TEXTO:
        if req.categoria_id is not None:
            sesion.categoria_id = req.categoria_id
        if req.tags is not None:
            sesion.tags = req.tags

        if opcion == "enriquecer":
            elegido = sesion.coincidencias[0]
            texto_db, cat_db, tags_db = await _cargar_datos_articulo(buscador, elegido.id)
            texto_enriquecido = (req.texto or texto_db or sesion.texto).strip()
            tags_iniciales = req.tags if req.tags is not None else (tags_db or sesion.tags)
            sesion.borrador = BorradorSesion(
                modo="enriquecimiento",
                articulo_original_id=elegido.id,
                articulo_original_url=elegido.url,
                titulo=elegido.titulo,
                texto=texto_enriquecido,
                tipo_plantilla=_extraer_tipo_plantilla(tags_iniciales),
                categoria_id=req.categoria_id or cat_db or sesion.categoria_id,
                tags=tags_iniciales,
            )
            return _avanzar_a_metadatos_o_revision(
                sesion, f"Borrador de enriquecimiento creado sobre #{elegido.id}. "
            )

        if opcion in ("continuar", "descartar"):
            sesion.borrador = BorradorSesion(
                modo="nuevo",
                titulo=sesion.titulo,
                texto=sesion.texto,
                tipo_plantilla=_extraer_tipo_plantilla(sesion.tags),
                categoria_id=sesion.categoria_id,
                tags=list(sesion.tags),
            )
            return _avanzar_a_metadatos_o_revision(sesion, "Continuamos con tu propio texto. ")

        return _respuesta(sesion, "Elegí 'enriquecer' el artículo hallado o 'continuar' con tu propio texto.", ["enriquecer", "continuar"])

    # Paso 4d (Variante C1 - Parte A): ESPERANDO_PLANTILLA -> elegir 'instructivo' o 'soluciones'
    if sesion.estado == EstadoFlujo.ESPERANDO_PLANTILLA:
        b = sesion.borrador
        if req.categoria_id is not None:
            b.categoria_id = req.categoria_id
        plantilla = _extraer_tipo_plantilla(req.tags or [], opcion)
        if not plantilla:
            return _respuesta(
                sesion,
                "Por favor, elegí el tipo de plantilla aplicable: 'instructivo' o 'soluciones'.",
                ["instructivo", "soluciones"],
            )
        b.tipo_plantilla = plantilla
        b.tags = _combinar_tags(plantilla, b.tags, req.tags or [])
        return _avanzar_a_metadatos_o_revision(sesion)

    # Paso 4e (Variante C1 - Parte B): ESPERANDO_METADATOS -> ingresar tags temáticos adicionales (y opcionalmente categoría)
    if sesion.estado == EstadoFlujo.ESPERANDO_METADATOS:
        b = sesion.borrador
        if req.categoria_id is not None:
            b.categoria_id = req.categoria_id

        nuevos_tags: List[str] = list(req.tags or [])
        if not nuevos_tags and req.mensaje:
            for fragmento in req.mensaje.split(","):
                item = fragmento.strip()
                if not item:
                    continue
                if item.isdigit() and req.categoria_id is None:
                    b.categoria_id = int(item)
                else:
                    nuevos_tags.append(item)

        b.tags = _combinar_tags(b.tipo_plantilla, b.tags, nuevos_tags)
        if len(b.tags) < 2:
            return _respuesta(
                sesion,
                f"Ingresá al menos un tag temático adicional además de '{b.tipo_plantilla}' (ej. 'ventas', 'facturacion').",
                [],
            )

        msg, ops = _validar_borrador(sesion, "Metadatos registrados. ")
        return _respuesta(sesion, msg, ops)

    # Paso 5: REVISION_BORRADOR -> editar/sanitizar (re-valida) o revisión humana final (aprobar/rechazar)
    if sesion.estado == EstadoFlujo.REVISION_BORRADOR:
        b = sesion.borrador
        texto_edicion = req.texto
        if texto_edicion is None and opcion == "editar" and req.mensaje and req.mensaje.strip().lower() != "editar":
            texto_edicion = req.mensaje

        hubo_cambios = any(v is not None for v in (req.titulo, texto_edicion, req.categoria_id, req.tags))

        if opcion == "sanitizar":
            limpio = sanitizar_borrador(texto=req.texto or b.texto, titulo=req.titulo or b.titulo)
            b.titulo = limpio["titulo_sanitizado"]
            b.texto = limpio["texto_sanitizado"]
            msg, ops = _validar_borrador(sesion, "Datos sensibles sanitizados. ")
            return _respuesta(sesion, msg, ops)

        if hubo_cambios:
            if req.titulo is not None:
                b.titulo = req.titulo.strip()
            if texto_edicion is not None:
                b.texto = texto_edicion.strip()
            if req.categoria_id is not None:
                b.categoria_id = req.categoria_id
            if req.tags is not None:
                plantilla_nueva = _extraer_tipo_plantilla(req.tags) or b.tipo_plantilla
                b.tipo_plantilla = plantilla_nueva
                b.tags = _combinar_tags(plantilla_nueva, req.tags)
            msg, ops = _validar_borrador(sesion, "Borrador actualizado. ")
            return _respuesta(sesion, msg, ops)

        if opcion == "editar":
            ops = (
                ["aprobar", "editar", "sanitizar", "rechazar", "reiniciar"]
                if (sesion.validacion and sesion.validacion.valido)
                else ["editar", "sanitizar", "rechazar", "reiniciar"]
            )
            return _respuesta(
                sesion,
                "Enviá los campos que quieras modificar (titulo, texto, categoria_id o tags) para actualizar y re-validar el borrador.",
                ops,
            )

        if opcion == "aprobar":
            if not sesion.validacion or not sesion.validacion.valido:
                msg, ops = _validar_borrador(sesion, "No se puede aprobar mientras existan errores bloqueantes. ")
                return _respuesta(sesion, msg, ops)
            limpio = sanitizar_borrador(texto=b.texto, titulo=b.titulo)
            b.titulo = limpio["titulo_sanitizado"]
            b.texto = limpio["texto_sanitizado"]
            sesion.estado = EstadoFlujo.APROBADO
            return _respuesta(sesion, f"Artículo '{b.titulo}' aprobado para publicación.", ["reiniciar"])

        if opcion == "rechazar":
            sesion.estado = EstadoFlujo.RECHAZADO
            return _respuesta(sesion, "Borrador rechazado. No se realizaron cambios.", ["reiniciar"])

        msg, ops = _validar_borrador(sesion)
        return _respuesta(sesion, msg, ops)

    return _respuesta(sesion, f"La sesión ya finalizó en estado {sesion.estado.value}. Enviá 'reiniciar' para comenzar otra carga.", ["reiniciar"])
