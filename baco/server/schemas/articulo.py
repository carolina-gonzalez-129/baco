from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class Tag(BaseModel):
    id: Optional[int] = None
    name: str
    slug: Optional[str] = None


class ArticuloSchema(BaseModel):
    id: int
    titulo: str = Field(..., min_length=15, max_length=255)
    categoria_id: Optional[int] = None
    tags: List[Tag] = Field(default_factory=list)
    url: Optional[str] = None
    texto: str = Field(..., min_length=20, max_length=5500)
    actualizado: Optional[datetime] = None
    raw_extra: Optional[dict] = Field(default_factory=dict)
    @field_validator("texto", mode="before")
    @classmethod
    def truncar_texto_para_agente(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 5500:
            return v[:5500]
        return v