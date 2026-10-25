from typing import Literal, Optional
from pydantic import BaseModel, Field

TipoRecurso = Literal["imagen", "video", "audio", "documento", "otro"]
OrigenRecurso = Literal["existente", "subido"]


class Recurso(BaseModel):
    id: str = Field(..., description="Identificador único del recurso (ej: 'rec_1', 'rec_2')")
    tipo: TipoRecurso = Field(..., description="Tipo de recurso multimedia (imagen, video, audio, documento, otro)")
    nombre: str = Field(..., description="Nombre descriptivo o nombre del archivo")
    origen: OrigenRecurso = Field(default="existente", description="Origen del recurso: 'existente' (Discourse/externo) o 'subido' (temporal de sesión)")
    tamano_bytes: Optional[int] = Field(default=None, description="Tamaño del archivo en bytes si está disponible")
    mime_type: Optional[str] = Field(default=None, description="Tipo MIME verificado del recurso")
    referencia: str = Field(default="", description="URL original del recurso o ruta temporal en disco de la sesión")
    orden: int = Field(default=0, description="Posición ordinal de aparición en el texto")
