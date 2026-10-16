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

# regex para q no manden datos sensibles o links raros
RE_CUIT = re.compile(r"\b\d{2}-?\d{8}-?\d\b")
RE_EMAIL = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
RE_TICKETS = re.compile(r"\b(ticket|incidente|caso|jira|tarea)\s*#?\d+\b", re.IGNORECASE)
RE_URL_INTERNA = re.compile(r"https?://[^\s]*(?:dev|stage|qa|local|\.test|192\.168|10\.|172\.)[^\s]*", re.IGNORECASE)

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

    if RE_CUIT.search(contenido_completo):
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description="Se detectaron CUITs reales o números de identificación tributaria en el contenido.",
            action="Reemplazar por CUITs genéricos o ficticios (ej. '30-00000000-0') antes de publicar."
        ))

    if RE_EMAIL.search(contenido_completo):
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

    if RE_URL_INTERNA.search(contenido_completo):
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description="Se detectaron URLs de entornos internos, pruebas o IPs privadas.",
            action="Remover o reemplazar por URLs genéricas o de documentación oficial."
        ))

    # me fijo si no pusieron titulo o si arranca con como hacer
    if not titulo_limpio:
        findings.append(_finding(
            severity="Bloqueante",
            field="titulo",
            description="El artículo no posee título.",
            action="Definir un título descriptivo para el artículo."
        ))
    else:
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

    return {
        "id": articulo.id,
        "fase": "fase_2_texto_y_estructura",
        "status": status,
        "titulo": articulo.titulo,
        "categoria_id": articulo.categoria_id,
        "tags_count": len(tags),
        "longitud_texto": longitud_texto,
        "findings": findings,
        "technical_accuracy_verified": False
    }
