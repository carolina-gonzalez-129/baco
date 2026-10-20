import re
from typing import Any
from baco.server.schemas.articulo import ArticuloSchema

def _finding(severity: str, field: str, description: str, action: str) -> dict[str, str]:
    return {
        "severity": severity,
        "field": field,
        "description": description,
        "action": action
    }

RE_CUIT = re.compile(r"\b(?:20|23|24|27|30|33|34)-?\d{8}-?\d\b")
RE_EMAIL = re.compile(r"\b[\w\.-]+@([\w\.-]+\.\w+)\b")
RE_TICKETS = re.compile(r"\b(ticket|incidente|caso|jira|tarea)\s*#?\d+\b", re.IGNORECASE)
RE_URL = re.compile(r"https?://([^\s/:?#]+)", re.IGNORECASE)

CUITS_EJEMPLO = {"20123456789", "30000000000"}
DOMINIOS_EMAIL_EJEMPLO = {"ejemplo.com", "ejemplo.org", "ejemplo.com.ar", "example.com", "example.org"}

ETIQUETAS_HOST_INTERNO = {"dev", "stage", "staging", "qa", "test", "local", "localhost", "internal", "interno"}

SUFIJOS_HOST_INTERNO = (".test", ".local", ".internal", ".localhost")
RE_IP_PRIVADA = re.compile(r"^(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|127\.\d+\.\d+\.\d+)$")


def _hay_cuit_real(contenido: str) -> bool:
    for m in RE_CUIT.finditer(contenido):
        digitos = re.sub(r"\D", "", m.group(0))
        if digitos in CUITS_EJEMPLO:
            continue
        if re.fullmatch(r"\d{2}0{8}\d", digitos):
            continue
        return True
    return False


def _hay_email_real(contenido: str) -> bool:
    for m in RE_EMAIL.finditer(contenido):
        dominio = m.group(1).lower()
        if dominio in DOMINIOS_EMAIL_EJEMPLO:
            continue
        return True
    return False


def _es_host_interno(host: str) -> bool:
    host = host.lower().rstrip(".")
    if RE_IP_PRIVADA.match(host) or host.endswith(SUFIJOS_HOST_INTERNO):
        return True
    return bool(set(re.split(r"[.\-]", host)) & ETIQUETAS_HOST_INTERNO)


def _hay_url_interna(contenido: str) -> bool:
    return any(_es_host_interno(m.group(1)) for m in RE_URL.finditer(contenido))


def _sanitizar_cuits(contenido: str) -> tuple[str, int]:
    reemplazos = 0
    def _sub_cuit(match):
        nonlocal reemplazos
        digitos = re.sub(r"\D", "", match.group(0))
        if digitos in CUITS_EJEMPLO or re.fullmatch(r"\d{2}0{8}\d", digitos):
            return match.group(0)
        reemplazos += 1
        return "20-12345678-9"
    return RE_CUIT.sub(_sub_cuit, contenido), reemplazos


def _sanitizar_emails(contenido: str) -> tuple[str, int]:
    reemplazos = 0
    def _sub_email(match):
        nonlocal reemplazos
        dominio = match.group(1).lower()
        if dominio in DOMINIOS_EMAIL_EJEMPLO:
            return match.group(0)
        reemplazos += 1
        return "usuario@ejemplo.com"
    return RE_EMAIL.sub(_sub_email, contenido), reemplazos


RE_URL_COMPLETA = re.compile(r"https?://([^\s/:?#]+)(?:[^\s.,;)]*)", re.IGNORECASE)


def _sanitizar_urls_internas(contenido: str) -> tuple[str, int]:
    reemplazos = 0
    def _sub_url(match):
        nonlocal reemplazos
        if _es_host_interno(match.group(1)):
            reemplazos += 1
            return "https://ejemplo.finneg.com"
        return match.group(0)
    return RE_URL_COMPLETA.sub(_sub_url, contenido), reemplazos


def _limpiar_texto_sensible(contenido: str) -> tuple[str, int]:
    paso_cuits, c = _sanitizar_cuits(contenido)
    paso_emails, e = _sanitizar_emails(paso_cuits)
    paso_urls, u = _sanitizar_urls_internas(paso_emails)
    return paso_urls, (c + e + u)

##ESTO DEBERIA INVOCARSE DSPS DE CHAT ORQUESTADO PARA Q SE INYECTE A BACO!
def sanitizar_borrador(texto: str = "", titulo: str = "") -> dict[str, Any]:
    texto_limpio = (texto or "").strip()
    titulo_limpio = (titulo or "").strip()

    texto_sanitizado, r_texto = _limpiar_texto_sensible(texto_limpio)
    titulo_sanitizado, r_titulo = _limpiar_texto_sensible(titulo_limpio)

    if RE_TITULO_REDUNDANTE.search(titulo_sanitizado):
        titulo_sanitizado = RE_TITULO_REDUNDANTE.sub("", titulo_sanitizado).strip()
        if titulo_sanitizado and titulo_sanitizado[0].islower():
            titulo_sanitizado = titulo_sanitizado[0].upper() + titulo_sanitizado[1:]

    return {
        "texto_sanitizado": texto_sanitizado,
        "titulo_sanitizado": titulo_sanitizado,
        "reemplazos_total": r_texto + r_titulo
    }



# cosas para validar el titulo
RE_TITULO_REDUNDANTE = re.compile(r"^\s*(?:cómo|como|pasos para|como hacer para)\b", re.IGNORECASE)
RE_TITULO_ERROR = re.compile(r"\berror\b", re.IGNORECASE)


def validar_texto_y_estructura_post_duplicados(articulo: ArticuloSchema) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    texto_limpio = (articulo.texto or "").strip()
    titulo_limpio = (articulo.titulo or "").strip()
    articulo.texto = texto_limpio
    articulo.titulo = titulo_limpio
    longitud_texto = len(texto_limpio)

    # chequeo cuits, mails o tickets para q no queden en la base publica
    contenido_completo = f"{titulo_limpio} {texto_limpio}"

    if _hay_cuit_real(contenido_completo):
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description="Se detectaron CUITs reales o números de identificación tributaria en el contenido.",
            action="Reemplazar por CUITs genéricos o ficticios (ej. '20-12345678-9' o '30-00000000-0') antes de publicar."
        ))

    if _hay_email_real(contenido_completo):
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description="Se detectaron direcciones de correo electrónico en el contenido.",
            action="Remover las casillas personales o reemplazarlas por un correo de ejemplo (ej. 'usuario@ejemplo.com')."
        ))

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
        if RE_TITULO_ERROR.search(titulo_limpio):
            tiene_comillas = ('"' in titulo_limpio or "“" in titulo_limpio or "”" in titulo_limpio or "'" in titulo_limpio)
            if not tiene_comillas and ":" not in titulo_limpio:
                findings.append(_finding(
                    severity="Sugerencia",
                    field="titulo",
                    description="El título incluye la palabra 'Error' sin citar el mensaje textual del sistema.",
                    action="Citar el mensaje entre comillas si es literal, o titular con la acción correctiva correspondiente."
                ))

    # largo minimo y q no queden marcadores tipo
    if longitud_texto < 150:
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description=f"El texto es muy breve ({longitud_texto} caracteres). Se requieren al menos 150 caracteres.",
            action="Detallar mejor el problema, pasos a seguir o contexto técnico."
        ))
    elif re.search(r"\[Indicar[^]]*]", texto_limpio, re.IGNORECASE):
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
            action="Indicar la categoría correspondiente."
        ))

    tags = articulo.tags or []
    slugs_o_nombres = {getattr(t, "slug", None) or getattr(t, "name", str(t)).lower().strip() for t in tags}

    if len(tags) < 2:
        findings.append(_finding(
            severity="Bloqueante",
            field="tags",
            description=f"Se requieren al menos 2 tags o etiquetas (actualmente tiene {len(tags)}).",
            action="Agregar al menos dos etiquetas relevantes (ej. 'instructivo', 'facturacion')."
        ))

    if not any(tipo in slugs_o_nombres for tipo in ("instructivo", "soluciones", "instructivos", "solucion")):
        findings.append(_finding(
            severity="Bloqueante",
            field="tags",
            description="Falta la etiqueta obligatoria de tipo de plantilla ('instructivo' o 'soluciones').",
            action="Incorporar 'instructivo' o 'soluciones' entre las etiquetas del artículo."
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



    datos_sanitizados = sanitizar_borrador(texto=texto_limpio, titulo=titulo_limpio)

    return {
        "id": articulo.id,
        "fase": "fase_2_texto_y_estructura",
        "status": status,
        "titulo": articulo.titulo,
        "titulo_sanitizado": datos_sanitizados["titulo_sanitizado"],
        "texto_sanitizado": datos_sanitizados["texto_sanitizado"],
        "categoria_id": articulo.categoria_id,
        "tags_count": len(tags),
        "longitud_texto": longitud_texto,
        "findings": findings,
        "technical_accuracy_verified": False
    }
