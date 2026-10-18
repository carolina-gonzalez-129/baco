from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from baco.server.schemas.validacion import ValidarFormatoResponse


class EstadoFlujo(str, Enum):
    ESPERANDO_TITULO = "ESPERANDO_TITULO"
    DECISION_TITULO = "DECISION_TITULO"
    ESPERANDO_TEXTO = "ESPERANDO_TEXTO"
    DECISION_TEXTO = "DECISION_TEXTO"
    ESPERANDO_PLANTILLA = "ESPERANDO_PLANTILLA"
    ESPERANDO_METADATOS = "ESPERANDO_METADATOS"
    REVISION_BORRADOR = "REVISION_BORRADOR"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"


class CoincidenciaArticulo(BaseModel):
    id: int
    titulo: str
    url: str


class BorradorSesion(BaseModel):
    modo: Literal["nuevo", "enriquecimiento"]
    articulo_original_id: Optional[int] = None
    articulo_original_url: Optional[str] = None
    titulo: str
    texto: str = ""
    tipo_plantilla: Optional[Literal["instructivo", "soluciones"]] = None
    categoria_id: Optional[int] = 1
    tags: List[str] = Field(default_factory=list)


class ChatOrquestadorRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, description="ID de la sesión conversacional.")
    mensaje: Optional[str] = Field(default=None, description="Entrada del usuario (título, texto o respuesta).")
    accion: Optional[str] = Field(
        default=None,
        description="Atajo de botón ('enriquecer', 'descartar', 'continuar', 'editar', 'sanitizar', 'aprobar', 'rechazar', 'reiniciar')."
    )
    titulo: Optional[str] = Field(default=None, description="Título al editar el borrador.")
    texto: Optional[str] = Field(default=None, description="Cuerpo al cargar texto o editar el borrador.")
    categoria_id: Optional[int] = Field(default=None, description="Categoría del borrador.")
    tags: Optional[List[str]] = Field(default=None, description="Tags del borrador.")


class ChatOrquestadorResponse(BaseModel):
    session_id: str
    estado: EstadoFlujo
    mensaje: str
    opciones: List[str] = Field(default_factory=list, description="Botones o acciones válidas en el estado actual.")
    coincidencias: List[CoincidenciaArticulo] = Field(default_factory=list)
    borrador: Optional[BorradorSesion] = None
    validacion: Optional[ValidarFormatoResponse] = None
