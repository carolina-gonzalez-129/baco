import re
from typing import Any
from baco.server.schemas.articulo import ArticuloSchema


## VALIDADOR DETERMINISTA DE ESTRUCTURA DE ARTÍCULOS (LADO DEL SERVIDOR)

def _finding(severity: str, field: str, description: str, action: str) -> dict[str, str]:
    return {
        "severity": severity,
        "field": field,
        "description": description,
        "action": action
    }


def validar_estructura_articulo(articulo: ArticuloSchema) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    # 1. Validación determinista del Título
    titulo_limpio = (articulo.titulo or "").strip()
    if not titulo_limpio or titulo_limpio.lower() == "sin título":
        findings.append(_finding(
            severity="Bloqueante",
            field="titulo",
            description="El artículo debe tener un título definido.",
            action="Asignar un título descriptivo al artículo."
        ))
    else:
        # A. No debe terminar en punto final
        if titulo_limpio.endswith("."):
            findings.append(_finding(
                severity="Requiere ajuste",
                field="titulo",
                description="El título no debe terminar con punto final.",
                action="Eliminar el punto final del título."
            ))

        # B. Evitar fórmulas redundantes de inicio (ej. 'Cómo...', 'Cómo hacer para...')
        if re.match(r"^c[oó]mo\s+(hacer\s+para\s+)?", titulo_limpio, re.IGNORECASE):
            findings.append(_finding(
                severity="Requiere ajuste",
                field="titulo",
                description="Inicia con fórmulas redundantes como 'Cómo...' o 'Cómo hacer para...'.",
                action="Comenzar directamente con el verbo de acción en infinitivo (ej. 'Configurar...', 'Emitir...')."
            ))

        # C. Regla editorial si usa la palabra "error"
        if re.search(r"\berror\b", titulo_limpio, re.IGNORECASE):
            if not re.search(r"""["'“].*?\berror\b.*?["'”]""", titulo_limpio, re.IGNORECASE):
                findings.append(_finding(
                    severity="Requiere ajuste",
                    field="titulo",
                    description="Usa la palabra 'Error' sin un mensaje literal citado entre comillas.",
                    action="Conservarlo solo si forma parte del mensaje textual del sistema entre comillas."
                ))

    # 2. Categoría obligatoria
    if not articulo.categoria_id:
        findings.append(_finding(
            severity="Bloqueante",
            field="categoria_id",
            description="El artículo debe tener asignada una categoría principal.",
            action="Indicar la categoría correspondiente."
        ))

    # 3. Validación de Tags / Etiquetas
    tags = articulo.tags or []
    slugs_o_nombres = {getattr(t, "slug", None) or getattr(t, "name", str(t)).lower().strip() for t in tags}

    # A. Cantidad mínima
    if len(tags) < 2:
        findings.append(_finding(
            severity="Bloqueante",
            field="tags",
            description=f"Se requieren al menos 2 tags o etiquetas (actualmente tiene {len(tags)}).",
            action="Agregar al menos dos etiquetas relevantes (ej. 'instructivo', 'facturacion')."
        ))

    # B. Debe incluir la etiqueta de tipo obligatoria: 'instructivo' o 'soluciones'
    if not any(tipo in slugs_o_nombres for tipo in ("instructivo", "soluciones", "instructivos", "solucion")):
        findings.append(_finding(
            severity="Bloqueante",
            field="tags",
            description="Falta la etiqueta obligatoria de tipo de plantilla ('instructivo' o 'soluciones').",
            action="Incorporar 'instructivo' o 'soluciones' entre las etiquetas del artículo."
        ))

    # 4. Longitud mínima y marcadores en la descripción / texto
    texto_limpio = (articulo.texto or "").strip()
    longitud_texto = len(texto_limpio)
    if longitud_texto < 300:
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description=f"El texto es muy breve ({longitud_texto} caracteres). Se requieren al menos 300 caracteres.",
            action="Detallar mejor el problema, pasos a seguir o contexto técnico."
        ))
    elif re.search(r"\[Indicar[^]]*\]", texto_limpio, re.IGNORECASE):
        # Marcadores pendientes
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description="Quedan marcadores de información pendiente como '[Indicar...]'.",
            action="Completar o retirar los marcadores antes de publicar."
        ))

    # Estado final consolidado
    tiene_bloqueantes = any(f["severity"] == "Bloqueante" for f in findings)
    status = "Pendiente" if tiene_bloqueantes else ("Listo con ajustes sugeridos" if findings else "Listo")

    return {
        "id": articulo.id,
        "status": status,
        "titulo": articulo.titulo,
        "categoria_id": articulo.categoria_id,
        "tags_count": len(tags),
        "longitud_texto": longitud_texto,
        "findings": findings,
        "technical_accuracy_verified": False
    }

# Alias para compatibilidad con código existente
validate_article_structure = validar_estructura_articulo