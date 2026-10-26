import re
from typing import Any
from baco.server.schemas.articulo import ArticuloSchema
from baco.server.config_limites import (
    TEXTO_MAX,
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
    TAGS_MIN,
    TAGS_PLANTILLAS_PERMITIDAS,
)

def _finding(severity: str, field: str, description: str, action: str) -> dict[str, str]:
    return {
        "severity": severity,
        "field": field,
        "description": description,
        "action": action
    }

# ==============================================================================
# PATRONES Y REGEX DEL CATÁLOGO PII / SECRETOS
# ==============================================================================

# 1. CBU / CVU (22 dígitos exactos)
RE_CBU = re.compile(r"(?<!\d)\b(?P<cbu>\d{8}[ -]?\d{14})\b(?!\d)")

# 2. Tarjetas de crédito / débito (PAN: 15 o 16 dígitos, prefijos 4, 51-55, 34/37)
RE_TARJETA_AGRUPADA = re.compile(
    r"(?<![\w/.-])\b(?P<pan>"
    r"4\d{3}[ -]\d{4}[ -]\d{4}[ -]\d{4}"          # Visa (16 dígitos: 4-4-4-4)
    r"|5[1-5]\d{2}[ -]\d{4}[ -]\d{4}[ -]\d{4}"    # Mastercard (16 dígitos: 4-4-4-4)
    r"|3[47]\d{2}[ -]\d{6}[ -]\d{5}"             # Amex (15 dígitos: 4-6-5)
    r")\b(?![\w/.-])"
)
RE_TARJETA_CONTIGUA = re.compile(
    r"(?<![\w/.-])\b(?P<pan>"
    r"4\d{15}"                                    # Visa (16 dígitos)
    r"|5[1-5]\d{14}"                              # Mastercard (16 dígitos)
    r"|3[47]\d{13}"                               # Amex (15 dígitos)
    r")\b(?![\w/.-])"
)
RE_CONTEXTO_TARJETA = re.compile(r"(?i)\b(?:tarjeta|card|visa|mastercard|amex|titular|vencimiento|venc)\b")

# 3. CUIT / CUIL de personas físicas (prefijos 20, 23, 24, 27 con dígito verificador)
# Prefijos 30, 33 y 34 (empresas/instituciones) no se tocan
RE_CUIT = re.compile(r"(?<!\d)\b(?P<cuit>(?:20|23|24|27)-?\d{8}-?\d)\b(?!\d)")

# Patrón contextual para CUIL/CUIT de personas físicas
RE_CUIL_CONTEXTO = re.compile(
    r"(?i)(?P<clave>\b(?:cuil|cuit)(?:\s+(?:nro|n[uú]mero))?[\s:=#]+)"
    r"(?P<valor>(?:20|23|24|27)[-.\s]?\d{8}[-.\s]?\d)\b"
)

# 4. DNI (Solo con "DNI" o "documento" pegado al número de 7 u 8 dígitos)
RE_DNI = re.compile(
    r"(?i)(?P<clave>\b(?:dni|d\.n\.i\.|documento(?:\s+(?:nacional|nro|n[uú]mero))?)\b[\s:=#]+)"
    r"(?P<valor>\d{1,2}(?:\.\d{3}\.\d{3}|\d{6,7}))\b"
)

# 5. CVV (Solo con "cvv", "cvc" o "código de seguridad" pegado a 3 o 4 dígitos)
RE_CVV = re.compile(
    r"(?i)(?P<clave>\b(?:cvv|cvc|c[oó]digo\s+de\s+seguridad|c[oó]d\.?\s+seguridad)\b[\s:=#]+)"
    r"(?P<valor>\d{3,4})\b"
)

# 6. Credenciales y secretos
# A. Tokens con formato propio y fijo
RE_AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
RE_GITHUB_TOKEN = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b")
RE_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
RE_BEARER = re.compile(r"(?i)(?P<clave>\bBearer\s+)(?P<valor>[A-Za-z0-9_\-\.~+/]{20,}=*)")

# B. Par clave: valor / JSON
RE_PASSWORD_KV = re.compile(
    r"""(?i)(?P<clave>["']?\b(?:password|contrase[ñn]a|clave|pwd|secret|passwd)\b["']?\s*[:=]\s*["']?)(?P<valor>[^\s"',;}{]+)(?P<cierre>["']?)"""
)

# Placeholders y descripciones exentas
PLACEHOLDERS_EXENTOS = frozenset({
    "xxxx", "xxxxxx", "********", "****", "{{token}}", "<tu_clave>", "<tu-clave>",
    "tu_clave", "tu-clave", "tu_password", "tu_contraseña", "tu_contrasena",
    "<password>", "<contraseña>", "<contrasena>", "changeme", "password", "contraseña",
    "contrasena", "123456", "1234", "admin", "secret", "clave", "none", "null", "undefined"
})

# 7. Emails
RE_EMAIL = re.compile(r"\b(?P<local>[\w\.-]+)@(?P<domain>[\w\.-]+\.\w+)\b")

DOMINIOS_PERSONALES = frozenset({
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "live.com", "icloud.com",
    "hotmail.es", "yahoo.com.ar", "outlook.es"
})

ALLOWLIST_BUZONES_GENERICOS = frozenset({
    "soporte", "info", "ventas", "administracion", "administración", "mesa.ayuda",
    "contacto", "ayuda", "consultas", "facturacion", "facturación", "postventa",
    "operaciones", "rrhh", "rr.hh", "recursos.humanos", "comercial", "pagos", "cobranzas"
})

DOMINIOS_EMAIL_EJEMPLO = {
    "ejemplo.com", "ejemplo.org", "ejemplo.com.ar", "example.com", "example.org",
    "finneg.com", "finnegans.com", "finnegans.com.ar",
}

# Allowlist de CUITs sintéticos/ejemplo en instructivos
CUITS_EJEMPLO = {"20123456789", "30000000000", "20000000001", "27000000006"}

RE_TICKETS = re.compile(r"\b(ticket|incidente|caso|jira|tarea)\s*#?\d+\b", re.IGNORECASE)
RE_URL = re.compile(r"https?://([^\s/:?#]+)", re.IGNORECASE)
RE_URL_COMPLETA = re.compile(r"https?://([^\s/:?#]+)(?:[^\s.,;)]*)", re.IGNORECASE)

ETIQUETAS_HOST_INTERNO = {"dev", "stage", "staging", "qa", "test", "local", "localhost", "internal", "interno"}
SUFIJOS_HOST_INTERNO = (".test", ".local", ".internal", ".localhost")
RE_IP_PRIVADA = re.compile(r"^(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|127\.\d+\.\d+\.\d+)$")

RE_TITULO_REDUNDANTE = re.compile(r"^\s*(?:cómo|como|pasos para|como hacer para)\b", re.IGNORECASE)
RE_TITULO_ERROR = re.compile(r"\berror\b", re.IGNORECASE)


# ==============================================================================
# ALGORITMOS DE VALIDACIÓN DETERMINISTAS
# ==============================================================================

def _pasa_luhn(numero: str) -> bool:
    """Verifica el algoritmo de Luhn para números de tarjeta."""
    digitos = [int(d) for d in re.sub(r"\D", "", numero)]
    if not digitos:
        return False
    checksum = 0
    reverso = digitos[::-1]
    for i, d in enumerate(reverso):
        if i % 2 == 1:
            doble = d * 2
            checksum += doble - 9 if doble > 9 else doble
        else:
            checksum += d
    return checksum % 10 == 0


def _validar_cbu_ponderador(cadena: str, ponderadores: list[int]) -> int:
    """Calcula el dígito verificador para un bloque de CBU."""
    suma = sum(int(dig) * pond for dig, pond in zip(cadena, ponderadores))
    resto = suma % 10
    return (10 - resto) % 10


def _es_cbu_valido(cbu_raw: str) -> bool:
    """Valida los 22 dígitos del CBU bancario argentino con sus dos dígitos verificadores."""
    digitos = re.sub(r"\D", "", cbu_raw)
    if len(digitos) != 22:
        return False
    # No puede ser secuencia uniforme (ej. todos ceros)
    if re.fullmatch(r"(\d)\1{21}", digitos):
        return False

    bloque1 = digitos[:7]
    dv1 = int(digitos[7])
    if _validar_cbu_ponderador(bloque1, [7, 1, 3, 9, 7, 1, 3]) != dv1:
        return False

    bloque2 = digitos[8:21]
    dv2 = int(digitos[21])
    if _validar_cbu_ponderador(bloque2, [3, 9, 7, 1, 3, 9, 7, 1, 3, 9, 7, 1, 3]) != dv2:
        return False

    return True


def _es_cuit_valido(cuit_raw: str) -> bool:
    """Valida el CUIT/CUIL con el algoritmo oficial de AFIP."""
    digitos = re.sub(r"\D", "", cuit_raw)
    if len(digitos) != 11:
        return False
    if digitos in CUITS_EJEMPLO or re.fullmatch(r"\d{2}0{8}\d", digitos):
        return False  # CUITs ficticios de ejemplo se omiten
    if re.fullmatch(r"(\d)\1{10}", digitos):
        return False

    coeficientes = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(d) * c for d, c in zip(digitos[:10], coeficientes))
    resto = suma % 11
    if resto == 0:
        dv = 0
    elif resto == 1:
        if digitos.startswith("20"):
            dv = 9
        elif digitos.startswith("27"):
            dv = 4
        else:
            dv = 0
    else:
        dv = 11 - resto

    return dv == int(digitos[10])


def _es_host_interno(host: str) -> bool:
    host = host.lower().rstrip(".")
    if RE_IP_PRIVADA.match(host) or host.endswith(SUFIJOS_HOST_INTERNO):
        return True
    return bool(set(re.split(r"[.\-]", host)) & ETIQUETAS_HOST_INTERNO)


def _hay_url_interna(contenido: str) -> bool:
    return any(_es_host_interno(m.group(1)) for m in RE_URL.finditer(contenido))


def _hay_cuit_real(contenido: str) -> bool:
    for m in RE_CUIL_CONTEXTO.finditer(contenido):
        val = m.group("valor")
        digitos = re.sub(r"\D", "", val)
        if digitos in CUITS_EJEMPLO or re.fullmatch(r"\d{2}0{8}\d", digitos):
            continue
        return True
    for m in RE_CUIT.finditer(contenido):
        val = m.group("cuit")
        if _es_cuit_valido(val):
            return True
    return False


def _hay_email_real(contenido: str) -> bool:
    for m in RE_EMAIL.finditer(contenido):
        local = m.group("local")
        domain = m.group("domain")
        if _es_email_personal_o_nominal(local, domain):
            return True
    return False


# ==============================================================================
# SANITIZACIÓN DETERMINISTA
# ==============================================================================

def _sanitizar_cbu(contenido: str) -> tuple[str, int]:
    reemplazos = 0
    def _sub(m):
        nonlocal reemplazos
        val = m.group("cbu")
        if _es_cbu_valido(val):
            reemplazos += 1
            return "[CBU_OCULTO]"
        return m.group(0)
    return RE_CBU.sub(_sub, contenido), reemplazos


def _sanitizar_tarjetas(contenido: str) -> tuple[str, int]:
    reemplazos = 0

    # 1. Agrupadas
    def _sub_agrupada(m):
        nonlocal reemplazos
        pan = m.group("pan")
        if _pasa_luhn(pan):
            reemplazos += 1
            return "[TARJETA_OCULTA]"
        return m.group(0)

    contenido = RE_TARJETA_AGRUPADA.sub(_sub_agrupada, contenido)

    # 2. Contiguas (requieren contexto cercano de hasta 30 caracteres)
    def _sub_contigua(m):
        nonlocal reemplazos
        pan = m.group("pan")
        inicio, fin = m.span()
        contexto_previo = contenido[max(0, inicio - 35):inicio]
        contexto_post = contenido[fin:min(len(contenido), fin + 35)]
        tiene_contexto = bool(
            RE_CONTEXTO_TARJETA.search(contexto_previo) or RE_CONTEXTO_TARJETA.search(contexto_post)
        )
        if tiene_contexto and _pasa_luhn(pan):
            reemplazos += 1
            return "[TARJETA_OCULTA]"
        return m.group(0)

    contenido = RE_TARJETA_CONTIGUA.sub(_sub_contigua, contenido)
    return contenido, reemplazos


def _sanitizar_cuits(contenido: str) -> tuple[str, int]:
    reemplazos = 0

    # 1. Detección contextual (con palabra clave "CUIL"/"CUIT")
    def _sub_contexto(m):
        nonlocal reemplazos
        clave = m.group("clave")
        val = m.group("valor")
        if "[CUIT_OCULTO]" in val:
            return m.group(0)
        digitos = re.sub(r"\D", "", val)
        if digitos in CUITS_EJEMPLO or re.fullmatch(r"\d{2}0{8}\d", digitos):
            return m.group(0)
        reemplazos += 1
        return f"{clave}[CUIT_OCULTO]"

    contenido = RE_CUIL_CONTEXTO.sub(_sub_contexto, contenido)

    # 2. Detección aislada de CUIT/CUIL
    def _sub_cuit(match):
        nonlocal reemplazos
        val = match.group("cuit")
        if "[CUIT_OCULTO]" in val:
            return match.group(0)
        if _es_cuit_valido(val):
            reemplazos += 1
            return "[CUIT_OCULTO]"
        return match.group(0)

    contenido = RE_CUIT.sub(_sub_cuit, contenido)
    return contenido, reemplazos


def _sanitizar_dni(contenido: str) -> tuple[str, int]:
    reemplazos = 0
    def _sub(m):
        nonlocal reemplazos
        clave = m.group("clave")
        val = m.group("valor")
        # Si ya es un marcador ignorar
        if "[DOCUMENTO_OCULTO]" in val:
            return m.group(0)
        reemplazos += 1
        return f"{clave}[DOCUMENTO_OCULTO]"
    return RE_DNI.sub(_sub, contenido), reemplazos


def _sanitizar_cvv(contenido: str) -> tuple[str, int]:
    reemplazos = 0
    def _sub(m):
        nonlocal reemplazos
        clave = m.group("clave")
        reemplazos += 1
        return f"{clave}[CVV_OCULTO]"
    return RE_CVV.sub(_sub, contenido), reemplazos


def _sanitizar_credenciales(contenido: str) -> tuple[str, int]:
    reemplazos = 0

    # AWS
    def _sub_aws(m):
        nonlocal reemplazos
        reemplazos += 1
        return "[TOKEN_OCULTO]"
    contenido = RE_AWS_KEY.sub(_sub_aws, contenido)

    # GitHub
    def _sub_gh(m):
        nonlocal reemplazos
        reemplazos += 1
        return "[TOKEN_OCULTO]"
    contenido = RE_GITHUB_TOKEN.sub(_sub_gh, contenido)

    # Bearer
    def _sub_bearer(m):
        nonlocal reemplazos
        clave = m.group("clave")
        reemplazos += 1
        return f"{clave}[TOKEN_OCULTO]"
    contenido = RE_BEARER.sub(_sub_bearer, contenido)

def _es_email_personal_o_nominal(local: str, domain: str) -> bool:
    """Evalúa si un correo debe ser reemplazado.
    
    Limitación documentada: la detección de buzón nominal es heurística
    y puede fallar en ambos sentidos.
    """
    dom = domain.lower()
    loc = local.lower()

    # Dominios de ejemplo oficiales nunca se tocan
    if dom in DOMINIOS_EMAIL_EJEMPLO:
        return False

    # 1. Dominios personales conocidos (gmail, hotmail, outlook, yahoo, etc.)
    if dom in DOMINIOS_PERSONALES:
        return True

    # 2. Si el buzón está en la allowlist de buzones genéricos/institucionales, no se toca
    if loc in ALLOWLIST_BUZONES_GENERICOS:
        return False

    # 3. Buzón nominal heurístico:
    # - Formato nombre.apellido (ej. juan.perez)
    # - Formato inicial+apellido con al menos 4 letras posteriores (ej. jperez, mrodriguez)
    if re.fullmatch(r"[a-z]{2,}\.[a-z]{2,}", loc):
        return True
    if re.fullmatch(r"[a-z][a-z]{3,}", loc) and "." not in loc:
        # Si no es una palabra genérica reservada
        return True

    return False


def _sanitizar_emails(contenido: str) -> tuple[str, int]:
    reemplazos = 0
    def _sub_email(m):
        nonlocal reemplazos
        local = m.group("local")
        domain = m.group("domain")
        if _es_email_personal_o_nominal(local, domain):
            reemplazos += 1
            return "usuario@ejemplo.com"
        return m.group(0)
    return RE_EMAIL.sub(_sub_email, contenido), reemplazos


def _evaluar_entropia_alta(s: str) -> bool:
    """Evalúa si un valor tiene alta entropía (12+ caracteres y mezcla de mayúsculas, minúsculas y números)."""
    if len(s) < 12:
        return False
    tiene_mayus = bool(re.search(r"[A-Z]", s))
    tiene_minus = bool(re.search(r"[a-z]", s))
    tiene_num = bool(re.search(r"\d", s))
    return tiene_mayus and tiene_minus and tiene_num


def _sanitizar_credenciales(contenido: str) -> tuple[str, dict[str, int]]:
    """Sanitiza credenciales en tres niveles:
    - Ocultar (alta entropía, tokens JWT/AWS/GitHub/Bearer largo) -> [CONTRASENA_OCULTA] / [TOKEN_OCULTO]
    - Ambiguos -> solo aviso (no se reemplazan)
    - Descartados por placeholder -> no se tocan
    """
    ocultas = 0
    ambiguas = 0
    placeholders = 0

    # 1. AWS Keys
    def _sub_aws(m):
        nonlocal ocultas
        ocultas += 1
        return "[TOKEN_OCULTO]"
    contenido = RE_AWS_KEY.sub(_sub_aws, contenido)

    # 2. GitHub Tokens
    def _sub_gh(m):
        nonlocal ocultas
        ocultas += 1
        return "[TOKEN_OCULTO]"
    contenido = RE_GITHUB_TOKEN.sub(_sub_gh, contenido)

    # 3. JWT
    def _sub_jwt(m):
        nonlocal ocultas
        ocultas += 1
        return "[TOKEN_OCULTO]"
    contenido = RE_JWT.sub(_sub_jwt, contenido)

    # 4. Bearer tokens largos
    def _sub_bearer(m):
        nonlocal ocultas
        clave = m.group("clave")
        ocultas += 1
        return f"{clave}[TOKEN_OCULTO]"
    contenido = RE_BEARER.sub(_sub_bearer, contenido)

    # 5. Pares clave: valor (password, secret, etc.)
    def _sub_pwd(m):
        nonlocal ocultas, ambiguas, placeholders
        clave = m.group("clave")
        cierre = m.group("cierre") or ""
        val = m.group("valor").strip()

        # Ya sanitizado previamente
        if "[CONTRASENA_OCULTA]" in val or "[TOKEN_OCULTO]" in val:
            return m.group(0)

        val_lower = val.lower().strip("<>{}'\"")
        # Nivel 1: Placeholders y descripciones exentas
        if val_lower in PLACEHOLDERS_EXENTOS or re.fullmatch(r"x+|\*+", val_lower):
            placeholders += 1
            return m.group(0)

        # Nivel 2: Alta entropía -> se oculta
        if _evaluar_entropia_alta(val):
            ocultas += 1
            return f"{clave}[CONTRASENA_OCULTA]{cierre}"

        # Nivel 3: Ambiguo (valor con forma de contraseña corta o simple)
        if len(val) >= 4:
            ambiguas += 1
            # Solo aviso, sin reemplazo

        return m.group(0)

    contenido = RE_PASSWORD_KV.sub(_sub_pwd, contenido)

    return contenido, {
        "credenciales_ocultas": ocultas,
        "credenciales_ambiguas": ambiguas,
        "descartados_por_placeholder": placeholders,
    }


def _sanitizar_urls_internas(contenido: str) -> tuple[str, int]:
    # URLs e IPs internas: Fuera del alcance de la primera versión. No se reemplazan.
    return contenido, 0


def _limpiar_texto_sensible(contenido: str) -> tuple[str, dict[str, int]]:
    """Aplica autosanitización en estricto orden de especificidad."""
    txt, cbu_cnt = _sanitizar_cbu(contenido)
    txt, pan_cnt = _sanitizar_tarjetas(txt)
    txt, cuit_cnt = _sanitizar_cuits(txt)
    txt, dni_cnt = _sanitizar_dni(txt)
    txt, cvv_cnt = _sanitizar_cvv(txt)
    txt, cred_stats = _sanitizar_credenciales(txt)
    txt, email_cnt = _sanitizar_emails(txt)
    txt, url_cnt = _sanitizar_urls_internas(txt)

    detalles = {
        "cbu": cbu_cnt,
        "tarjeta": pan_cnt,
        "cuit": cuit_cnt,
        "dni": dni_cnt,
        "cvv": cvv_cnt,
        "credenciales_ocultas": cred_stats["credenciales_ocultas"],
        "credenciales_ambiguas": cred_stats["credenciales_ambiguas"],
        "descartados_por_placeholder": cred_stats["descartados_por_placeholder"],
        "emails": email_cnt,
        "urls": url_cnt,
    }
    return txt, detalles


def sanitizar_borrador(
    texto: str = "",
    titulo: str = "",
    sanitizar_redundancia_titulo: bool = True,
) -> dict[str, Any]:
    """Autosanitiza el contenido y el título reemplazando PII y secretos por marcadores genéricos."""
    texto_limpio = (texto or "").strip()
    titulo_limpio = (titulo or "").strip()

    texto_sanitizado, d_texto = _limpiar_texto_sensible(texto_limpio)
    titulo_sanitizado, d_titulo = _limpiar_texto_sensible(titulo_limpio)

    detalles = {k: d_texto[k] + d_titulo[k] for k in d_texto}
    
    # Solo suman al conteo de reemplazos los efectivamente ocultados
    reemplazos_total = (
        detalles["cbu"]
        + detalles["tarjeta"]
        + detalles["cuit"]
        + detalles["dni"]
        + detalles["cvv"]
        + detalles["credenciales_ocultas"]
        + detalles["emails"]
        + detalles["urls"]
    )

    if sanitizar_redundancia_titulo and RE_TITULO_REDUNDANTE.search(titulo_sanitizado):
        titulo_sanitizado = RE_TITULO_REDUNDANTE.sub("", titulo_sanitizado).strip()
        if titulo_sanitizado and titulo_sanitizado[0].islower():
            titulo_sanitizado = titulo_sanitizado[0].upper() + titulo_sanitizado[1:]

    aviso_privacidad = None
    partes_aviso = []

    if reemplazos_total > 0:
        partes = []
        nombres_tipos = {
            "cbu": "CBU/CVU bancario",
            "tarjeta": "número de tarjeta",
            "cuit": "CUIT/CUIL personal",
            "dni": "documento de identidad (DNI)",
            "cvv": "código de seguridad (CVV)",
            "credenciales_ocultas": "credencial/token secreto",
            "emails": "dirección de correo personal",
        }
        for clave, nombre in nombres_tipos.items():
            cant = detalles.get(clave, 0)
            if cant > 0:
                partes.append(f"{cant} {nombre}{'s' if cant > 1 else ''}")

        partes_aviso.append(
            f"Por seguridad, se detectaron y reemplazaron automáticamente datos de identificación "
            f"personal o secretos ({', '.join(partes)}) por marcadores protegidos para preservarte."
        )

    # Nivel 3 de credenciales: Solo aviso, sin reemplazo para ambiguos
    if detalles.get("credenciales_ambiguas", 0) > 0:
        cant_amb = detalles["credenciales_ambiguas"]
        partes_aviso.append(
            f"Aviso: El texto parece contener {cant_amb} posible(s) contraseña(s) o valor(es) sensible(s) no ofuscado(s). "
            f"Si son ejemplos reales, recordá reemplazarlos por valores genéricos."
        )

    if partes_aviso:
        aviso_privacidad = " ".join(partes_aviso)

    return {
        "texto_sanitizado": texto_sanitizado,
        "titulo_sanitizado": titulo_sanitizado,
        "reemplazos_total": reemplazos_total,
        "detalles": detalles,
        "aviso_privacidad": aviso_privacidad,
    }


def validar_texto_y_estructura_post_duplicados(articulo: ArticuloSchema) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    texto_limpio = (articulo.texto or "").strip()
    titulo_limpio = (articulo.titulo or "").strip()

    # 1. Autosanitización inmediata de PII y fórmulas redundantes
    datos_sanitizados = sanitizar_borrador(texto=texto_limpio, titulo=titulo_limpio)
    texto_sanitizado = datos_sanitizados["texto_sanitizado"]
    titulo_sanitizado = datos_sanitizados["titulo_sanitizado"]

    from baco.server.services.orquestador.recursos_service import texto_efectivo_sin_marcadores

    articulo.texto = texto_sanitizado
    articulo.titulo = titulo_sanitizado
    longitud_texto = len(texto_efectivo_sin_marcadores(texto_sanitizado))

    # 2. Si se reemplazaron PIIs o secretos, avisar al usuario de forma no bloqueante para preservarle
    if datos_sanitizados["reemplazos_total"] > 0:
        aviso = datos_sanitizados.get("aviso_privacidad") or (
            "Por seguridad, se detectaron y reemplazaron automáticamente datos de identificación "
            "personal o secretos por marcadores protegidos para preservarte."
        )
        findings.append(_finding(
            severity="Sugerencia",
            field="texto",
            description=aviso,
            action="Revisar que el contenido conserve el sentido técnico tras el reemplazo automático."
        ))
    elif datos_sanitizados.get("detalles", {}).get("credenciales_ambiguas", 0) > 0:
        aviso = datos_sanitizados.get("aviso_privacidad")
        findings.append(_finding(
            severity="Sugerencia",
            field="texto",
            description=aviso,
            action="Revisar si los valores sospechosos son reales y reemplazarlos por valores de ejemplo si corresponde."
        ))

    contenido_completo = f"{titulo_sanitizado} {texto_sanitizado}"

    if RE_TICKETS.search(contenido_completo):
        findings.append(_finding(
            severity="Requiere ajuste",
            field="texto",
            description="Se detectaron referencias a tickets o números de incidencias internas (ej. 'Ticket #1234').",
            action="Describir el problema en términos funcionales orientados al usuario final sin códigos de ticket."
        ))

    if _hay_url_interna(contenido_completo):
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description="Se detectaron URLs de entornos internos, pruebas o IPs privadas.",
            action="Remover o reemplazar por URLs genéricas o de documentación oficial."
        ))

    # si pusieron titulo chequeo q no arranque con como hacer y q no tenga error sin comillas
    if titulo_limpio:
        if RE_TITULO_REDUNDANTE.search(titulo_limpio):
            findings.append(_finding(
                severity="Requiere ajuste",
                field="titulo",
                description="El título comienza con fórmulas redundantes ('Cómo...', 'Pasos para...').",
                action="Iniciar directamente con un verbo en infinitivo (ej. 'Emitir...', 'Configurar...') o el proceso directo."
            ))

        # si pusieron error sin comillas tiro sugerencia
        if RE_TITULO_ERROR.search(titulo_sanitizado):
            tiene_comillas = ('"' in titulo_sanitizado or "“" in titulo_sanitizado or "”" in titulo_sanitizado or "'" in titulo_sanitizado)
            if not tiene_comillas and ":" not in titulo_sanitizado:
                findings.append(_finding(
                    severity="Sugerencia",
                    field="titulo",
                    description="El título incluye la palabra 'Error' sin citar el mensaje textual del sistema.",
                    action="Citar el mensaje entre comillas si es literal, o titular con la acción correctiva correspondiente."
                ))

    # largo minimo y maximo segun config_limites y que no queden marcadores tipo
    if longitud_texto < TEXTO_MIN:
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description=f"El texto es muy breve ({longitud_texto} caracteres). Se requieren al menos {TEXTO_MIN} caracteres.",
            action=f"Detallar mejor el problema, pasos a seguir o contexto técnico para superar los {TEXTO_MIN} caracteres."
        ))
    elif longitud_texto > TEXTO_MAX_PERCENTIL_99:
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description=f"El texto excede el límite permitido ({longitud_texto} caracteres recibidos, máximo {TEXTO_MAX_PERCENTIL_99}).",
            action=f"Reducir la extensión del contenido para no superar {TEXTO_MAX_PERCENTIL_99} caracteres."
        ))
    elif re.search(r"\[Indicar[^]]*]", texto_sanitizado, re.IGNORECASE):
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description="Quedan marcadores de información pendiente como '[Indicar...]'.",
            action="Completar o retirar los marcadores antes de publicar."
        ))

    if not articulo.categoria_id:
        findings.append(_finding(
            severity="Bloqueante",
            field="categoria_id",
            description="El artículo debe tener asignada una categoría principal.",
            action="Seleccionar una categoría del catálogo oficial."
        ))

    tags = articulo.tags or []
    slugs_o_nombres = {getattr(t, "slug", None) or getattr(t, "name", str(t)).lower().strip() for t in tags}

    if len(tags) < TAGS_MIN:
        findings.append(_finding(
            severity="Bloqueante",
            field="tags",
            description=f"Se requieren al menos {TAGS_MIN} tags o etiquetas (actualmente tiene {len(tags)}).",
            action=f"Agregar al menos {TAGS_MIN} etiquetas relevantes (ej. 'instructivo', 'facturacion')."
        ))

    if not any(tipo in slugs_o_nombres for tipo in (*TAGS_PLANTILLAS_PERMITIDAS, "instructivos", "solucion")):
        plantillas_fmt = " o ".join(f"'{p}'" for p in TAGS_PLANTILLAS_PERMITIDAS)
        findings.append(_finding(
            severity="Bloqueante",
            field="tags",
            description=f"Falta la etiqueta obligatoria de tipo de plantilla ({plantillas_fmt}).",
            action=f"Incorporar {plantillas_fmt} entre las etiquetas del artículo."
        ))

    # si hay bloqueantes queda pendiente, sino listo
    tiene_bloqueantes = any(f["severity"] == "Bloqueante" for f in findings)
    tiene_ajustes = any(f["severity"] == "Requiere ajuste" for f in findings)

    if tiene_bloqueantes:
        status = "Pendiente"
    elif tiene_ajustes:
        status = "Listo con ajustes sugeridos"
    elif findings:
        status = "Listo con sugerencias"
    else:
        status = "Listo"

    return {
        "id": articulo.id,
        "fase": "fase_2_texto_y_estructura",
        "status": status,
        "titulo": articulo.titulo,
        "titulo_sanitizado": titulo_sanitizado,
        "texto": articulo.texto,
        "texto_sanitizado": texto_sanitizado,
        "aviso_privacidad": datos_sanitizados.get("aviso_privacidad"),
        "categoria_id": articulo.categoria_id,
        "tags_count": len(tags),
        "longitud_texto": longitud_texto,
        "findings": findings,
        "technical_accuracy_verified": False
    }
