from typing import List, Literal, Optional, Tuple
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


def normalizar_coincidencias(filas: list) -> List[CoincidenciaArticulo]:
    if not filas:
        return []
    f = filas[0]
    if isinstance(f, dict):
        return [CoincidenciaArticulo(id=int(f["id"]), titulo=str(f["titulo"]), url=str(f["url"]))]
    return [CoincidenciaArticulo(id=int(f[0]), titulo=str(f[1]), url=str(f[2]))]


def parsear_metadatos_mensaje(
    mensaje: Optional[str], tags_req: Optional[List[str]], cat_req: Optional[int]
) -> Tuple[List[str], Optional[int]]:
    nuevos_tags: List[str] = list(tags_req or [])
    cat_res = cat_req
    if not nuevos_tags and mensaje:
        for fragmento in mensaje.split(","):
            item = fragmento.strip()
            if not item:
                continue
            if item.isdigit() and cat_req is None:
                cat_res = int(item)
            else:
                nuevos_tags.append(item)
    return nuevos_tags, cat_res


def interpretar_opcion(req: ChatOrquestadorRequest) -> str:
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


def construir_respuesta(sesion: SesionChat, mensaje: str, opciones: List[str]) -> ChatOrquestadorResponse:
    return ChatOrquestadorResponse(
        session_id=sesion.session_id,
        estado=sesion.estado,
        mensaje=mensaje,
        opciones=opciones,
        coincidencias=sesion.coincidencias if sesion.estado in (EstadoFlujo.DECISION_TITULO, EstadoFlujo.DECISION_TEXTO) else [],
        borrador=sesion.borrador,
        validacion=sesion.validacion,
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

    detalle = "\n".join(f"- [{f['severity']}] {f['description']} ({f['action']})" for f in res["findings"])
    if not valido:
        return (
            f"{prefijo}El borrador tiene observaciones bloqueantes:\n{detalle}\nEditá el borrador o sanitizalo para poder aprobar.",
            OPCIONES_REVISION_BLOQUEANTE,
        )

    obs = f"\nSugerencias:\n{detalle}\n" if detalle else " "
    return (
        f"{prefijo}El borrador fue validado ({res['status']}).{obs}¿Confirmás aprobar o rechazar la publicación?",
        OPCIONES_REVISION_VALIDO,
    )


def avanzar_a_metadatos_o_revision(sesion: SesionChat, prefijo: str = "") -> ChatOrquestadorResponse:
    b = sesion.borrador
    plantilla = b.tipo_plantilla or extraer_tipo_plantilla(b.tags)
    if plantilla:
        b.tipo_plantilla = plantilla
        b.tags = combinar_tags(plantilla, b.tags)

    if not b.tipo_plantilla:
        sesion.estado = EstadoFlujo.ESPERANDO_PLANTILLA
        return construir_respuesta(sesion, msg_pedir_plantilla(prefijo), OPCIONES_PLANTILLAS)

    if len(b.tags) < 2:
        sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
        return construir_respuesta(sesion, msg_pedir_metadatos(b.tipo_plantilla, prefijo), [])

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops)
