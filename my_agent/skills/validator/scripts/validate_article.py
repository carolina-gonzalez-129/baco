"""Comprobaciones deterministas para el formato mínimo de un artículo."""

from __future__ import annotations

import re
from typing import Any


def _finding(severity: str, field: str, description: str, action: str) -> dict[str, str]:
    return {"severity": severity, "field": field, "description": description, "action": action}


def validate_article(article: dict[str, Any]) -> dict[str, Any]:
    """Valida requisitos mecánicos; no evalúa exactitud técnica o semántica."""
    findings: list[dict[str, str]] = []
    title = article.get("title")
    category = article.get("category")
    template_type = article.get("template_type")
    description = article.get("description")
    body = article.get("body", "")
    tags = article.get("tags", [])

    if not isinstance(title, str) or not title.strip():
        findings.append(_finding("Bloqueante", "Título", "Falta el título.", "Informar un título."))
    if not isinstance(category, str) or not category.strip():
        findings.append(_finding("Bloqueante", "Categoría", "Falta la categoría.", "Informar una categoría."))
    if template_type not in {"instructivo", "soluciones"}:
        findings.append(_finding("Bloqueante", "Tipo de plantilla", "Debe ser instructivo o soluciones.", "Informar el tipo."))
    if not isinstance(description, str) or not description.strip():
        findings.append(_finding("Bloqueante", "Descripción", "Falta la descripción.", "Informar una descripción."))
    if not isinstance(body, str) or not body.strip():
        findings.append(_finding("Bloqueante", "Cuerpo", "Falta el cuerpo del artículo.", "Informar el contenido."))

    normalized_tags = {tag.strip().casefold() for tag in tags if isinstance(tag, str)}
    if template_type in {"instructivo", "soluciones"} and template_type not in normalized_tags:
        findings.append(_finding("Requiere ajuste", "Etiquetas", f"Falta la etiqueta {template_type}.", f"Agregar {template_type}."))

    if isinstance(title, str) and re.search(r"\berror\b", title, re.IGNORECASE):
        if re.search(r"""["“].*?\berror\b.*?["”]""", title, re.IGNORECASE) is None:
            findings.append(_finding("Requiere ajuste", "Título", "Usa “Error” sin un mensaje literal citado.", "Conservarlo solo si forma parte del mensaje del sistema."))

    if isinstance(body, str):
        if re.search(r"\[Indicar[^]]*\]", body, re.IGNORECASE):
            findings.append(_finding("Bloqueante", "Cuerpo", "Quedan marcadores de información pendiente.", "Completar o retirar los marcadores."))
        if template_type == "soluciones":
            if not re.search(r"(?im)^\s*#{0,6}\s*Consulta\s*:?\s*$", body):
                findings.append(_finding("Bloqueante", "Estructura", "Falta la sección Consulta.", "Agregar Consulta."))
            if not re.search(r"(?im)^\s*#{0,6}\s*Pasos a seguir\s*:?\s*$", body):
                findings.append(_finding("Bloqueante", "Estructura", "Falta la sección Pasos a seguir.", "Agregar Pasos a seguir."))
            if not re.search(r"(?im)^\s*#{0,6}\s*Respuesta\s*:?\s*$", body):
                findings.append(_finding("Bloqueante", "Estructura", "Falta la sección Respuesta.", "Agregar Respuesta."))

    status = "Pendiente" if any(f["severity"] == "Bloqueante" for f in findings) else (
        "Listo con ajustes sugeridos" if findings else "Listo"
    )
    return {
        "status": status,
        "title": title if isinstance(title, str) else "",
        "category": category if isinstance(category, str) else "",
        "template_type": template_type if isinstance(template_type, str) else "",
        "tags": sorted(normalized_tags),
        "findings": findings,
        "technical_accuracy_verified": False,
    }
