from typing import Optional, List, Literal
from pydantic import BaseModel, Field

class ArticuloSimilarTool(BaseModel):
    id: int = Field(..., description="ID del artículo en Discourse")
    titulo: str = Field(..., description="Título del artículo existente")
    url: str = Field(..., description="URL oficial del artículo para proponer su mejora o consulta")
    score: Optional[float] = Field(default=None, description="Puntaje de similitud (0.0 a 1.0)")


class BuscarDuplicadosToolOutput(BaseModel):
    decision_sugerida: Literal["crear_nuevo", "proponer_mejora_existente"] = Field(
        ...,
        description="Orientación para el agente: 'proponer_mejora_existente' si se encontraron artículos afines "
                    "para sugerir su edición/actualización, o 'crear_nuevo' si el contenido es novedoso."
    )
    hay_duplicados: bool = Field(
        ...,
        description="True si se detectó algún duplicado exacto o artículos muy similares."
    )
    mensaje: str = Field(
        ...,
        description="Diagnóstico conciso del buscador de duplicados."
    )
    url_principal: Optional[str] = Field(
        default=None,
        description="URL del artículo existente más relevante para proponer su mejora, si se encontró."
    )
    articulos_similares: List[ArticuloSimilarTool] = Field(
        default_factory=list,
        description="Lista de artículos similares existentes encontrados (solo lectura)."
    )
