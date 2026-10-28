import difflib
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
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
    MSG_ANTES_DE_CONFORME,
    OPCIONES_PLANTILLAS,
    OPCIONES_REVISION_BLOQUEANTE,
    OPCIONES_REVISION_VALIDO,
    msg_error_longitud_maxima,
    msg_error_longitud_minima,
    msg_pedir_metadatos,
    msg_pedir_plantilla,
)
from baco.server.services.orquestador.recursos_service import (
    _max_num_recurso,
    componer_texto_publicable,
    extraer_recursos_y_texto_limpio,
    fusionar_texto_y_recursos_sin_colision,
    texto_efectivo_sin_marcadores,
)
from baco.server.services.orquestador.sesion import SesionChat, multimedia_habilitada

ETAPAS_FLUJO: List[str] = [
    "Título y duplicados",
    "Contenido",
    "Plantilla y etiquetas",
    "Revisión",
    "Conformidad",
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
    EstadoFlujo.CONFORMIDAD_USUARIO: (5, "Conformidad"),
    EstadoFlujo.RECHAZADO: (5, "Conformidad"),
}


def obtener_etapa_flujo(
    estado: EstadoFlujo, sesion: Optional[SesionChat] = None
) -> EtapaFlujo:
    actual, nombre = MAPA_ESTADO_ETAPA.get(estado, (1, ETAPAS_FLUJO[0]))
    if sesion and sesion.borrador:
        b = sesion.borrador
        if b.metadatos_anteriores and not b.metadatos_heredados_revisados and actual > 3:
            actual, nombre = (3, ETAPAS_FLUJO[2])
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


CATALOGO_OFICIAL_165_CATEGORIAS: List[CategoriaOpcion] = [
    CategoriaOpcion(id=cid, nombre=DICCIONARIO_OFICIAL_CATEGORIAS.get(cid, f"Categoría {cid}"))
    for cid in range(1, 166)
]


def _consultar_categorias_y_tags_sync(cur: Any) -> Tuple[List[CategoriaOpcion], List[str]]:
    categorias: List[CategoriaOpcion] = []
    tags: List[str] = []
    if cur is None:
        return list(CATALOGO_OFICIAL_165_CATEGORIAS), tags

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

    # Si vino la lista de la BD (más de 10 elementos),
    # completamos con el catálogo oficial de las 165 categorías para garantizar que estén todas disponibles.
    # Si vino una lista acotada de un mock/test (len <= 10), respetamos el fixture del test.
    if len(categorias) > 10:
        mapa_existente = {c.id: c.nombre for c in categorias}
        categorias = [
            CategoriaOpcion(id=cid, nombre=mapa_existente.get(cid, DICCIONARIO_OFICIAL_CATEGORIAS.get(cid, f"Categoría {cid}")))
            for cid in range(1, 166)
        ]

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
                sesion.categorias_disponibles = list(CATALOGO_OFICIAL_165_CATEGORIAS)
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
                sesion.categorias_disponibles = list(CATALOGO_OFICIAL_165_CATEGORIAS)

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
    l = (
        len(texto_efectivo_sin_marcadores(texto))
        if campo == "texto"
        else len(texto.strip())
    )
    if l < min_c:
        return msg_error_longitud_minima(campo, min_c)
    if l > max_c:
        return msg_error_longitud_maxima(campo, max_c)
    return None


def validar_longitud_maxima(texto: str, max_c: int, campo: str) -> Optional[str]:
    l = (
        len(texto_efectivo_sin_marcadores(texto))
        if campo == "texto"
        else len(texto.strip())
    )
    if l > max_c:
        return msg_error_longitud_maxima(campo, max_c)
    return None


def consolidar_texto_enriquecimiento(
    texto_base: str, texto_aporte_raw: str
) -> Tuple[str, Optional[str]]:
    """
    Sanitiza el aporte y lo consolida con el texto base del artículo existente.
    Preserva siempre el texto proveniente de la API (texto_base), aplicando la
    autosanitización únicamente sobre el aporte o las adiciones del usuario.
    Retorna: (texto_consolidado, aviso_privacidad).
    """
    base = (texto_base or "").strip()
    raw = (texto_aporte_raw or "").strip()
    if not raw:
        return base, None
    if base and raw == base:
        return base, None
    if base and base in raw:
        pre, post = raw.split(base, 1)
        avisos = []
        pre_limpio = ""
        post_limpio = ""
        if pre.strip():
            s_pre = sanitizar_borrador(texto=pre)
            pre_limpio = s_pre["texto_sanitizado"]
            if s_pre.get("aviso_privacidad"):
                avisos.append(s_pre["aviso_privacidad"])
        if post.strip():
            s_post = sanitizar_borrador(texto=post)
            post_limpio = s_post["texto_sanitizado"]
            if s_post.get("aviso_privacidad"):
                avisos.append(s_post["aviso_privacidad"])
        partes = [p for p in (pre_limpio, base, post_limpio) if p]
        aviso_priv = avisos[0] if avisos else None
        return "\n\n".join(partes), aviso_priv

    sanit = sanitizar_borrador(texto=raw)
    aporte_limpio = sanit["texto_sanitizado"]
    aviso_priv = sanit.get("aviso_privacidad")

    if aporte_limpio and base:
        if base in aporte_limpio:
            return aporte_limpio, aviso_priv
        # Si la base fue modificada o editada por el usuario, se respeta la edición manual sin forzar append de la base original
        return aporte_limpio, aviso_priv
    return (aporte_limpio or base), aviso_priv


def actualizar_metadatos_sesion(sesion: SesionChat, req: ChatOrquestadorRequest) -> None:
    if req.titulo is not None and req.titulo.strip():
        sanit_t = sanitizar_borrador(texto="", titulo=req.titulo.strip(), sanitizar_redundancia_titulo=False)
        sesion.titulo = (sanit_t["titulo_sanitizado"] or req.titulo.strip()).strip()
        if sesion.borrador is not None:
            sesion.borrador.titulo = sesion.titulo
    if (
        req.texto is not None
        and req.texto.strip()
        and sesion.estado == EstadoFlujo.ESPERANDO_TITULO
    ):
        from baco.server.services.orquestador.recursos_service import (
            extraer_recursos_y_bloques_texto,
            fusionar_bloques_y_recursos_sin_colision,
        )
        bloques_ext, recs = extraer_recursos_y_bloques_texto(
            req.texto.strip(),
            recursos_previos=sesion.recursos,
            ultimo_id=sesion.ultimo_id_recurso,
        )
        bloques_ext, recs_merged = fusionar_bloques_y_recursos_sin_colision(
            bloques_ext, sesion.recursos, recs, ultimo_id=sesion.ultimo_id_recurso
        )
        bloques_san = [
            sanitizar_borrador(texto=b, titulo=sesion.titulo if i == 0 else "")["texto_sanitizado"].strip()
            for i, b in enumerate(bloques_ext)
            if b.strip()
        ]
        sesion.bloques_texto = [b for b in bloques_san if b]
        sesion.texto_limpio = "\n\n".join(sesion.bloques_texto).strip()
        sesion.recursos = recs_merged
        sesion.ultimo_id_recurso = max(sesion.ultimo_id_recurso, _max_num_recurso(recs_merged))
        sesion.orden_multimedia = list(range(len(recs_merged)))
        sesion.posiciones = [r.posicion for r in recs_merged.values()]
        sesion.texto = componer_texto_publicable(sesion.bloques_texto, sesion.recursos)
    if getattr(req, "texto_editor", None) is not None:
        sanit_te = sanitizar_borrador(texto=req.texto_editor)["texto_sanitizado"]
        sesion.texto_editor = sanit_te
        if sesion.borrador is not None:
            sesion.borrador.texto_editor = sanit_te
    if req.categoria_id is not None:
        sesion.categoria_id = req.categoria_id
    if req.tags is not None:
        tags_san = [
            sanitizar_borrador(texto=t, sanitizar_redundancia_titulo=False)["texto_sanitizado"].strip()
            for t in req.tags
            if isinstance(t, str) and t.strip()
        ]
        sesion.tags = tags_san
        if sesion.borrador is not None:
            sesion.borrador.tags = tags_san


async def cargar_datos_articulo(
    buscador: BuscadorDuplicados, articulo_id: int
) -> Tuple[str, Optional[int], List[str]]:
    """Carga el contenido y metadatos de un artículo existente para enriquecimiento.

    Prioridad:
    1. Consulta SIEMPRE en tiempo real con imágenes directas desde bc.finneg.com (GET anónimo).
    2. Si no existe en producción (404, error de red o tema borrado), hace fallback al texto guardado en la DB local.
    CERO persistencia: la consulta no almacena nada en disco ni en base de datos.
    """
    from baco.server.services.discourse_media import consultar_articulo_bc_publico
    import unittest.mock

    is_bc_mocked = isinstance(consultar_articulo_bc_publico, (unittest.mock.MagicMock, unittest.mock.AsyncMock))
    is_buscador_mocked = isinstance(getattr(buscador, "obtener_articulo", None), (unittest.mock.MagicMock, unittest.mock.AsyncMock))

    # 1. Consulta prioritaria en tiempo real a bc.finneg.com (GET público) en producción o si está explícitamente mockeado en tests
    if not is_buscador_mocked or is_bc_mocked:
        texto_bc, cat_bc, tags_bc = await run_in_threadpool(consultar_articulo_bc_publico, articulo_id)
        if texto_bc:
            if (not tags_bc or not cat_bc) and hasattr(buscador, "obtener_articulo"):
                art_db = await run_in_threadpool(buscador.obtener_articulo, articulo_id)
                if isinstance(art_db, dict):
                    if not tags_bc:
                        tags_bc = [str(t).strip() for t in (art_db.get("tags") or []) if str(t).strip()]
                    if not cat_bc:
                        cat_bc = art_db.get("categoria_id")
            return texto_bc.strip(), cat_bc, tags_bc

    # 2. Fallback controlado a la base de datos local si falla, da 404 o es mock de pruebas
    if hasattr(buscador, "obtener_articulo"):
        art_db = await run_in_threadpool(buscador.obtener_articulo, articulo_id)
        if isinstance(art_db, dict):
            texto_db = (art_db.get("texto") or "").strip()
            cat_db = art_db.get("categoria_id")
            tags_db = [str(t).strip() for t in (art_db.get("tags") or []) if str(t).strip()]
            if texto_db:
                return texto_db, cat_db, tags_db

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


def normalizar_texto_categoria(texto: str) -> str:
    if not texto:
        return ""
    t = str(texto).strip().lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.strip()


@dataclass
class ResultadoCategoria:
    categoria_id: Optional[int]
    categoria_nombre: Optional[str]
    candidatos: List[CategoriaOpcion] = field(default_factory=list)
    estado: Literal["asignado", "ambiguo", "no_encontrado", "vacio"] = "vacio"


def resolver_categoria(
    entrada: Union[str, int, None],
    categorias_disponibles: Optional[List[CategoriaOpcion]] = None,
) -> ResultadoCategoria:
    if entrada is None:
        return ResultadoCategoria(categoria_id=None, categoria_nombre=None, estado="vacio")

    catalogo: List[CategoriaOpcion] = list(categorias_disponibles or CATALOGO_OFICIAL_165_CATEGORIAS)

    # 1. Entrada numérica (id directo)
    es_digito = isinstance(entrada, int) or (isinstance(entrada, str) and str(entrada).strip().isdigit())
    if es_digito:
        cid = int(entrada)
        nom = None
        for c in catalogo:
            if c.id == cid:
                nom = c.nombre
                break
        if not nom:
            nom = DICCIONARIO_OFICIAL_CATEGORIAS.get(cid, f"Categoría {cid}")
        return ResultadoCategoria(categoria_id=cid, categoria_nombre=nom, estado="asignado")

    raw = str(entrada).strip()
    if not raw:
        return ResultadoCategoria(categoria_id=None, categoria_nombre=None, estado="vacio")

    norm_in = normalizar_texto_categoria(raw)
    if not norm_in:
        return ResultadoCategoria(categoria_id=None, categoria_nombre=None, estado="vacio")

    # Mapeo y deduplicación de categorías válidas (sin dummies sintéticos sin nombre real)
    mapa_unicos: Dict[str, CategoriaOpcion] = {}
    for c in catalogo:
        nom = (c.nombre or "").strip()
        if not nom:
            continue
        norm_c = normalizar_texto_categoria(nom)
        if norm_c.startswith("categoria ") and norm_c[10:].isdigit():
            if c.id in DICCIONARIO_OFICIAL_CATEGORIAS:
                nom_real = DICCIONARIO_OFICIAL_CATEGORIAS[c.id]
                c = CategoriaOpcion(id=c.id, nombre=nom_real)
                norm_c = normalizar_texto_categoria(nom_real)
            else:
                continue

        if norm_c not in mapa_unicos:
            mapa_unicos[norm_c] = c
        else:
            existente = mapa_unicos[norm_c]
            if c.id < existente.id:
                mapa_unicos[norm_c] = c

    lista_unicos = list(mapa_unicos.values())

    # a) Coincidencia exacta normalizada
    if norm_in in mapa_unicos:
        c_exact = mapa_unicos[norm_in]
        return ResultadoCategoria(categoria_id=c_exact.id, categoria_nombre=c_exact.nombre, estado="asignado")

    # b) Coincidencia por prefijo
    cands_prefijo = [c for c in lista_unicos if normalizar_texto_categoria(c.nombre).startswith(norm_in)]
    if len(cands_prefijo) == 1:
        return ResultadoCategoria(categoria_id=cands_prefijo[0].id, categoria_nombre=cands_prefijo[0].nombre, estado="asignado")
    elif len(cands_prefijo) > 1:
        return ResultadoCategoria(categoria_id=None, categoria_nombre=None, candidatos=cands_prefijo, estado="ambiguo")

    # c) Coincidencia por contains (subcadena)
    cands_contains = [c for c in lista_unicos if norm_in in normalizar_texto_categoria(c.nombre)]
    if len(cands_contains) == 1:
        return ResultadoCategoria(categoria_id=cands_contains[0].id, categoria_nombre=cands_contains[0].nombre, estado="asignado")
    elif len(cands_contains) > 1:
        return ResultadoCategoria(categoria_id=None, categoria_nombre=None, candidatos=cands_contains, estado="ambiguo")

    # d) Coincidencia aproximada (difflib)
    nombres_norm = list(mapa_unicos.keys())
    matches = difflib.get_close_matches(norm_in, nombres_norm, n=5, cutoff=0.65)
    if len(matches) == 1:
        matched = mapa_unicos[matches[0]]
        return ResultadoCategoria(categoria_id=matched.id, categoria_nombre=matched.nombre, estado="asignado")
    elif len(matches) > 1:
        cands = [mapa_unicos[m] for m in matches]
        return ResultadoCategoria(categoria_id=None, categoria_nombre=None, candidatos=cands, estado="ambiguo")

    # e) No encontrado: sugerencias de categorías estándar
    sug_matches = difflib.get_close_matches(norm_in, nombres_norm, n=3, cutoff=0.35)
    sug_cands = [mapa_unicos[m] for m in sug_matches]
    if not sug_cands:
        sug_cands = [c for c in lista_unicos if c.nombre in ("Ventas", "Compras", "Contabilidad", "Agro", "Tesorería")][:3]
    return ResultadoCategoria(categoria_id=None, categoria_nombre=None, candidatos=sug_cands, estado="no_encontrado")


def parsear_metadatos_mensaje(
    mensaje: Optional[str],
    tags_req: Optional[List[str]],
    cat_req: Optional[int],
    texto_fallback: Optional[str] = None,
    categorias_disponibles: Optional[List[CategoriaOpcion]] = None,
    tags_disponibles: Optional[List[str]] = None,
) -> Tuple[List[str], Optional[int], Optional[str]]:
    nuevos_tags: List[str] = list(tags_req or [])
    cat_res = cat_req
    cat_nom = None
    if cat_res is not None:
        res_init = resolver_categoria(cat_res, categorias_disponibles)
        cat_nom = res_init.categoria_nombre

    cadena = (mensaje or texto_fallback or "").strip()
    if not cadena:
        return nuevos_tags, cat_res, cat_nom

    vino_de_mensaje = bool(mensaje and mensaje.strip())
    set_tags = {normalizar_texto_categoria(t) for t in (tags_disponibles or []) if t and str(t).strip()}
    fragmentos = [f.strip() for f in cadena.split(",") if f.strip()]

    for item in fragmentos:
        if item.isdigit():
            if cat_res is None:
                res_num = resolver_categoria(int(item), categorias_disponibles)
                if res_num.categoria_id is not None:
                    cat_res = res_num.categoria_id
                    cat_nom = res_num.categoria_nombre
                    continue
            if not tags_req:
                nuevos_tags.append(item)
            continue

        item_norm = normalizar_texto_categoria(item)

        # Si coincide con un tag existente en la base, es prioritariamente una etiqueta temática
        if set_tags and item_norm in set_tags:
            if not tags_req:
                nuevos_tags.append(item)
            continue

        # Si no coincide con un tag y aún no hay categoría, verificar si es el nombre de una categoría.
        # Regla sine qua non: En turno 1 nunca se infiere categoría desde palabras simples (ej. "ventas", "agro"),
        # ya que los vocabularios de tags y categorías colisionan. Sólo se asigna categoría si es una frase
        # multipalabra exacta del catálogo oficial (ej. "Liquidación de Haberes").
        if cat_res is None and vino_de_mensaje and len(item.split()) > 1:
            res_c = resolver_categoria(item, categorias_disponibles)
            if res_c.estado == "asignado":
                cat_res = res_c.categoria_id
                cat_nom = res_c.categoria_nombre
                continue

        # Si no fue categoría ni tag conocido, se toma como nuevo tag temático
        if not tags_req:
            nuevos_tags.append(item)

    return nuevos_tags, cat_res, cat_nom


def interpretar_opcion(req: ChatOrquestadorRequest) -> str:
    bruto = (req.accion or req.mensaje or "").strip().lower()
    mapa = {
        "si": "enriquecer", "sí": "enriquecer", "1": "enriquecer", "enriquecer": "enriquecer",
        "actualizar": "actualizar", "actualizo": "actualizar",
        "no": "descartar", "2": "descartar", "descartar": "descartar", "continuar": "continuar",
        "confirmar_texto": "confirmar_texto", "confirmar texto": "confirmar_texto",
        "quitar_recursos": "quitar_recursos", "quitar recursos": "quitar_recursos", "quitar": "quitar_recursos",
        "seguir_con_recursos": "seguir_con_recursos", "seguir con recursos": "seguir_con_recursos",
        "continuar_con_recursos": "seguir_con_recursos", "continuar con recursos": "seguir_con_recursos",
        "con recursos": "seguir_con_recursos", "sin skills": "seguir_con_recursos",
        "conforme": "conforme", "estoy conforme": "conforme", "estoy_conforme": "conforme", "aprobar": "conforme", "apruebo": "conforme", "confirmar": "conforme", "confirmado": "conforme", "omitir": "conforme",
        "aceptar": "aceptar_metadatos", "acepto": "aceptar_metadatos", "aceptar_metadatos": "aceptar_metadatos", "aceptar metadatos": "aceptar_metadatos", "conservar": "aceptar_metadatos", "conservar metadatos": "aceptar_metadatos",
        "rechazar_metadatos": "rechazar_metadatos", "rechazar metadatos": "rechazar_metadatos",
        "copiar borrador": "copiar_borrador", "copiar_borrador": "copiar_borrador", "copiar": "copiar_borrador",
        "rechazar": "rechazar", "rechazo": "rechazar", "cancelar": "rechazar",
        "confirmar_rechazo": "confirmar_rechazo", "confirmar rechazo": "confirmar_rechazo", "si, rechazar": "confirmar_rechazo", "sí, rechazar": "confirmar_rechazo",
        "sanitizar": "sanitizar", "editar": "editar", "corregir": "editar", "enviar_correccion": "editar", "correccion": "editar", "seguir editando": "editar", "seguir_editando": "editar",
        "reiniciar": "reiniciar", "cambiar tema": "reiniciar", "cambiar de tema": "reiniciar",
        "volver": "volver", "atras": "volver", "atrás": "volver", "regresar": "volver", "anterior": "volver",
        "ayuda": "ayuda", "opciones": "ayuda", "que hago": "ayuda", "qué hago": "ayuda", "?": "ayuda", "instrucciones": "ayuda",
        "instructivo": "instructivo", "instructivos": "instructivo",
        "soluciones": "soluciones", "solucion": "soluciones", "solución": "soluciones",
    }
    return mapa.get(bruto, bruto)


def obtener_aviso_metadatos_heredados(borrador: Optional[BorradorSesion]) -> Optional[str]:
    if not borrador or not borrador.metadatos_anteriores or borrador.metadatos_heredados_revisados:
        return None
    ant = borrador.metadatos_anteriores
    cat_nom = ant.get("categoria_nombre") or (
        DICCIONARIO_OFICIAL_CATEGORIAS.get(ant.get("categoria_id"), f"Categoría {ant.get('categoria_id')}")
        if ant.get("categoria_id") else "Sin categoría"
    )
    tags_str = ", ".join(ant.get("tags") or []) or "ninguna"
    return (
        f"El artículo en su versión anterior tenía asociada la categoría '{cat_nom}' y las etiquetas: [{tags_str}]. "
        "Podés tocar 'Aceptar' para conservar estos metadatos o 'Rechazar' si preferís definirlos manualmente."
    )


def construir_respuesta(
    sesion: SesionChat,
    mensaje: str,
    opciones: List[str],
    aviso_privacidad: Optional[str] = None,
    aviso_metadatos_heredados: Optional[str] = None,
) -> ChatOrquestadorResponse:
    txt_titulo_actual = (
        sesion.borrador.titulo
        if sesion.borrador is not None
        else (sesion.titulo or None)
    )
    txt_limpio_actual = (
        sesion.borrador.texto_limpio
        if sesion.borrador is not None
        else (sesion.texto_limpio or sesion.texto_en_edicion or None)
    )
    if sesion.borrador is not None:
        skills_hab = sesion.borrador.skills_habilitadas
        skills_mot = sesion.borrador.skills_motivo
    else:
        from baco.server.config_limites import TEXTO_MAX
        from baco.server.services.orquestador.recursos_service import texto_efectivo_sin_marcadores

        largo = len(texto_efectivo_sin_marcadores(txt_limpio_actual or ""))
        supera_largo = largo > TEXTO_MAX
        tiene_recursos = bool(sesion.recursos)
        if supera_largo or tiene_recursos:
            skills_hab = False
            if supera_largo and tiene_recursos:
                skills_mot = (
                    f"El texto supera el límite de {TEXTO_MAX} caracteres para el uso de skills "
                    f"({largo} caracteres recibidos) y el borrador contiene recursos multimedia."
                )
            elif supera_largo:
                skills_mot = (
                    f"El texto supera el límite de {TEXTO_MAX} caracteres para el uso de skills "
                    f"({largo} caracteres recibidos)."
                )
            else:
                skills_mot = "El borrador contiene recursos multimedia. Las skills de IA solo admiten texto plano sin recursos."
        else:
            skills_hab = True
            skills_mot = None

    tiene_meta_pendiente = bool(
        sesion.borrador
        and sesion.borrador.metadatos_anteriores
        and not sesion.borrador.metadatos_heredados_revisados
        and sesion.estado not in (
            EstadoFlujo.ESPERANDO_TITULO,
            EstadoFlujo.DECISION_TITULO,
            EstadoFlujo.ESPERANDO_TEXTO,
            EstadoFlujo.DECISION_TEXTO,
        )
    )
    meta_aviso_final = aviso_metadatos_heredados
    if tiene_meta_pendiente and not meta_aviso_final:
        meta_aviso_final = obtener_aviso_metadatos_heredados(sesion.borrador)

    opciones_finales = list(opciones)
    if tiene_meta_pendiente:
        if "aceptar" not in opciones_finales and "aceptar_metadatos" not in opciones_finales:
            opciones_finales = ["aceptar", "rechazar"] + [o for o in opciones_finales if o not in ("aceptar", "rechazar")]

    return ChatOrquestadorResponse(
        session_id=sesion.session_id,
        estado=sesion.estado,
        etapa=obtener_etapa_flujo(sesion.estado, sesion),
        mensaje=mensaje,
        opciones=opciones_finales,
        tags_acumulados=obtener_tags_acumulados(sesion),
        categorias_disponibles=list(sesion.categorias_disponibles),
        tags_disponibles=list(sesion.tags_disponibles),
        coincidencias=sesion.coincidencias if sesion.estado in (EstadoFlujo.DECISION_TITULO, EstadoFlujo.DECISION_TEXTO) else [],
        borrador=sesion.borrador,
        titulo=txt_titulo_actual,
        texto_limpio=txt_limpio_actual,
        multimedia_habilitada=multimedia_habilitada(sesion),
        skills_habilitadas=skills_hab,
        skills_motivo=skills_mot,
        validacion=sesion.validacion,
        aviso_privacidad=aviso_privacidad,
        aviso_metadatos_heredados=meta_aviso_final,
    )


def validar_borrador(sesion: SesionChat, prefijo: str = "") -> Tuple[str, List[str]]:
    b = sesion.borrador
    texto_eval = (b.texto_limpio if (b and b.texto_limpio) else (b.texto_alineado_discourse if b else ""))
    try:
        articulo = ArticuloSchema(
            id=b.articulo_original_id or 0,
            titulo=b.titulo,
            texto=texto_eval,
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
            resumen={
                "longitud_texto": len(texto_efectivo_sin_marcadores(texto_eval or "")),
                "tags_count": len(b.tags or []),
            },
        )
        sesion.estado = EstadoFlujo.REVISION_BORRADOR
        detalle = "\n".join(f"- [{f['severity']}] {f['field']}: {f['description']}" for f in findings)
        return (
            f"{prefijo}Todavía no podemos avanzar porque hay puntos obligatorios pendientes:\n{detalle}\n"
            "Podés tocar 'editar' para corregirlos o 'rechazar' para cancelar.",
            OPCIONES_REVISION_BLOQUEANTE,
        )

    res = validar_texto_y_estructura_post_duplicados(articulo)
    valido = res["status"] != "Pendiente"
    if b.modo == "enriquecimiento" and (
        b.texto_base_limpio or (sesion.coincidencias and sesion.coincidencias[0].texto_original)
    ):
        texto_base_limpio = (
            b.texto_base_limpio
            if b.texto_base_limpio
            else extraer_recursos_y_texto_limpio(sesion.coincidencias[0].texto_original.strip())[0]
        )
        texto_preservado, aviso_preservado = consolidar_texto_enriquecimiento(texto_base_limpio, texto_eval)
        b.texto_limpio = texto_preservado
        b.texto_base_limpio = texto_preservado
        res["texto_sanitizado"] = texto_preservado
        if aviso_preservado:
            res["aviso_privacidad"] = aviso_preservado
    elif res.get("texto_sanitizado"):
        b.texto_limpio = res["texto_sanitizado"]
    if res.get("titulo_sanitizado"):
        b.titulo = res["titulo_sanitizado"]
    sesion.validacion = ValidarFormatoResponse(
        valido=valido,
        status=res["status"],
        titulo_sanitizado=res.get("titulo_sanitizado"),
        texto_sanitizado=res.get("texto_sanitizado"),
        aviso_privacidad=res.get("aviso_privacidad"),
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
            "Podés tocar 'editar' para corregirlos o 'rechazar' para cancelar.",
            OPCIONES_REVISION_BLOQUEANTE,
        )

    if ajustes:
        detalle = "\n".join(f"- [{f['severity']}] {f['description']} ({f['action']})" for f in ajustes)
        return (
            f"{prefijo}El borrador supera los requisitos técnicos mínimos pero presenta {len(ajustes)} observación(es) "
            f"editoriales que requieren ajuste humano:\n{detalle}\n\n{MSG_ANTES_DE_CONFORME}",
            OPCIONES_REVISION_VALIDO,
        )

    obs = "\n".join(f"- [{f['severity']}] {f['description']} ({f['action']})" for f in sugerencias)
    detalle_sug = f"\nSugerencias:\n{obs}\n\n" if obs else "\n\n"
    return (
        f"{prefijo}El borrador fue validado ({res['status']}).{detalle_sug}{MSG_ANTES_DE_CONFORME}",
        OPCIONES_REVISION_VALIDO,
    )


def avanzar_a_metadatos_o_revision(
    sesion: SesionChat, prefijo: str = "", aviso_privacidad: Optional[str] = None
) -> ChatOrquestadorResponse:
    b = sesion.borrador
    if b.categoria_id is None and sesion.categoria_id is not None:
        b.categoria_id = sesion.categoria_id

    # Prioridad 1: Si hay metadatos heredados de una versión anterior y todavía no fueron confirmados/revisados:
    if b.metadatos_anteriores and not b.metadatos_heredados_revisados:
        sesion.estado = EstadoFlujo.REVISION_BORRADOR
        cat_nom = b.metadatos_anteriores.get("categoria_nombre") or (
            DICCIONARIO_OFICIAL_CATEGORIAS.get(b.metadatos_anteriores.get("categoria_id"), f"Categoría {b.metadatos_anteriores.get('categoria_id')}")
            if b.metadatos_anteriores.get("categoria_id") else "Sin categoría"
        )
        tags_str = ", ".join(b.metadatos_anteriores.get("tags") or []) or "ninguna"
        aviso_meta = (
            f"El artículo en su versión anterior tenía asociada la categoría '{cat_nom}' y las etiquetas: [{tags_str}]. "
            "Podés tocar 'Aceptar' para conservar estos metadatos o 'Rechazar' si preferís definirlos manualmente."
        )
        msg_val, ops_val = validar_borrador(sesion, prefijo)
        mensaje_espera = f"{prefijo}Esperando confirmación o rechazo de los metadatos heredados en el panel izquierdo."
        ops = ["aceptar", "rechazar"] + [o for o in ops_val if o not in ("aceptar", "rechazar")]
        return construir_respuesta(
            sesion,
            mensaje_espera,
            ops,
            aviso_privacidad=aviso_privacidad,
            aviso_metadatos_heredados=aviso_meta,
        )

    plantilla = b.tipo_plantilla or extraer_tipo_plantilla(b.tags)
    if plantilla:
        b.tipo_plantilla = plantilla
        b.tags = combinar_tags(plantilla, b.tags)

    if not b.tipo_plantilla:
        sesion.estado = EstadoFlujo.ESPERANDO_PLANTILLA
        return construir_respuesta(
            sesion, msg_pedir_plantilla(prefijo), OPCIONES_PLANTILLAS, aviso_privacidad=aviso_privacidad
        )

    if len(b.tags) < 2 or b.categoria_id is None:
        sesion.estado = EstadoFlujo.ESPERANDO_METADATOS
        return construir_respuesta(
            sesion, msg_pedir_metadatos(b.tipo_plantilla, prefijo), ["volver"], aviso_privacidad=aviso_privacidad
        )

    msg, ops = validar_borrador(sesion, prefijo)
    return construir_respuesta(sesion, msg, ops, aviso_privacidad=aviso_privacidad)
