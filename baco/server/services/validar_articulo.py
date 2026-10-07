import re
from typing import Any
from baco.server.schemas.articulo import ArticuloSchema


## ============================================================================
## VALIDADOR DETERMINISTA DE ESTRUCTURA DE ARTÍCULOS (LADO DEL SERVIDOR)
## ============================================================================
# NOTA ARQUITECTURA:
# No aplicar todas las validaciones antes de implementar la deduplicación porque
# muchos artículos ya publicados no las cumplen (en baco_db se verificó que el 69%
# no tiene tag de plantilla, 17% tiene menos de 2 tags y 6,9% tiene menos de 300 caracteres).
# Osea q si fuesemos tan estrictos al principio se perderia el 70 % de la base
#
# ESTRATEGIA EN 2 FASES:
# 1) FASE 1 (Pre-Duplicados): Validación exclusiva sobre el campo TÍTULO con auto-sanitización.
#    Permite buscar duplicados de inmediato sin abrumar al usuario con el resto del contenido.
# 2) FASE 2 (Post-Duplicados): Validación sobre el campo TEXTO, taxonomía (categoría/tags)
#    y reglas editoriales para asegurar la calidad del artículo nuevo o a publicar.
## ============================================================================


def _finding(severity: str, field: str, description: str, action: str) -> dict[str, str]:
    return {
        "severity": severity,
        "field": field,
        "description": description,
        "action": action
    }


# ----------------------------------------------------------------------------
# FASE 1: Validación y Sanitización Exclusiva del TÍTULO (PRE-DUPLICADOS)
# ----------------------------------------------------------------------------
def validar_titulo_pre_duplicados(articulo: ArticuloSchema) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    titulo_raw = (articulo.titulo or "").strip()
    titulo_limpio = re.sub(r"\s+", " ", titulo_raw)
    if titulo_limpio.endswith("."):
        titulo_limpio = titulo_limpio.rstrip(".").strip()
    articulo.titulo = titulo_limpio
    if not titulo_limpio or titulo_limpio.lower() == "sin título":
        findings.append(_finding(
            severity="Bloqueante",
            field="titulo",
            description="El artículo debe tener un título definido para poder procesarse",
            action="Asignar un título descriptivo al artículo."
        ))
    else:
        if re.match(r"^c[oó]mo\s+(hacer\s+para\s+)?", titulo_limpio, re.IGNORECASE):
            findings.append(_finding(
                severity="Requiere ajuste",
                field="titulo",
                description="Inicia con fórmulas redundantes como 'Cómo...' o 'Cómo hacer para...'.",
                action="Comenzar directamente con el verbo de acción en infinitivo (ej. 'Configurar...', 'Emitir...')."
            ))

        if re.search(r"\berror\b", titulo_limpio, re.IGNORECASE):
            if not re.search(r"""["'“].*?\berror\b.*?["'”]""", titulo_limpio, re.IGNORECASE):
                findings.append(_finding(
                    severity="Requiere ajuste",
                    field="titulo",
                    description="Usa la palabra 'Error' sin un mensaje literal citado entre comillas.",
                    action="Conservarlo solo si forma parte del mensaje textual del sistema entre comillas."
                ))

    tiene_bloqueantes = any(f["severity"] == "Bloqueante" for f in findings)

    return {
        "id": articulo.id,
        "fase": "fase_1_titulo",
        "apto_para_deduplicacion": not tiene_bloqueantes,
        "titulo_sanitizado": articulo.titulo,
        "findings": findings
    }


# ----------------------------------------------------------------------------
# FASE 2: Validacion de los demas campos
# ----------------------------------------------------------------------------
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
