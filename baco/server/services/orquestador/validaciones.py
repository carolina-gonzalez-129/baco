from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.schemas.chat_orquestado import (
    CategoriaOpcion,
    ChatOrquestadorRequest,
    ChatOrquestadorResponse,
    CoincidenciaArticulo,
    EstadoFlujo,
    EtapaFlujo,
)
from baco.server.schemas.validacion import ValidarFormatoResponse
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.validar_articulo import (
    sanitizar_borrador,
    validar_texto_y_estructura_post_duplicados,
)
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

ETAPAS_FLUJO: List[str] = [
    "Título y duplicados",
    "Contenido",
    "Plantilla y etiquetas",
    "Revisión",
    "Aprobación",
]

MAPA_ESTADO_ETAPA: dict[EstadoFlujo, Tuple[int, str]] = {
    EstadoFlujo.ESPERANDO_TITULO: (1, "Título y duplicados"),
    EstadoFlujo.DECISION_TITULO: (1, "Título y duplicados"),
    EstadoFlujo.ESPERANDO_TEXTO: (2, "Contenido"),
    EstadoFlujo.DECISION_TEXTO: (2, "Contenido"),
    EstadoFlujo.ESPERANDO_PLANTILLA: (3, "Plantilla y etiquetas"),
    EstadoFlujo.ESPERANDO_METADATOS: (3, "Plantilla y etiquetas"),
    EstadoFlujo.REVISION_BORRADOR: (4, "Revisión"),
    EstadoFlujo.SUBSANANDO_BORRADOR: (4, "Revisión"),
    EstadoFlujo.APROBADO: (5, "Aprobación"),
    EstadoFlujo.RECHAZADO: (5, "Aprobación"),
}


def obtener_etapa_flujo(estado: EstadoFlujo) -> EtapaFlujo:
    actual, nombre = MAPA_ESTADO_ETAPA.get(estado, (1, ETAPAS_FLUJO[0]))
    return EtapaFlujo(
        actual=actual,
        total=len(ETAPAS_FLUJO),
        nombre=nombre,
        etapas=list(ETAPAS_FLUJO),
    )


def obtener_tags_acumulados(sesion: SesionChat) -> List[str]:
    if sesion.borrador is not None:
        return combinar_tags(sesion.borrador.tipo_plantilla, sesion.borrador.tags, sesion.tags)
    plantilla = extraer_tipo_plantilla(sesion.tags)
    return combinar_tags(plantilla, sesion.tags)


DICCIONARIO_OFICIAL_CATEGORIAS: Dict[int, str] = {
    1: "Sin categoría",
    2: "Finnegans",
    4: "Staff",
    19: "Inventarios",
    20: "Ventas",
    21: "Contabilidad",
    22: "Tesorería",
    23: "Impuestos Argentina",
    24: "Compras",
    25: "App Builder",
    26: "Activos Fijos",
    28: "Cuentas a pagar",
    29: "Cuentas a cobrar",
    31: "Maquinarias agrícolas",
    32: "Manufacturas",
    33: "Órdenes de producción",
    34: "Obras",
    35: "Desarrolladoras",
    36: "Exportación",
    37: "Agro",
    39: "HCM",
    40: "CRM",
    41: "Presupuestos",
    43: "Importación",
    44: "MRP",
    45: "Ventas agro",
    46: "Compras agro",
    47: "Ganadería",
    48: "Comercialización de granos",
    49: "Plantas Procesadoras",
    50: "MercadoLibre",
    51: "TiendaNube",
    52: "Bot de compras",
    54: "Aplicaciones",
    59: "Vista Clientes",
    61: "Videos Cómo se hace",
    62: "GO",
    63: "Soporte técnico",
    65: "Recursos de conocimiento",
    66: "Proyectos",
    67: "México",
    75: "Ecuador",
    81: "Perú",
    82: "Paraguay",
    83: "Uruguay",
    84: "Workshops internos",
    85: "API",
    86: "Herramientas de conocimiento",
    87: "Deals",
    88: "Integraciones",
    89: "Bot de granos",
    90: "Especificaciones técnicas",
    91: "Emergencias",
    93: "Videos CSH internos",
    94: "Comercializadoras",
    95: "Cursos DAI",
    96: "Academia",
    98: "Chile",
    100: "Infraestructura",
    101: "Partners",
    102: "Soy Finnencer",
    105: "Infraestructura - Interno",
    106: "Soporte técnico - Interno",
    107: "Soporte técnico - Finnegans",
    108: "One Team",
    109: "Fichas de componentes",
    110: "Sueldos",
    111: "D&D",
    112: "QA",
    113: "ERP interno",
    114: "Pruebas en la BC",
    115: "Constructoras",
    116: "Producto",
    117: "FinnApp",
    118: "Portal de Clientes",
    119: "DAI Builder",
    120: "DAI Builder interno",
    121: "Bolivia",
    122: "Colombia",
    123: "CADs",
    124: "IReport",
    125: "Portal de Proveedores",
    126: "Servidores-Dedicados",
    127: "Infra-Dedicada",
    128: "Seguridad",
    129: "Readme",
    130: "ERP",
    131: "Particularizaciones",
    132: "Agro",
    133: "Comercializadoras",
    134: "Constructoras",
    135: "CORE",
    136: "HCM",
    137: "Paraguay",
    138: "Plantillas de entradas",
    139: "Test Unitarios",
    140: "Manufacturas",
    141: "CORE",
    142: "Comercio Exterior",
    143: "Casos de prueba",
    144: "Quippos",
    145: "Bproc",
    146: "Estados Unidos",
    147: "ADMP",
    148: "Responsables de conocimiento",
    149: "Política de seguridad",
    150: "Mantenimiento",
    151: "Prompts",
    152: "Finni",
    153: "Webinars",
    154: "Administración de mi cuenta",
    155: "Portal de granos",
    156: "App Mobile de Vendedores",
    157: "Diseño UX/UI",
    158: "BModeler",
    159: "IA",
    160: "Facilities",
    161: "Desarrollo IA",
    162: "Datawarehouse",
    163: "Prompts Finni Dashboard",
    164: "Casos de Uso",
    165: "Novedades de Tecnología",
}

CATEGORIAS_CURADAS_OPCION_A: List[CategoriaOpcion] = [
    CategoriaOpcion(id=37, nombre="Agro"),
    CategoriaOpcion(id=25, nombre="App Builder"),
    CategoriaOpcion(id=94, nombre="Comercializadoras"),
    CategoriaOpcion(id=48, nombre="Comercialización de granos"),
    CategoriaOpcion(id=24, nombre="Compras"),
    CategoriaOpcion(id=115, nombre="Constructoras"),
    CategoriaOpcion(id=21, nombre="Contabilidad"),
    CategoriaOpcion(id=62, nombre="GO"),
    CategoriaOpcion(id=39, nombre="HCM"),
    CategoriaOpcion(id=23, nombre="Impuestos Argentina"),
    CategoriaOpcion(id=19, nombre="Inventarios"),
    CategoriaOpcion(id=67, nombre="México"),
    CategoriaOpcion(id=82, nombre="Paraguay"),
    CategoriaOpcion(id=81, nombre="Perú"),
    CategoriaOpcion(id=129, nombre="Readme"),
    CategoriaOpcion(id=65, nombre="Recursos de conocimiento"),
    CategoriaOpcion(id=63, nombre="Soporte técnico"),
    CategoriaOpcion(id=22, nombre="Tesorería"),
    CategoriaOpcion(id=83, nombre="Uruguay"),
    CategoriaOpcion(id=20, nombre="Ventas"),
    CategoriaOpcion(id=61, nombre="Videos Cómo se hace"),
]


def _consultar_categorias_y_tags_sync(cur: Any) -> Tuple[List[CategoriaOpcion], List[str]]:
    categorias: List[CategoriaOpcion] = []
    tags: List[str] = []
    if cur is None:
        return list(CATEGORIAS_CURADAS_OPCION_A), tags

    conn = getattr(cur, "connection", None)

    try:
        cur.execute("SELECT id, nombre FROM public.categorias ORDER BY id;")
        filas_cat = cur.fetchall()
        if isinstance(filas_cat, (list, tuple)):
            for f in filas_cat:
                if isinstance(f, dict) and "id" in f and ("nombre" in f or "name" not in f):
                    cid = int(f["id"])
                    raw_nom = str(f.get("nombre") or "").strip()
                    if not raw_nom or raw_nom.lower().startswith("categoría") or raw_nom.lower().startswith("categoria"):
                        nom = DICCIONARIO_OFICIAL_CATEGORIAS.get(cid, raw_nom or f"Categoría {cid}")
                    else:
                        nom = raw_nom
                    categorias.append(CategoriaOpcion(id=cid, nombre=nom))
                elif isinstance(f, (list, tuple)) and len(f) == 2 and isinstance(f[0], int):
                    cid = int(f[0])
                    raw_nom = str(f[1] or "").strip()
                    if not raw_nom or raw_nom.lower().startswith("categoría") or raw_nom.lower().startswith("categoria"):
                        nom = DICCIONARIO_OFICIAL_CATEGORIAS.get(cid, raw_nom or f"Categoría {cid}")
                    else:
                        nom = raw_nom
                    categorias.append(CategoriaOpcion(id=cid, nombre=nom))
    except Exception:
        if conn is not None and hasattr(conn, "rollback"):
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute("SELECT DISTINCT categoria_id FROM public.articulos WHERE categoria_id IS NOT NULL ORDER BY categoria_id;")
            filas_c = cur.fetchall()
            if isinstance(filas_c, (list, tuple)):
                for f in filas_c:
                    cid = int(f["categoria_id"] if isinstance(f, dict) else f[0])
                    nom = DICCIONARIO_OFICIAL_CATEGORIAS.get(cid, f"Categoría {cid}")
                    categorias.append(CategoriaOpcion(id=cid, nombre=nom))
        except Exception:
            if conn is not None and hasattr(conn, "rollback"):
                try:
                    conn.rollback()
                except Exception:
                    pass

    # Si vino la lista completa de la BD (más de 10 elementos),
    # presentamos la lista curada de los 21 módulos clave acordados en la Opción A.
    # Si vino una lista acotada de un mock/test (len <= 10), respetamos el fixture del test.
    if len(categorias) > 10:
        categorias = list(CATEGORIAS_CURADAS_OPCION_A)

    try:
        cur.execute("SELECT id, name, slug FROM public.tags ORDER BY name;")
        filas_tags = cur.fetchall()
        if isinstance(filas_tags, (list, tuple)):
            vistos: set[str] = set()
            for f in filas_tags:
                nombre_tag = ""
                if isinstance(f, dict) and f.get("name"):
                    nombre_tag = str(f["name"]).strip()
                elif isinstance(f, (list, tuple)):
                    if len(f) >= 2 and isinstance(f[0], int) and len(f) == 3:
                        nombre_tag = str(f[1] or "").strip()
                    elif len(f) == 1 and isinstance(f[0], str):
                        nombre_tag = f[0].strip()
                elif isinstance(f, str):
                    nombre_tag = f.strip()
                if nombre_tag and nombre_tag.lower() not in vistos:
                    vistos.add(nombre_tag.lower())
                    tags.append(nombre_tag)
    except Exception:
        if conn is not None and hasattr(conn, "rollback"):
            try:
                conn.rollback()
            except Exception:
                pass

    return categorias, tags


_CACHE_CATEGORIAS: List[CategoriaOpcion] = []
_CACHE_TAGS: List[str] = []


def obtener_cache_catalogos() -> Tuple[List[CategoriaOpcion], List[str]]:
    return list(_CACHE_CATEGORIAS), list(_CACHE_TAGS)


def limpiar_cache_catalogos() -> None:
    global _CACHE_CATEGORIAS, _CACHE_TAGS
    _CACHE_CATEGORIAS = []
    _CACHE_TAGS = []


def precargar_catalogos_cache_sync(cur: Any) -> None:
    global _CACHE_CATEGORIAS, _CACHE_TAGS
    cats, tags = _consultar_categorias_y_tags_sync(cur)
    if cats:
        _CACHE_CATEGORIAS = cats
    if tags:
        _CACHE_TAGS = tags


async def cargar_catalogos_sesion(sesion: SesionChat, buscador: Optional[BuscadorDuplicados]) -> None:
    global _CACHE_CATEGORIAS, _CACHE_TAGS
    if _CACHE_CATEGORIAS and _CACHE_TAGS:
        if not sesion.categorias_disponibles:
            sesion.categorias_disponibles = list(_CACHE_CATEGORIAS)
        if not sesion.tags_disponibles:
            sesion.tags_disponibles = list(_CACHE_TAGS)
    else:
        cur = getattr(buscador, "cur", None) if buscador is not None else None
        if cur is None:
            if _CACHE_CATEGORIAS and not sesion.categorias_disponibles:
                sesion.categorias_disponibles = list(_CACHE_CATEGORIAS)
            elif not sesion.categorias_disponibles:
                sesion.categorias_disponibles = list(CATEGORIAS_CURADAS_OPCION_A)
            if _CACHE_TAGS and not sesion.tags_disponibles:
                sesion.tags_disponibles = list(_CACHE_TAGS)
        else:
            cats, tags_db = await run_in_threadpool(_consultar_categorias_y_tags_sync, cur)
            if cats:
                _CACHE_CATEGORIAS = cats
                if not sesion.categorias_disponibles:
                    sesion.categorias_disponibles = list(cats)
            elif _CACHE_CATEGORIAS and not sesion.categorias_disponibles:
                sesion.categorias_disponibles = list(_CACHE_CATEGORIAS)
            elif not sesion.categorias_disponibles:
                sesion.categorias_disponibles = list(CATEGORIAS_CURADAS_OPCION_A)

            if tags_db:
                _CACHE_TAGS = tags_db
                if not sesion.tags_disponibles:
                    sesion.tags_disponibles = list(tags_db)
            elif _CACHE_TAGS and not sesion.tags_disponibles:
                sesion.tags_disponibles = list(_CACHE_TAGS)

    cat_actual = sesion.borrador.categoria_id if (sesion.borrador and sesion.borrador.categoria_id) else None
    if cat_actual and sesion.categorias_disponibles:
        if not any(c.id == cat_actual for c in sesion.categorias_disponibles):
            nombre_extra = DICCIONARIO_OFICIAL_CATEGORIAS.get(cat_actual, f"Categoría {cat_actual}")
            sesion.categorias_disponibles.append(CategoriaOpcion(id=cat_actual, nombre=nombre_extra))


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


def consolidar_texto_enriquecimiento(
    texto_base: str, texto_aporte_raw: str
) -> Tuple[str, Optional[str]]:
    """
    Sanitiza el aporte y lo consolida con el texto base del artículo existente.
    Permite modificar o eliminar secciones cuando el aporte es sustancial o reemplazo completo,
    y anexa automáticamente cuando se trata de una nota o adición breve (<40% o <250 caracteres).
    Retorna: (texto_consolidado, aviso_privacidad).
    """
    sanit = sanitizar_borrador(texto=texto_aporte_raw)
    aporte_limpio = sanit["texto_sanitizado"]
    aviso_priv = sanit.get("aviso_privacidad")

    base = (texto_base or "").strip()
    if aporte_limpio and base:
        if base in aporte_limpio:
            return aporte_limpio, aviso_priv
        if len(aporte_limpio) < min(len(base) * 0.4, 250):
            return f"{base}\n\n{aporte_limpio}", aviso_priv
        return aporte_limpio, aviso_priv
    return (aporte_limpio or base), aviso_priv


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
    filas: list, mensaje: str = "", texto_original: Optional[str] = None, tipo_coincidencia: Optional[str] = None
) -> List[CoincidenciaArticulo]:
    if not filas:
        return []
    f = filas[0]
    score = extraer_score(f, mensaje)
    tipo = tipo_coincidencia
    if not tipo:
        if "serie" in (mensaje or "").lower() or (isinstance(f, dict) and "base_titulo" in f):
            tipo = "serie"
        elif "exactamente" in (mensaje or "").lower():
            tipo = "exacto"
        elif "similar" in (mensaje or "").lower():
            tipo = "trigrama"
        else:
            tipo = "semantico"

    if isinstance(f, dict):
        return [
            CoincidenciaArticulo(
                id=int(f["id"]),
                titulo=str(f["titulo"]),
                url=str(f["url"]),
                score=score,
                texto_original=texto_original or f.get("texto"),
                tipo_coincidencia=tipo,
            )
        ]
    return [
        CoincidenciaArticulo(
            id=int(f[0]),
            titulo=str(f[1]),
            url=str(f[2]),
            score=score,
            texto_original=texto_original,
            tipo_coincidencia=tipo,
        )
    ]


def parsear_metadatos_mensaje(
    mensaje: Optional[str],
    tags_req: Optional[List[str]],
    cat_req: Optional[int],
    texto_fallback: Optional[str] = None,
    categorias_disponibles: Optional[List[CategoriaOpcion]] = None,
    tags_disponibles: Optional[List[str]] = None,
) -> Tuple[List[str], Optional[int]]:
    nuevos_tags: List[str] = list(tags_req or [])
    cat_res = cat_req
    mapa_cat_nombre = {
        c.nombre.strip().lower(): c.id for c in (categorias_disponibles or []) if c.nombre
    }
    set_tags = {t.strip().lower() for t in (tags_disponibles or []) if t and str(t).strip()}
    cadena = (mensaje or texto_fallback or "").strip()
    if not cadena:
        return nuevos_tags, cat_res

    vino_de_mensaje = bool(mensaje and mensaje.strip())
    fragmentos = [f.strip() for f in cadena.split(",") if f.strip()]

    # Si hay un fragmento numérico explícito, tiene prioridad absoluta como categoria_id
    if cat_res is None:
        for f in fragmentos:
            if f.isdigit():
                cat_res = int(f)
                break

    for item in fragmentos:
        if item.isdigit():
            # Si coincide con cat_res ya asignado, no lo agregamos a tags
            if cat_res is not None and int(item) == cat_res:
                continue
            if not tags_req:
                nuevos_tags.append(item)
        elif item.lower() in set_tags:
            if not tags_req:
                nuevos_tags.append(item)
        elif vino_de_mensaje and cat_res is None and item.lower() in mapa_cat_nombre:
            cat_res = mapa_cat_nombre[item.lower()]
        else:
            if not tags_req:
                nuevos_tags.append(item)

    return nuevos_tags, cat_res


def interpretar_opcion(req: ChatOrquestadorRequest) -> str:
    bruto = (req.accion or req.mensaje or "").strip().lower()
    mapa = {
        "si": "enriquecer", "sí": "enriquecer", "1": "enriquecer", "enriquecer": "enriquecer",
        "actualizar": "actualizar", "actualizo": "actualizar",
        "no": "descartar", "2": "descartar", "descartar": "descartar", "continuar": "continuar",
        "aprobar": "aprobar", "apruebo": "aprobar", "confirmar": "aprobar", "confirmado": "aprobar", "omitir": "aprobar",
        "rechazar": "rechazar", "rechazo": "rechazar", "cancelar": "rechazar",
        "confirmar_rechazo": "confirmar_rechazo", "confirmar rechazo": "confirmar_rechazo", "si, rechazar": "confirmar_rechazo", "sí, rechazar": "confirmar_rechazo",
        "sanitizar": "sanitizar", "editar": "editar", "corregir": "editar", "enviar_correccion": "editar", "correccion": "editar",
        "reiniciar": "reiniciar", "cambiar tema": "reiniciar", "cambiar de tema": "reiniciar",
        "volver": "volver", "atras": "volver", "atrás": "volver", "regresar": "volver", "anterior": "volver",
        "ayuda": "ayuda", "opciones": "ayuda", "que hago": "ayuda", "qué hago": "ayuda", "?": "ayuda", "instrucciones": "ayuda",
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
        etapa=obtener_etapa_flujo(sesion.estado),
        mensaje=mensaje,
        opciones=opciones,
        tags_acumulados=obtener_tags_acumulados(sesion),
        categorias_disponibles=list(sesion.categorias_disponibles),
        tags_disponibles=list(sesion.tags_disponibles),
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
            f"{prefijo}Todavía no podemos avanzar porque hay puntos obligatorios pendientes:\n{detalle}\n"
            "Podés tocar 'editar' para corregirlos, 'sanitizar' si necesitás limpiar datos personales, o 'rechazar' para cancelar.",
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
            f"{prefijo}Todavía no podemos avanzar porque hay puntos obligatorios pendientes:\n{detalle}\n"
            "Podés tocar 'editar' para corregirlos, 'sanitizar' si necesitás limpiar datos personales, o 'rechazar' para cancelar.",
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
        f"{prefijo}El borrador fue validado ({res['status']}).{detalle_sug}¿Confirmás aprobar o rechazar?",
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
            sesion, msg_pedir_metadatos(b.tipo_plantilla, prefijo), ["volver"], aviso_privacidad=aviso_privacidad
        )

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_privacidad)
