from typing import Any, List, Literal, Optional, Tuple
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from baco.server.config_limites import (
    TEXTO_MAX,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)
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
from baco.server.services.validar_articulo import validar_texto_y_estructura_post_duplicados
from baco.server.services.orquestador.mensajes import (
    OPCIONES_PLANTILLAS,
    OPCIONES_REVISION_BLOQUEANTE,
    OPCIONES_REVISION_VALIDO,
    msg_error_longitud_maxima,
    msg_error_longitud_minima,
    msg_pedir_metadatos,
    msg_pedir_plantilla,
)
from baco.server.services.orquestador.sesion import SesionChat


def validar_longitud(texto: str, min_c: int, max_c: int, campo: str) -> Optional[str]:
    l = len(texto.strip())
    if l < min_c:
        return msg_error_longitud_minima(campo, min_c)
    if l > max_c:
        return msg_error_longitud_maxima(campo, max_c)
    return None


def validar_longitud_maxima(texto: str, max_c: int, campo: str) -> Optional[str]:
    if len(texto.strip()) > max_c:
        return msg_error_longitud_maxima(campo, max_c)
    return None


def actualizar_metadatos_sesion(sesion: SesionChat, req: ChatOrquestadorRequest) -> None:
    if req.categoria_id is not None:
        sesion.categoria_id = req.categoria_id
    if req.tags is not None:
        sesion.tags = req.tags


async def cargar_datos_articulo(
    buscador: BuscadorDuplicados, articulo_id: int
) -> Tuple[str, Optional[int], List[str]]:
    if not hasattr(buscador, "obtener_articulo"):
        return "", None, []
    art_db = await run_in_threadpool(buscador.obtener_articulo, articulo_id)
    if isinstance(art_db, dict):
        tags_db = [str(t).strip() for t in (art_db.get("tags") or []) if str(t).strip()]
        return (art_db.get("texto") or "").strip(), art_db.get("categoria_id"), tags_db
    return "", None, []


def extraer_tipo_plantilla(tags: List[str], texto_opcion: str = "") -> Optional[Literal["instructivo", "soluciones"]]:
    candidatos = [texto_opcion.strip().lower()] + [t.strip().lower() for t in (tags or [])]
    for c in candidatos:
        if c in ("instructivo", "instructivos"):
            return "instructivo"
        if c in ("soluciones", "solucion", "solución"):
            return "soluciones"
    return None


def combinar_tags(plantilla: Optional[str], *listas_tags: List[str]) -> List[str]:
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


def extraer_score(fila: Any, mensaje: str = "") -> Optional[float]:
    if isinstance(fila, dict):
        for k in ("score_total", "score", "similarity", "sim_texto"):
            if k in fila and fila[k] is not None:
                try:
                    return round(float(fila[k]), 3)
                except (ValueError, TypeError):
                    pass

    if isinstance(fila, (list, tuple)):
        if len(fila) >= 6:
            try:
                val = float(fila[5])
                if 0.0 <= val <= 1.0:
                    return round(val, 3)
            except (ValueError, TypeError):
                pass
        if len(fila) == 4 and isinstance(fila[3], str):
            return 0.850
        if len(fila) > 3:
            try:
                val = float(fila[-1])
                if 0.0 <= val <= 1.0:
                    return round(val, 3)
            except (ValueError, TypeError):
                pass

    if "exactamente" in (mensaje or "").lower():
        return 1.0
    return None


def normalizar_coincidencias(
    filas: list, mensaje: str = "", texto_original: Optional[str] = None
) -> List[CoincidenciaArticulo]:
    if not filas:
        return []
    f = filas[0]
    score = extraer_score(f, mensaje)
    if isinstance(f, dict):
        return [
            CoincidenciaArticulo(
                id=int(f["id"]),
                titulo=str(f["titulo"]),
                url=str(f["url"]),
                score=score,
                texto_original=texto_original or f.get("texto"),
            )
        ]
    return [
        CoincidenciaArticulo(
            id=int(f[0]),
            titulo=str(f[1]),
            url=str(f[2]),
            score=score,
            texto_original=texto_original,
        )
    ]


def parsear_metadatos_mensaje(
    mensaje: Optional[str],
    tags_req: Optional[List[str]],
    cat_req: Optional[int],
    texto_fallback: Optional[str] = None,
) -> Tuple[List[str], Optional[int]]:
    nuevos_tags: List[str] = list(tags_req or [])
    cat_res = cat_req
    cadena = (mensaje or texto_fallback or "").strip()
    if not nuevos_tags and cadena:
        for fragmento in cadena.split(","):
            item = fragmento.strip()
            if not item:
                continue
            if item.isdigit() and cat_res is None:
                cat_res = int(item)
            else:
                nuevos_tags.append(item)
    elif cadena and cat_res is None:
        for fragmento in cadena.split(","):
            item = fragmento.strip()
            if item.isdigit() and cat_res is None:
                cat_res = int(item)
                break
    return nuevos_tags, cat_res


def interpretar_opcion(req: ChatOrquestadorRequest) -> str:
    bruto = (req.accion or req.mensaje or "").strip().lower()
    mapa = {
        "si": "enriquecer", "sí": "enriquecer", "1": "enriquecer", "enriquecer": "enriquecer",
        "no": "descartar", "2": "descartar", "descartar": "descartar", "continuar": "continuar",
        "aprobar": "aprobar", "apruebo": "aprobar", "confirmar": "aprobar", "confirmado": "aprobar", "omitir": "aprobar",
        "rechazar": "rechazar", "rechazo": "rechazar", "cancelar": "rechazar",
        "sanitizar": "sanitizar", "editar": "editar", "corregir": "editar", "enviar_correccion": "editar", "correccion": "editar",
        "reiniciar": "reiniciar", "cambiar tema": "reiniciar", "cambiar de tema": "reiniciar",
        "instructivo": "instructivo", "instructivos": "instructivo",
        "soluciones": "soluciones", "solucion": "soluciones", "solución": "soluciones",
    }
    return mapa.get(bruto, bruto)


def construir_respuesta(
    sesion: SesionChat,
    mensaje: str,
    opciones: List[str],
    aviso_privacidad: Optional[str] = None,
) -> ChatOrquestadorResponse:
    return ChatOrquestadorResponse(
        session_id=sesion.session_id,
        estado=sesion.estado,
        mensaje=mensaje,
        opciones=opciones,
        coincidencias=sesion.coincidencias if sesion.estado in (EstadoFlujo.DECISION_TITULO, EstadoFlujo.DECISION_TEXTO) else [],
        borrador=sesion.borrador,
        validacion=sesion.validacion,
        aviso_privacidad=aviso_privacidad,
    )


def validar_borrador(sesion: SesionChat, prefijo: str = "") -> Tuple[str, List[str]]:
    b = sesion.borrador
    try:
        articulo = ArticuloSchema(
            id=b.articulo_original_id or 0,
            titulo=b.titulo,
            texto=b.texto,
            categoria_id=b.categoria_id,
            tags=[Tag(name=t) for t in b.tags],
            url=b.articulo_original_url,
        )
    except ValidationError as e:
        findings = [
            {
                "severity": "Bloqueante",
                "field": ".".join(map(str, err["loc"])),
                "description": err["msg"],
                "action": "Corregir el campo para cumplir con los requisitos del artículo.",
            }
            for err in e.errors()
        ]
        sesion.validacion = ValidarFormatoResponse(
            valido=False,
            status="Pendiente",
            findings=findings,
            resumen={"longitud_texto": len(b.texto or ""), "tags_count": len(b.tags or [])},
        )
        sesion.estado = EstadoFlujo.REVISION_BORRADOR
        detalle = "\n".join(f"- [{f['severity']}] {f['field']}: {f['description']}" for f in findings)
        return (
            f"{prefijo}El borrador tiene observaciones bloqueantes:\n{detalle}\nEditá el borrador o sanitizalo para poder aprobar.",
            OPCIONES_REVISION_BLOQUEANTE,
        )

    res = validar_texto_y_estructura_post_duplicados(articulo)
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

    bloqueantes = [f for f in res.get("findings", []) if f.get("severity") == "Bloqueante"]
    ajustes = [f for f in res.get("findings", []) if f.get("severity") == "Requiere ajuste"]
    sugerencias = [f for f in res.get("findings", []) if f.get("severity") == "Sugerencia"]

    if not valido:
        detalle = "\n".join(f"- [{f['severity']}] {f['description']} ({f['action']})" for f in bloqueantes)
        return (
            f"{prefijo}El borrador tiene observaciones bloqueantes:\n{detalle}\nEditá el borrador o sanitizalo para poder aprobar.",
            OPCIONES_REVISION_BLOQUEANTE,
        )

    if ajustes:
        detalle = "\n".join(f"- [{f['severity']}] {f['description']} ({f['action']})" for f in ajustes)
        return (
            f"{prefijo}El borrador supera los requisitos técnicos mínimos pero presenta {len(ajustes)} observación(es) "
            f"editoriales que requieren ajuste humano:\n{detalle}\n"
            "Podés enviar la corrección correspondiente o confirmar para aprobarlo tal cual está.",
            OPCIONES_REVISION_VALIDO,
        )

    obs = "\n".join(f"- [{f['severity']}] {f['description']} ({f['action']})" for f in sugerencias)
    detalle_sug = f"\nSugerencias:\n{obs}\n" if obs else " "
    return (
        f"{prefijo}El borrador fue validado ({res['status']}).{detalle_sug}¿Confirmás aprobar o rechazar la publicación?",
        OPCIONES_REVISION_VALIDO,
    )


def avanzar_a_metadatos_o_revision(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if b.categoria_id is None:
        b.categoria_id = sesion.categoria_id or 1

    plantilla = b.tipo_plantilla or extraer_tipo_plantilla(b.tags)
    if plantilla:
        b.tipo_plantilla = plantilla
        b.tags = combinar_tags(plantilla, b.tags)

    if not b.tipo_plantilla:
        sesion.estado = EstadoFlujo.ESPERANDO_PLANTILLA
        return construir_respuesta(
            sesion, msg_pedir_plantilla(prefijo), OPCIONES_PLANTILLAS, aviso_privacidad=aviso_privacidad
        )

    if len(b.tags) < 2:
        sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
        return construir_respuesta(
            sesion, msg_pedir_metadatos(b.tipo_plantilla, prefijo), [], aviso_privacidad=aviso_privacidad
        )

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_privacidad)
