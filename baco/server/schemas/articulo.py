from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from baco.server.config_limites import (
    TEXTO_MAX_PERCENTIL_99,
    TEXTO_MIN,
    TITULO_MAX,
    TITULO_MIN,
)


class Tag(BaseModel):
    id: int | None = None
    name: str
    slug: str | None = None


class ArticuloSchema(BaseModel):
    id: int
    titulo: str = Field(..., min_length=TITULO_MIN, max_length=TITULO_MAX)
    categoria_id: int | None = None
    tags: list[Tag] = Field(default_factory=list)
    url: str | None = None
    texto: str = Field(..., min_length=1)
    actualizado: datetime | None = None
    raw_extra: dict | None = Field(default_factory=dict)

    @field_validator("texto")
    @classmethod
    def validar_longitud_texto_efectivo(cls, v: str) -> str:
        from baco.server.services.orquestador.recursos_service import (
            texto_efectivo_sin_marcadores,
        )

        efectivo = texto_efectivo_sin_marcadores(v)
        if len(efectivo) < TEXTO_MIN:
            raise ValueError(f"String should have at least {TEXTO_MIN} characters")
        if len(efectivo) > TEXTO_MAX_PERCENTIL_99:
            raise ValueError(f"String should have at most {TEXTO_MAX_PERCENTIL_99} characters")
        return v
