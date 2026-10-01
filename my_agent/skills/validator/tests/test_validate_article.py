from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from validate_article import validate_article


def test_solucion_valida_con_respuesta():
    result = validate_article({
        "title": "Corregir retención SUSS",
        "category": "Impuestos Argentina",
        "template_type": "soluciones",
        "description": "Corregir la retención SUSS.",
        "tags": ["soluciones", "retencion-suss"],
        "body": "## Consulta\n\nNo calcula la retención.\n\n## Respuesta\n\nLa configuración no está completa.\n\n## Pasos a seguir\n\n1. Revisar la configuración.",
    })
    assert result["status"] == "Listo"
    assert result["findings"] == []


def test_detecta_marcadores_y_seccion_respuesta():
    result = validate_article({
        "title": "Problema de retención",
        "category": "ERP",
        "template_type": "soluciones",
        "description": "Resolver el problema de retención.",
        "tags": [],
        "body": "## Consulta\n\nFalla.\n\n## Respuesta\n\nCausa.\n\n## Pasos a seguir\n\n[Indicar pasos]",
    })
    assert result["status"] == "Pendiente"
    assert any(f["field"] == "Estructura" for f in result["findings"])
    assert any(f["field"] == "Cuerpo" for f in result["findings"])


def test_distingue_error_citado():
    result = validate_article({
        "title": "Obtener CAE - Mensaje: “Error de conexión”",
        "category": "ERP",
        "template_type": "instructivo",
        "description": "Obtener el CAE.",
        "tags": ["instructivo"],
        "body": "Contenido.",
    })
    assert not any(f["field"] == "Título" for f in result["findings"])
