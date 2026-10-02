
#Comprobaciones deterministas para el formato de una entrada

#Quizas estaria bueno que si se puede esto pase a handlearlo el servidor
#Para que a la skill de validator entonces solo le quede lo de nlp, osea tiene q aplicar pautas de redaccion buenos titulos y demas
#Incluso aunque el agente exista xq paso los otros filtros podria utilizarse
from my_agent.schemas.entrada import Entrada, TipoPlantilla
import re
from typing import Any

def _finding(severity: str, field: str, description: str, action: str) -> dict[str, str]:
    return {"severity": severity, "field": field, "description": description, "action": action}

def validate_article_structure(entrada: Entrada) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    # 1. Regla editorial del título: "Error" literal entre comillas
    if re.search(r"\berror\b", entrada.titulo, re.IGNORECASE):
        if not re.search(r"""["“].*?\berror\b.*?["”]""", entrada.titulo, re.IGNORECASE):
            findings.append(_finding(
                "Requiere ajuste",
                "Título",
                "Usa la palabra “Error” sin un mensaje literal citado.",
                "Conservarlo solo si forma parte del mensaje textual del sistema entre comillas."
            ))

    # 2. Marcadores pendientes en la descripción ([Indicar...])
    if re.search(r"\[Indicar[^]]*\]", entrada.descripcion, re.IGNORECASE):
        findings.append(_finding(
            "Bloqueante",
            "Descripción",
            "Quedan marcadores de información pendiente como '[Indicar...]'.",
            "Completar o retirar los marcadores antes de publicar."
        ))

    # 3. Estructura para plantilla de Soluciones
    if entrada.tipo_plantilla == TipoPlantilla.SOLUCIONES:
        secciones = [
            ("Consulta", r"(?im)^\s*#{0,6}\s*Consulta\s*:?\s*$"),
            ("Pasos a seguir", r"(?im)^\s*#{0,6}\s*Pasos a seguir\s*:?\s*$"),
            ("Respuesta", r"(?im)^\s*#{0,6}\s*Respuesta\s*:?\s*$")
        ]
        for nombre, patron in secciones:
            if not re.search(patron, entrada.descripcion):
                findings.append(_finding(
                    "Bloqueante",
                    "Estructura",
                    f"Falta la sección obligatoria '{nombre}'.",
                    f"Agregar la sección '{nombre}' en la descripción."
                ))

    # Estado final
    tiene_bloqueantes = any(f["severity"] == "Bloqueante" for f in findings)
    status = "Pendiente" if tiene_bloqueantes else ("Listo con ajustes sugeridos" if findings else "Listo")

    return {
        "status": status,
        "titulo": entrada.titulo,
        "categoria": entrada.categoria,
        "tipo_plantilla": entrada.tipo_plantilla,
        "findings": findings,
        "technical_accuracy_verified": False
    }