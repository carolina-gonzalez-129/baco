from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime

class Tag(BaseModel):
    id: Optional[int] = None
    name: str
    slug: Optional[str] = None

class ArticuloSchema(BaseModel):
    id: int
    titulo: str = Field(default="Sin título")
    categoria_id: Optional[int] = None
    tags: List[Tag] = Field(default_factory=list)
    url: Optional[str] = None
    texto: str = Field(default="")
    actualizado: Optional[datetime] = None
    raw_extra: Optional[dict] = Field(default_factory=dict)