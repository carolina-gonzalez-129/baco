from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class FindingSchema(BaseModel):
    severity: str = Field(..., description="Nivel de severidad: 'Bloqueante', 'Ajuste' o 'Sugerencia'")
    description: str = Field(..., description="Detalle del hallazgo encontrado")
    field: Optional[str] = Field(default=None, description="Campo del artículo afectado (ej: 'texto', 'titulo', 'tags')")
    action: Optional[str] = Field(default=None, description="Acción recomendada para resolver el problema")
    category: Optional[str] = Field(default=None, description="Categoría de la regla")
    level: Optional[str] = Field(default=None, description="Nivel de severidad normalizado")
    snippet: Optional[str] = Field(default=None, description="Fragmento del texto donde se detectó el problema")
    suggestion: Optional[str] = Field(default=None, description="Recomendación adicional")


class ResumenValidacionSchema(BaseModel):
    longitud_texto: int = Field(..., description="Cantidad de caracteres del cuerpo del artículo")
    tags_count: int = Field(..., description="Cantidad de etiquetas asignadas")


class ValidarFormatoResponse(BaseModel):
    valido: bool = Field(
        ...,
        description="True si el artículo no tiene hallazgos bloqueantes y está listo para publicarse."
    )
    fase: str = Field(
        default="fase_2_texto_y_estructura",
        description="Fase del pipeline de validación ejecutada"
    )
    status: str = Field(
        ...,
        description="Estado final del artículo: 'Listo' o 'Pendiente'"
    )
    titulo_sanitizado: Optional[str] = Field(
        default=None,
        description="Título sanitizado deterministamente (sin fórmulas redundantes como 'Cómo...')."
    )
    texto_sanitizado: Optional[str] = Field(
        default=None,
        description="Cuerpo sanitizado deterministamente (CUITs reales y correos reemplazados por ejemplos seguros)."
    )
    findings: List[FindingSchema] = Field(
        default_factory=list,
        description="Listado de observaciones, alertas bloqueantes o sugerencias"
    )
    resumen: ResumenValidacionSchema = Field(
        ...,
        description="Resumen de métricas de tamaño y etiquetas"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "valido": True,
                "fase": "fase_2_texto_y_estructura",
                "status": "Listo",
                "titulo_sanitizado": "Configurar Facturación Electrónica AFIP",
                "texto_sanitizado": "Para configurar los comprobantes con CUIT 20-12345678-9...",
                "findings": [],
                "resumen": {
                    "longitud_texto": 450,
                    "tags_count": 3
                }
            }
        }
    )


class HallazgoTool(BaseModel):
    """Observación o diagnóstico editorial/estructural devuelto."""
    severidad: str = Field(..., description="Nivel: 'Bloqueante', 'Requiere ajuste' o 'Sugerencia'")
    campo: str = Field(..., description="Campo afectado: 'titulo', 'texto' o 'tags'")
    descripcion: str = Field(..., description="Descripción del problema encontrado")
    accion: str = Field(..., description="Acción correctiva recomendada")


class ValidarFormatoToolOutput(BaseModel):
    """Diagnóstico editorial y estructural simplificado para consumo en MCP."""
    valido: bool = Field(..., description="True si no existen observaciones bloqueantes para la publicación.")
    status: str = Field(..., description="'Listo' o 'Pendiente'")
    titulo_sanitizado: Optional[str] = Field(
        default=None,
        description="Título sanitizado listo para consumo directo de BACO."
    )
    texto_sanitizado: Optional[str] = Field(
        default=None,
        description="Cuerpo sanitizado sin datos sensibles listo para que BACO aplique sus skills."
    )
    hallazgos: List[HallazgoTool] = Field(
        default_factory=list,
        description="Lista de observaciones detectadas (bloqueantes, ajustes de estilo o marcadores pendientes)."
    )
    longitud_texto: int = Field(..., description="Cantidad de caracteres evaluados en el cuerpo.")
    tags_count: int = Field(..., description="Cantidad de etiquetas informadas.")
