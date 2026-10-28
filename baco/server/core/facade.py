import logging
import sys
from typing import List, Optional
from psycopg.rows import dict_row
from pydantic import ValidationError

from baco.server.config_limites import (
    TEXTO_MAX,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)
from baco.server.db.config import get_ro_conn
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.schemas.duplicados import (
    ArticuloSimilarTool,
    BuscarDuplicadosToolOutput,
    NivelCoincidenciaEnum,
)
from baco.server.schemas.validacion import (
    HallazgoTool,
    StatusValidacionEnum,
    ValidarFormatoToolOutput,
)
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.recursos_service import texto_efectivo_sin_marcadores
from baco.server.services.validar_articulo import (
    sanitizar_borrador,
    validar_texto_y_estructura_post_duplicados,
)

logger = logging.getLogger("baco.core")
if not logger.handlers:
    _stderr_handler = logging.StreamHandler(sys.stderr)
    _stderr_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_stderr_handler)
    logger.propagate = False


def buscar_duplicados(
    titulo: Optional[str] = None,
    texto: Optional[str] = None,
    limite: int = 3,
    borrador: Optional[str] = None,
    *,
    _get_ro_conn=None,
    _buscador_cls=None,
) -> BuscarDuplicadosToolOutput:
    """
    Fachada de solo lectura para búsqueda de artículos duplicados o similares.
    Aplica las mismas cotas de entrada que la API REST y nunca devuelve el cuerpo del artículo.
    """
    if texto is None and borrador is not None:
        texto = borrador

    if not isinstance(limite, int) or isinstance(limite, bool) or limite < 1 or limite > 10:
        return BuscarDuplicadosToolOutput(
            decision_sugerida="crear_nuevo",
            hay_duplicados=False,
            nivel=NivelCoincidenciaEnum.NINGUNO,
            mensaje="El parámetro 'limite' debe estar entre 1 y 10.",
            url_principal=None,
            articulos_similares=[],
        )

    titulo_limpio = (titulo or "").strip() if isinstance(titulo, str) else ""
    texto_limpio = (texto or "").strip() if isinstance(texto, str) else ""

    if titulo_limpio:
        sanit_t = sanitizar_borrador(texto="", titulo=titulo_limpio, sanitizar_redundancia_titulo=False)
        titulo_limpio = sanit_t["titulo_sanitizado"] or titulo_limpio
    if texto_limpio:
        sanit_tx = sanitizar_borrador(texto=texto_limpio)
        texto_limpio = sanit_tx["texto_sanitizado"] or texto_limpio

    if not titulo_limpio and not texto_limpio:
        return BuscarDuplicadosToolOutput(
            decision_sugerida="crear_nuevo",
            hay_duplicados=False,
            nivel=NivelCoincidenciaEnum.NINGUNO,
            mensaje="No se proporcionó ni título ni borrador para contrastar.",
            url_principal=None,
            articulos_similares=[],
        )

    if titulo_limpio and (len(titulo_limpio) < TITULO_MIN or len(titulo_limpio) > TITULO_MAX):
        return BuscarDuplicadosToolOutput(
            decision_sugerida="crear_nuevo",
            hay_duplicados=False,
            nivel=NivelCoincidenciaEnum.NINGUNO,
            mensaje=f"El título debe tener entre {TITULO_MIN} y {TITULO_MAX} caracteres.",
            url_principal=None,
            articulos_similares=[],
        )

    largo_texto_efectivo = len(texto_efectivo_sin_marcadores(texto_limpio)) if texto_limpio else 0
    if texto_limpio and (largo_texto_efectivo < TEXTO_MIN or largo_texto_efectivo > TEXTO_MAX):
        return BuscarDuplicadosToolOutput(
            decision_sugerida="crear_nuevo",
            hay_duplicados=False,
            nivel=NivelCoincidenciaEnum.NINGUNO,
            mensaje=f"El texto debe tener entre {TEXTO_MIN} y {TEXTO_MAX} caracteres.",
            url_principal=None,
            articulos_similares=[],
        )

    conn_fn = _get_ro_conn or get_ro_conn
    cls_buscador = _buscador_cls or BuscadorDuplicados

    with conn_fn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            buscador = cls_buscador(cur)
            resultado = buscador.evaluar_coincidencias(
                titulo=titulo_limpio,
                headers=True,
                texto=texto_limpio if texto_limpio else None,
                limite=limite,
            )

    mensaje_res = resultado.get("mensaje", "")
    hay_duplicados = bool(resultado.get("encontrado"))
    es_exacto = hay_duplicados and (
        "exactamente este título" in mensaje_res
        or "exactamente la misma descripción" in mensaje_res
    )

    articulos: List[ArticuloSimilarTool] = []
    for c in resultado.get("coincidencias", []):
        if isinstance(c, dict):
            art_id = c.get("id")
            art_tit = c.get("titulo")
            art_url = c.get("url") or (f"https://bc.finneg.com/t/{art_id}" if art_id else None)
            raw_score = c.get("score_total") if c.get("score_total") is not None else c.get("score")
        elif isinstance(c, (tuple, list)) and len(c) >= 2:
            art_id = c[0]
            art_tit = c[1]
            art_url = c[2] if len(c) > 2 and c[2] else (f"https://bc.finneg.com/t/{art_id}" if art_id else None)
            raw_score = c[3] if len(c) > 3 and isinstance(c[3], (int, float)) else None
        else:
            continue

        if art_id and art_tit:
            if es_exacto and raw_score is None:
                score_final = 1.0
            elif raw_score is not None:
                score_final = float(raw_score)
            else:
                score_final = None

            articulos.append(
                ArticuloSimilarTool(
                    id=int(art_id),
                    titulo=str(art_tit),
                    url=str(art_url),
                    score=score_final,
                )
            )

    if not hay_duplicados and not articulos:
        nivel = NivelCoincidenciaEnum.NINGUNO
    elif es_exacto:
        nivel = NivelCoincidenciaEnum.EXACTO
    else:
        nivel = NivelCoincidenciaEnum.SIMILAR

    decision_sugerida = (
        "proponer_mejora_existente" if (hay_duplicados or len(articulos) > 0) else "crear_nuevo"
    )

    return BuscarDuplicadosToolOutput(
        decision_sugerida=decision_sugerida,
        hay_duplicados=hay_duplicados,
        nivel=nivel,
        mensaje=mensaje_res,
        url_principal=resultado.get("link"),
        articulos_similares=articulos,
    )


def validar_formato(
    titulo: str,
    texto: str,
    tags: Optional[List[str]] = None,
    categoria_id: Optional[int] = None,
) -> ValidarFormatoToolOutput:
    """
    Fachada en memoria para validar la estructura, plantilla, metadatos y sanitización PII
    de un borrador de artículo. Maneja entradas fuera de cota sin lanzar excepciones.
    """
    titulo_str = titulo if isinstance(titulo, str) else ""
    texto_str = texto if isinstance(texto, str) else ""
    tags_objetos = [Tag(name=t.strip()) for t in (tags or []) if isinstance(t, str) and t.strip()]

    from baco.server.services.orquestador.recursos_service import texto_efectivo_sin_marcadores
    if texto_str and len(texto_efectivo_sin_marcadores(texto_str)) > TEXTO_MAX:
        sanit = sanitizar_borrador(texto=texto_str, titulo=titulo_str)
        return ValidarFormatoToolOutput(
            valido=False,
            status=StatusValidacionEnum.PENDIENTE,
            titulo_sanitizado=sanit.get("titulo_sanitizado"),
            texto_sanitizado=sanit.get("texto_sanitizado"),
            hallazgos=[
                HallazgoTool(
                    severidad="Bloqueante",
                    campo="texto",
                    descripcion=f"El texto debe tener entre {TEXTO_MIN} y {TEXTO_MAX} caracteres (recibidos: {len(texto_efectivo_sin_marcadores(texto_str))}).",
                    accion=f"Ajustar la extensión del cuerpo para que tenga entre {TEXTO_MIN} y {TEXTO_MAX} caracteres.",
                )
            ],
            longitud_texto=len(texto_efectivo_sin_marcadores(texto_str)),
            tags_count=len(tags_objetos),
        )

    try:
        articulo = ArticuloSchema(
            id=0,
            titulo=titulo_str,
            texto=texto_str,
            tags=tags_objetos,
            categoria_id=categoria_id,
        )
    except ValidationError as exc:
        sanit = sanitizar_borrador(texto=texto_str, titulo=titulo_str)
        hallazgos_err: List[HallazgoTool] = []
        for err in exc.errors():
            campo_err = ".".join(map(str, err.get("loc", ("texto",)))) or "texto"
            if campo_err == "titulo":
                desc = f"El título debe tener entre {TITULO_MIN} y {TITULO_MAX} caracteres (recibidos: {len(titulo_str)})."
                acc = f"Ajustar la extensión del título para que tenga entre {TITULO_MIN} y {TITULO_MAX} caracteres."
            elif campo_err == "texto":
                desc = f"El texto debe tener entre {TEXTO_MIN} y {TEXTO_MAX} caracteres (recibidos: {len(texto_efectivo_sin_marcadores(texto_str))})."
                acc = f"Ajustar la extensión del cuerpo para que tenga entre {TEXTO_MIN} y {TEXTO_MAX} caracteres."
            else:
                desc = err.get("msg", "Valor inválido en el esquema del artículo.")
                acc = "Corregir el campo para cumplir con los requisitos del artículo."
            hallazgos_err.append(
                HallazgoTool(
                    severidad="Bloqueante",
                    campo=campo_err,
                    descripcion=desc,
                    accion=acc,
                )
            )
        return ValidarFormatoToolOutput(
            valido=False,
            status=StatusValidacionEnum.PENDIENTE,
            titulo_sanitizado=sanit.get("titulo_sanitizado"),
            texto_sanitizado=sanit.get("texto_sanitizado"),
            hallazgos=hallazgos_err,
            longitud_texto=len(texto_efectivo_sin_marcadores(texto_str)),
            tags_count=len(tags_objetos),
        )

    resultado = validar_texto_y_estructura_post_duplicados(articulo)

    hallazgos = [
        HallazgoTool(
            severidad=f.get("severity", "Ajuste"),
            campo=f.get("field", "texto"),
            descripcion=f.get("description", ""),
            accion=f.get("action", ""),
        )
        for f in resultado.get("findings", [])
    ]

    raw_status = resultado.get("status", "Pendiente")
    try:
        status_enum = StatusValidacionEnum(raw_status)
    except ValueError:
        status_enum = StatusValidacionEnum.PENDIENTE

    es_valido = status_enum != StatusValidacionEnum.PENDIENTE

    return ValidarFormatoToolOutput(
        valido=es_valido,
        status=status_enum,
        titulo_sanitizado=resultado.get("titulo_sanitizado"),
        texto_sanitizado=resultado.get("texto_sanitizado"),
        hallazgos=hallazgos,
        longitud_texto=resultado.get("longitud_texto", 0),
        tags_count=resultado.get("tags_count", 0),
    )
