from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

from baco.server.config_limites import TEXTO_MAX, TITULO_MAX
from baco.server.schemas.validacion import ValidarFormatoResponse


class EstadoFlujo(str, Enum):
    ESPERANDO_TITULO = "ESPERANDO_TITULO"
    DECISION_TITULO = "DECISION_TITULO"
    ESPERANDO_TEXTO = "ESPERANDO_TEXTO"
    DECISION_TEXTO = "DECISION_TEXTO"
    ESPERANDO_PLANTILLA = "ESPERANDO_PLANTILLA"
    ESPERANDO_METADATOS = "ESPERANDO_METADATOS"
    REVISION_BORRADOR = "REVISION_BORRADOR"
    # SUBSANANDO_BORRADOR se preserva por compatibilidad de esquema OpenAPI/Front,
    # pero el flujo operativo gestiona la subsanación bloqueante dentro de REVISION_BORRADOR.
    SUBSANANDO_BORRADOR = "SUBSANANDO_BORRADOR"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"


class CoincidenciaArticulo(BaseModel):
    id: int
    titulo: str
    url: Optional[str] = None
    score: Optional[float] = Field(
        default=None,
        description="Score de similitud (1.0 exacto, 0.70+ trigramas, 0.90+ embeddings)."
    )
    texto_original: Optional[str] = Field(
        default=None,
        description="Texto original del artículo coincidente."
    )
    tipo_coincidencia: Optional[str] = Field(
        default=None,
        description="Tipo de coincidencia: 'exacto', 'serie', 'trigrama' o 'semantico'."
    )


class CategoriaOpcion(BaseModel):
    id: int = Field(..., description="ID de la categoría en la tabla 'categorias'.")
    nombre: str = Field(..., description="Nombre de la categoría en la tabla 'categorias'.")


class EtapaFlujo(BaseModel):
    actual: int = Field(..., ge=1, description="Número de etapa actual (n de N).")
    total: int = Field(default=5, ge=1, description="Cantidad total de etapas del flujo (N).")
    nombre: str = Field(..., description="Nombre descriptivo de la etapa actual.")
    etapas: List[str] = Field(
        default_factory=list,
        description="Lista ordenada de todas las etapas del flujo para el stepper."
    )


class BorradorSesion(BaseModel):
    modo: Literal["nuevo", "enriquecimiento"]
    articulo_original_id: Optional[int] = None
    articulo_original_url: Optional[str] = None
    titulo: str
    texto: str = ""
    texto_original_aprobado: Optional[str] = None
    tipo_plantilla: Optional[Literal["instructivo", "soluciones"]] = None
    categoria_id: Optional[int] = 1
    tags: List[str] = Field(default_factory=list)


class ChatOrquestadorRequest(BaseModel):
    session_id: Optional[str] = Field(
        default=None,
        description="El ID de sesión es gestionado exclusivamente por el servidor mediante cookie 'baco_session' o cabecera 'X-Session-ID'. Cualquier valor enviado en este campo del cuerpo será ignorado."
    )
    mensaje: Optional[str] = Field(
        default=None,
        description="Entrada del usuario (título, texto o respuesta)."
    )
    accion: Optional[str] = Field(
        default=None,
        description="Atajo de botón ('enriquecer', 'descartar', 'continuar', 'editar', 'sanitizar', 'aprobar', 'rechazar', 'reiniciar')."
    )
    titulo: Optional[str] = Field(
        default=None,
        description="Título al editar el borrador."
    )
    texto: Optional[str] = Field(
        default=None,
        description="Cuerpo al cargar texto o editar el borrador."
    )
    categoria_id: Optional[int] = Field(
        default=None,
        description="Categoría o ID de módulo ERP del borrador."
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Lista de tags del borrador."
    )

    @field_validator("texto", "mensaje", mode="before")
    @classmethod
    def validar_longitud_texto(cls, v: Optional[str]) -> Optional[str]:
        if v and len(v) > TEXTO_MAX:
            raise ValueError(f"El texto supera los {TEXTO_MAX} caracteres. Dividilo o resumilo.")
        return v

    @field_validator("titulo", mode="before")
    @classmethod
    def validar_longitud_titulo(cls, v: Optional[str]) -> Optional[str]:
        if v and len(v) > TITULO_MAX:
            raise ValueError(f"El título supera los {TITULO_MAX} caracteres. Resumilo.")
        return v


class ChatOrquestadorResponse(BaseModel):
    session_id: str
    estado: EstadoFlujo
    etapa: EtapaFlujo = Field(
        ...,
        description="Etapa actual del flujo (n de N) y listado de etapas para el stepper."
    )
    mensaje: str
    opciones: List[str] = Field(
        default_factory=list,
        description="Botones o acciones válidas en el estado actual."
    )
    tags_acumulados: List[str] = Field(
        default_factory=list,
        description="Etiquetas acumuladas en la sesión o borrador hasta el momento."
    )
    categorias_disponibles: List[CategoriaOpcion] = Field(
        default_factory=list,
        description="Categorías elegibles provenientes de la tabla 'categorias' (id y nombre)."
    )
    tags_disponibles: List[str] = Field(
        default_factory=list,
        description="Etiquetas disponibles provenientes de la tabla 'tags'."
    )
    coincidencias: List[CoincidenciaArticulo] = Field(default_factory=list)
    borrador: Optional[BorradorSesion] = None
    validacion: Optional[ValidarFormatoResponse] = None
    aviso_privacidad: Optional[str] = Field(
        default=None,
        description="Notificación puntual ('flash') emitida cuando se detectan y anonimizan datos sensibles en el turno actual."
    )
