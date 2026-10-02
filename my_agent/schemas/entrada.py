from fastapi import FastAPI
from pydantic import BaseModel, Field
from enum import Enum
app = FastAPI()

##esta bueno porq pydantic
#ya valida q los campos sean los q estoy diciendo
#y por defecto los campos son requeridos, asiqeu

# Enum de tipo de plantilla
class TipoPlantilla(str, Enum):
    INSTRUCTIVO = "instructivo"
    SOLUCIONES = "soluciones"


class Entrada(BaseModel):
    titulo: str  = Field(
        ...,
        min_length=8,
        max_length=150,
        description="Título de la entrada"
    )
    categoria: str = Field(..., description="Categoria")
    tipo_plantilla: TipoPlantilla = Field(
        ...,
        description="Tipo de plantilla (instructivo o soluciones)"
    )
    descripcion: str = Field(
        ...,
        min_length=200,
        description="Descripcion detallada de la entrada (mínimo 200 caracteres)"
    )

 