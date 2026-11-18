from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StatusValidacionEnum(str, Enum):
    LISTO = "Listo"
    LISTO_CON_AJUSTES = "Listo con ajustes sugeridos"
    LISTO_CON_SUGERENCIAS = "Listo con sugerencias"
    PENDIENTE = "Pendiente"


class FindingSchema(BaseModel):
    severity: str = Field(..., description="Nivel de severidad: 'Bloqueante', 'Ajuste' o 'Sugerencia'")
    description: str = Field(..., description="Detalle del hallazgo encontrado")
    field: str | None = Field(default=None, description="Campo del artículo afectado (ej: 'texto', 'titulo', 'tags')")
    action: str | None = Field(default=None, description="Acción recomendada para resolver el problema")
    category: str | None = Field(default=None, description="Categoría de la regla")
    level: str | None = Field(default=None, description="Nivel de severidad normalizado")
    snippet: str | None = Field(default=None, description="Fragmento del texto donde se detectó el problema")
    suggestion: str | None = Field(default=None, description="Recomendación adicional")


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
    titulo_sanitizado: str | None = Field(
        default=None,
        description="Título sanitizado deterministamente (sin fórmulas redundantes como 'Cómo...')."
    )
    texto_sanitizado: str | None = Field(
        default=None,
        description="Cuerpo sanitizado deterministamente (CUITs reales y correos reemplazados por ejemplos seguros)."
    )
    aviso_privacidad: str | None = Field(
        default=None,
        description="Aviso de privacidad y protección de datos si se sanitizaron PIIs."
    )
    findings: list[FindingSchema] = Field(
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
