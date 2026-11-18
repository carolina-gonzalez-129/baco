"""
Modulo que se utiliza en buscar_duplicados para evitar falsos positivos en texto, trigramas y embeddings.
Evita q se consideren duplicados articulos con temas, formatos o paises diferentes
ej localizacion bolivia sino me sale como similar a localizacion ecuador, pero son paises distintos y la
diapositiva difiere
circuitos opuestos ej cobros vs pagos o compras vs ventas
webinars de temas distintos
fases de proyecto distitno

"""

import re

JURISDICCIONES: dict[str, set[str]] = {
    "AR": {"argentina", "afip", "arba", "agip", "iibb", "cuit", "cae"},
    "PE": {"peru", "perú", "sunat", "ple", "detracciones", "detraccion", "detracción", "ruc"},
    "CO": {"colombia", "dian", "exogena", "exógena"},
    "MX": {"mexico", "méxico", "sat", "cfdi"},
    "PY": {"paraguay", "marangatu", "paraguayapp"},
    "UY": {"uruguay", "dgi", "uruguayapp"},
    "CL": {"chile", "sii"},
    "BO": {"bolivia"},
    "EC": {"ecuador", "sri"},
    "BR": {"brasil", "brazil"},
}

# Siglas de organismos que coinciden con palabras comunes ("sin", "set").
# Solo cuentan en el texto original y en MAYÚSCULAS (SIN = Bolivia, SET = Paraguay).
SIGLAS_AMBIGUAS: dict[str, set[str]] = {
    "BO": {"SIN"},
    "PY": {"SET"},
}

CIRCUITOS_OPUESTOS: list[tuple[set[str], set[str]]] = [
    ({"compras", "compra", "proveedor", "proveedores"}, {"ventas", "venta", "cliente", "clientes"}),
    ({"cobro", "cobros", "ingreso", "ingresos"}, {"pago", "pagos", "egreso", "egresos"}),
    ({"transaccion", "transacciones", "transacción"}, {"informe", "informes", "reporte", "reportes"}),
    ({"origen"}, {"destino"}),
    ({"alta", "crear", "creacion", "creación"}, {"baja", "eliminar", "eliminacion", "eliminación"}),
    ({"importar", "importacion", "importación"}, {"exportar", "exportacion", "exportación"}),
    ({"retencion", "retenciones", "retención"}, {"percepcion", "percepciones", "percepción"}),
]

FASES_PROYECTO: set[str] = {
    "diseno", "diseño", "proyecto start", "start", "ejecucion", "ejecución",
    "cierre", "alcance", "planificacion", "planificación", "capacitacion", "capacitación"
}

PREFIJOS_FORMATO: set[str] = {
    "webinar", "capacitacion", "capacitación", "grabacion", "grabación",
    "taller", "meetup", "video", "readme", "modulo", "módulo"
}


def normalizar_con_postgres(cur, texto: str) -> str:
    if not texto or not texto.strip():
        return ""
    cur.execute("SELECT normalizar_texto(%s);", (texto,))
    row = cur.fetchone()
    if not row:
        return ""
    return (row[0] if isinstance(row, (tuple, list)) else row.get("normalizar_texto", "")) or ""


def _tokenizar(texto: str) -> set[str]:
    """Tokeniza ignorando puntuación (ej. "afip?" -> "afip")."""
    return set(re.findall(r"\w+", texto.lower())) if texto else set()


def detectar_jurisdiccion(tokens_o_texto: str | set[str], texto_raw: str = "") -> str | None:
    if isinstance(tokens_o_texto, set):
        tokens = {t.lower() for t in tokens_o_texto}
    else:
        tokens = _tokenizar(tokens_o_texto)

    for pais, keywords in JURISDICCIONES.items():
        if tokens & keywords:
            return pais

    # Siglas ambiguas: solo sobre el texto original, respetando mayúsculas.
    if texto_raw:
        tokens_raw = set(re.findall(r"\w+", texto_raw))
        for pais, siglas in SIGLAS_AMBIGUAS.items():
            if tokens_raw & siglas:
                return pais
    return None


def detectar_jurisdicciones(tokens_o_texto: str | set[str], texto_raw: str = "") -> set[str]:
    """Como detectar_jurisdiccion, pero devuelve TODOS los países mencionados
    (ej. "Localización Brasil: diferencias con Argentina" -> {"BR", "AR"})."""
    if isinstance(tokens_o_texto, set):
        tokens = {t.lower() for t in tokens_o_texto}
    else:
        tokens = _tokenizar(tokens_o_texto)
    paises = {pais for pais, keywords in JURISDICCIONES.items() if tokens & keywords}
    if texto_raw:
        tokens_raw = set(re.findall(r"\w+", texto_raw))
        paises |= {pais for pais, siglas in SIGLAS_AMBIGUAS.items() if tokens_raw & siglas}
    return paises


def son_semanticas_divergentes(
        cand_normalizado: str,
        cons_normalizada: str,
        cand_raw: str = "",
        cons_raw: str = "",
        cand_texto: str = "",
        cons_texto: str = ""
) -> bool:

    if not cand_normalizado or not cons_normalizada:
        return False

    tokens_cand = _tokenizar(cand_normalizado)
    tokens_cons = _tokenizar(cons_normalizada)

    paises_cand = detectar_jurisdicciones(tokens_cand, cand_raw)
    paises_cons = detectar_jurisdicciones(tokens_cons, cons_raw)
    if not paises_cand and cand_texto:
        paises_cand = detectar_jurisdicciones(_tokenizar(cand_texto[:1000]), cand_texto[:1000])
    if not paises_cons and cons_texto:
        paises_cons = detectar_jurisdicciones(_tokenizar(cons_texto[:1000]), cons_texto[:1000])

    # Divergen si cada uno menciona algún país que el otro no
    # (ej. {AR, BR} vs {AR, CL}: comparten Argentina pero Brasil != Chile).
    if (paises_cand - paises_cons) and (paises_cons - paises_cand):
        return True

    for grupo_a, grupo_b in CIRCUITOS_OPUESTOS:
        cand_en_a = bool(tokens_cand & grupo_a)
        cand_en_b = bool(tokens_cand & grupo_b)
        cons_en_a = bool(tokens_cons & grupo_a)
        cons_en_b = bool(tokens_cons & grupo_b)
        if (cand_en_a and cons_en_b and not (cand_en_b or cons_en_a)) or \
                (cand_en_b and cons_en_a and not (cand_en_a or cons_en_b)):
            return True

    # Títulos casi idénticos que difieren únicamente en su número de versión/nivel/error (ej. Nivel 1 vs Nivel 2, Error 600 vs 259)
    nums_cand = set(re.findall(r"\b(?:f?\d+)\b", cand_normalizado.lower()))
    nums_cons = set(re.findall(r"\b(?:f?\d+)\b", cons_normalizada.lower()))
    if nums_cand and nums_cons and nums_cand != nums_cons:
        palabras_cand = tokens_cand - nums_cand
        palabras_cons = tokens_cons - nums_cons
        if len(palabras_cand & palabras_cons) >= 3 and len(palabras_cand ^ palabras_cons) <= 1:
            return True

    cand_tit = cand_raw or cand_normalizado
    cons_tit = cons_raw or cons_normalizada
    for sep in (":", "-"):
        if sep in cand_tit and sep in cons_tit:
            partes_cand = [p.strip() for p in cand_tit.split(sep) if p.strip()]
            partes_cons = [p.strip() for p in cons_tit.split(sep) if p.strip()]
            if len(partes_cand) > 1 and len(partes_cons) > 1:
                tokens_pref_cand = set(partes_cand[0].lower().split())
                tokens_pref_cons = set(partes_cons[0].lower().split())

                if (tokens_pref_cand & PREFIJOS_FORMATO) and (tokens_pref_cons & PREFIJOS_FORMATO):
                    suf_cand = sep.join(partes_cand[1:]).strip().lower()
                    suf_cons = sep.join(partes_cons[1:]).strip().lower()
                    tokens_suf_cand = set(suf_cand.split())
                    tokens_suf_cons = set(suf_cons.split())

                    if tokens_suf_cand != tokens_suf_cons:
                        pais_suf_cand = detectar_jurisdiccion(tokens_suf_cand)
                        pais_suf_cons = detectar_jurisdiccion(tokens_suf_cons)
                        if (pais_suf_cand or pais_suf_cons) and pais_suf_cand != pais_suf_cons:
                            return True

                        palabras_vacias = {"de", "la", "el", "en", "y", "a", "para", "modulo", "módulo", "app", "con", "por"}
                        clave_cand = tokens_suf_cand - palabras_vacias
                        clave_cons = tokens_suf_cons - palabras_vacias
                        if clave_cand and clave_cons and not (clave_cand & clave_cons):
                            return True

    if "-" in cand_tit and "-" in cons_tit:
        partes_cand = [p.strip() for p in cand_tit.split("-") if p.strip()]
        partes_cons = [p.strip() for p in cons_tit.split("-") if p.strip()]
        if len(partes_cand) > 1 and len(partes_cons) > 1:
            sufijo_cand = partes_cand[-1].lower()
            sufijo_cons = partes_cons[-1].lower()
            if sufijo_cand != sufijo_cons:
                if (any(f in sufijo_cand for f in FASES_PROYECTO) or
                        any(f in sufijo_cons for f in FASES_PROYECTO)):
                    prefijo_cand = "-".join(partes_cand[:-1]).strip().lower()
                    prefijo_cons = "-".join(partes_cons[:-1]).strip().lower()
                    if prefijo_cand == prefijo_cons:
                        return True

    return False
