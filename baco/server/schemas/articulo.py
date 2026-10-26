from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from baco.server.config_limites import (
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)


class Tag(BaseModel):
    id: Optional[int] = None
    name: str
    slug: Optional[str] = None


class ArticuloSchema(BaseModel):
    id: int
    titulo: str = Field(..., min_length=TITULO_MIN, max_length=TITULO_MAX)
    categoria_id: Optional[int] = None
    tags: List[Tag] = Field(default_factory=list)
    url: Optional[str] = None
    texto: str = Field(..., min_length=1)
    actualizado: Optional[datetime] = None
    raw_extra: Optional[dict] = Field(default_factory=dict)

    @field_validator("texto")
    @classmethod
    def validar_longitud_texto_efectivo(cls, v: str) -> str:
        from baco.server.services.orquestador.recursos_service import texto_efectivo_sin_marcadores

        efectivo = texto_efectivo_sin_marcadores(v)
        if len(efectivo) < TEXTO_MIN:
            raise ValueError(f"String should have at least {TEXTO_MIN} characters")
        if len(efectivo) > TEXTO_MAX_PERCENTIL_99:
            raise ValueError(f"String should have at most {TEXTO_MAX_PERCENTIL_99} characters")
        return v
