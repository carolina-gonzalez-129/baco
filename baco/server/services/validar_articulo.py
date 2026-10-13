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

def validar_texto_y_estructura_post_duplicados(articulo: ArticuloSchema) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    texto_limpio = (articulo.texto or "").strip()
    articulo.texto = texto_limpio
    longitud_texto = len(texto_limpio)
    if longitud_texto < 300:
        findings.append(_finding(
            severity="Bloqueante",
            field="texto",
            description=f"El texto es muy breve ({longitud_texto} caracteres). Se requieren al menos 300 caracteres.",
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

    tiene_bloqueantes = any(f["severity"] == "Bloqueante" for f in findings)
    status = "Pendiente" if tiene_bloqueantes else ("Listo con ajustes sugeridos" if findings else "Listo")

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




