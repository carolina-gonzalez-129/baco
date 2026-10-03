import re
from typing import Any
from my_agent.server.schemas.articulo import ArticuloSchema


##PARA USAR DESDE EL LADO DEL SERVIDOR, ES UN VALIDADOR DETERMINISTA

def _finding(severity: str, field: str, description: str, action: str) -> dict[str, str]:
    return {
        "severity": severity,
        "field": field,
        "description": description,
        "action": action
    }


def validate_article_structure(articulo: ArticuloSchema) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    # 1. Título obligatorio y no por defecto
    titulo_limpio = articulo.titulo.strip()
    if not titulo_limpio or titulo_limpio.lower() == "sin título":
        findings.append(_finding(
            severity="Bloqueante",
            field="titulo",
            description="El artículo debe tener un título definido.",
            action="Asignar un título descriptivo al artículo."
        ))
    elif re.search(r"\berror\b", titulo_limpio, re.IGNORECASE):
        # Regla editorial si usa "error"
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

    # 3. Al menos 2 tags / etiquetas para que sea localizable
    if len(articulo.tags) < 2:
        findings.append(_finding(
            severity="Bloqueante",
            field="tags",
            description=f"Se requieren al menos 2 tags o etiquetas (actualmente tiene {len(articulo.tags)}).",
            action="Agregar al menos dos etiquetas relevantes (ej. 'instructivo', 'facturacion')."
        ))

    # 4. Longitud mínima de la descripción / texto (al menos 300 caracteres)
    longitud_texto = len(articulo.texto.strip())
    if longitud_texto < 300:
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description=f"El texto es muy breve ({longitud_texto} caracteres). Se requieren al menos 300 caracteres.",
            action="Detallar mejor el problema, pasos a seguir o contexto técnico."
        ))
    elif re.search(r"\[Indicar[^]]*\]", articulo.texto, re.IGNORECASE):
        # Marcadores pendientes
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description="Quedan marcadores de información pendiente como '[Indicar...]'.",
            action="Completar o retirar los marcadores antes de publicar."
        ))

    # Estado final
    tiene_bloqueantes = any(f["severity"] == "Bloqueante" for f in findings)
    status = "Pendiente" if tiene_bloqueantes else ("Listo con ajustes sugeridos" if findings else "Listo")

    return {
        "id": articulo.id,
        "status": status,
        "titulo": articulo.titulo,
        "categoria_id": articulo.categoria_id,
        "tags_count": len(articulo.tags),
        "longitud_texto": longitud_texto,
        "findings": findings,
        "technical_accuracy_verified": False
    }