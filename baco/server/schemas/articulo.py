from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from baco.server.config_limites import (
    TEXTO_MAX,
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
    texto: str = Field(..., min_length=TEXTO_MIN, max_length=TEXTO_MAX)
    actualizado: Optional[datetime] = None
    raw_extra: Optional[dict] = Field(default_factory=dict)