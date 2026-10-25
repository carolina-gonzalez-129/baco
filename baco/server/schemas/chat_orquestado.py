from enum import Enum
import re
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ValidationInfo, computed_field, field_validator, model_validator

from baco.server.config_limites import TEXTO_MAX, TITULO_MAX
from baco.server.schemas.validacion import ValidarFormatoResponse
from baco.server.schemas.recurso import Recurso

_RE_MARCADOR_LEGACY = re.compile(r"\[\[recurso:[a-zA-Z0-9_\-]+\]\]")


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
    CONFORMIDAD_USUARIO = "CONFORMIDAD_USUARIO"
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


class ItemContenidoAdicional(BaseModel):
    id: str = Field(..., description="ID estable del ítem adicional.")
    tipo: str = Field(default="texto", description="Tipo de contenido: texto, nota, enlace, etc.")
    contenido: str = Field(default="", description="Contenido textual o valor del ítem.")
    posicion: int = Field(default=0, description="Posición u orden del ítem en la lista.")


class BorradorSesion(BaseModel):
    modo: Literal["nuevo", "enriquecimiento"]
    articulo_original_id: Optional[int] = None
    articulo_original_url: Optional[str] = None
    titulo: str
    recursos: Dict[str, Recurso] = Field(default_factory=dict)
    texto_limpio: str = ""
    texto_en_edicion: str = ""
    orden_multimedia: List[int] = Field(
        default_factory=list,
        description="Vector numérico que guarda el orden explícito de los contenidos multimedia en el borrador."
    )
    posiciones: List[int] = Field(
        default_factory=list,
        description="Vector numérico con las posiciones correlativas de los contenidos multimedia."
    )
    contenido_adicional: List[ItemContenidoAdicional] = Field(
        default_factory=list,
        description="Sección aparte de contenido adicional para flujos de enriquecer o actualizar, separada de texto_limpio."
    )
    advertencias_recursos: List[str] = Field(default_factory=list)
    texto_original_conforme: Optional[str] = None
    conforme: bool = Field(default=False, description="Indica si el usuario prestó conformidad con el borrador.")
    conforme_en: Optional[str] = Field(default=None, description="Timestamp ISO 8601 del momento en que se registró la conformidad.")
    conformidad_invalidada: bool = Field(default=False, description="Indica si una conformidad previa fue invalidada por una modificación posterior.")
    tipo_plantilla: Optional[Literal["instructivo", "soluciones"]] = None
    categoria_id: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    metadatos_anteriores: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Metadatos heredados del artículo original: categoria_id, categoria_nombre, tags",
    )
    metadatos_heredados_revisados: bool = Field(
        default=False,
        description="Indica si el usuario ya revisó o confirmó los metadatos heredados.",
    )

    @model_validator(mode="before")
    @classmethod
    def preparar_datos_borrador(cls, data: Any) -> Any:
        if isinstance(data, dict):
            txt = data.get("texto")
            txt_limpio = data.get("texto_limpio")
            if (not txt_limpio) and txt:
                from baco.server.services.orquestador.recursos_service import extraer_recursos_y_texto_limpio
                tl, recs = extraer_recursos_y_texto_limpio(txt)
                data["texto_limpio"] = tl
                if recs and not data.get("recursos"):
                    data["recursos"] = recs
            data.pop("texto", None)
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def texto(self) -> str:
        """Vista compuesta derivada: siempre componer_texto_publicable(texto_limpio, recursos)."""
        from baco.server.services.orquestador.recursos_service import componer_texto_publicable
        return componer_texto_publicable(self.texto_limpio, self.recursos)

    @field_validator("texto_limpio", mode="after")
    @classmethod
    def validar_marcadores_referencian_recursos_existentes(cls, v: str, info: ValidationInfo) -> str:
        """Cambio 3: valida que cada marcador en texto_limpio referencia un recurso existente.

        Rechaza marcadores inventados o escritos a mano por la persona sin borrado silencioso.
        """
        if not v or not isinstance(v, str):
            return v
        marcadores_recurso = re.findall(r"\[\[recurso:([a-zA-Z0-9_\-]+)\]\]", v)
        if not marcadores_recurso:
            return v

        recursos = info.data.get("recursos") if info.data else None
        recursos_dict = recursos if isinstance(recursos, dict) else {}

        invalidos = [m for m in marcadores_recurso if m not in recursos_dict]
        if invalidos:
            raise ValueError(
                f"El texto contiene marcadores que no referencian ningún recurso existente: "
                f"{', '.join(f'[[recurso:{m}]]' for m in invalidos)}. "
                f"No se permite ingresar marcadores manualmente."
            )
        return v

    @model_validator(mode="after")
    def sincronizar_vector_multimedia(self) -> "BorradorSesion":
        """Al crear el borrador (en cualquier flujo) deja la lista multimedia lista para el panel:

        orden correlativo 0..N-1, diccionario en ese orden y vectores sincronizados.
        También normaliza borradores previos con órdenes 1-based o con huecos.
        """
        items = sorted(self.recursos.values(), key=lambda r: r.orden)
        for i, r in enumerate(items):
            r.orden = i
        self.recursos = {r.id: r for r in items}
        vec = list(range(len(items)))
        self.orden_multimedia = list(vec)
        self.posiciones = list(vec)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def multimedia(self) -> List[Recurso]:
        """Lista de recursos multimedia en su orden explícito actual (se serializa para el front)."""
        return sorted(self.recursos.values(), key=lambda r: r.orden)

    def reorder(self, from_index: int, to_index: int) -> List[Recurso]:
        """Reordena los recursos multimedia moviendo el elemento en from_index a to_index."""
        items = sorted(self.recursos.values(), key=lambda r: r.orden)
        if not (0 <= from_index < len(items) and 0 <= to_index < len(items)):
            raise ValueError(f"Índices de reordenamiento fuera de rango: from_index={from_index}, to_index={to_index} (total: {len(items)})")
        item = items.pop(from_index)
        items.insert(to_index, item)
        self._sincronizar_orden_recursos(items)
        return items

    def reordenar_por_ids(self, orden_ids: List[str]) -> List[Recurso]:
        """Reordena los recursos multimedia según una lista ordenada de IDs."""
        items_map = {r.id: r for r in self.recursos.values()}
        nuevos: List[Recurso] = []
        for rid in orden_ids:
            if rid in items_map:
                nuevos.append(items_map.pop(rid))
        for sobrante in sorted(items_map.values(), key=lambda r: r.orden):
            nuevos.append(sobrante)
        self._sincronizar_orden_recursos(nuevos)
        return nuevos

    def reordenar_por_indices(self, orden_indices: List[int]) -> List[Recurso]:
        """Reordena los recursos multimedia según una lista ordenada de índices."""
        items = sorted(self.recursos.values(), key=lambda r: r.orden)
        nuevos: List[Recurso] = []
        vistos = set()
        for idx in orden_indices:
            if 0 <= idx < len(items) and idx not in vistos:
                nuevos.append(items[idx])
                vistos.add(idx)
        for i, item in enumerate(items):
            if i not in vistos:
                nuevos.append(item)
        self._sincronizar_orden_recursos(nuevos)
        return nuevos

    def eliminar_multimedia(self, elemento: Union[str, int]) -> Optional[Recurso]:
        """Elimina un recurso multimedia por ID (str) o por índice (int) y actualiza el vector."""
        items = sorted(self.recursos.values(), key=lambda r: r.orden)
        if isinstance(elemento, int) or (
            isinstance(elemento, str) and elemento.isdigit() and elemento not in self.recursos
        ):
            idx = int(elemento)
            if not (0 <= idx < len(items)):
                return None
            rec_id = items[idx].id
        else:
            rec_id = str(elemento)
            if rec_id not in self.recursos:
                return None

        eliminado = self.recursos.pop(rec_id, None)
        restantes = [r for r in items if r.id != rec_id]
        self._sincronizar_orden_recursos(restantes)
        return eliminado

    def agregar_multimedia(self, recurso: Recurso, posicion: Optional[int] = None) -> Recurso:
        """Inserta o añade un nuevo recurso multimedia en la posición indicada o al final."""
        items = sorted([r for r in self.recursos.values() if r.id != recurso.id], key=lambda r: r.orden)
        if posicion is None or posicion < 0 or posicion >= len(items):
            items.append(recurso)
        else:
            items.insert(posicion, recurso)
        self._sincronizar_orden_recursos(items)
        return recurso

    def _sincronizar_orden_recursos(self, items_ordenados: List[Recurso]) -> None:
        """Sincroniza el diccionario de recursos, sus atributos orden y los vectores numéricos."""
        for i, r in enumerate(items_ordenados):
            r.orden = i
        self.recursos = {r.id: r for r in items_ordenados}
        vec = list(range(len(items_ordenados)))
        self.orden_multimedia = list(vec)
        self.posiciones = list(vec)
        if self.conforme:
            self.conforme = False
            self.conforme_en = None
            self.conformidad_invalidada = True

    @property
    def texto_original_aprobado(self) -> Optional[str]:
        return self.texto_original_conforme

    @texto_original_aprobado.setter
    def texto_original_aprobado(self, val: Optional[str]) -> None:
        self.texto_original_conforme = val


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
        description="Atajo de botón ('confirmar_texto', 'enriquecer', 'descartar', 'continuar', 'editar', 'sanitizar', 'conforme', 'copiar_borrador', 'rechazar', 'reiniciar')."
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
    multimedia_habilitada: bool = Field(
        default=False,
        description="True una vez superada buscar_duplicados (en cualquier rama): el mini panel multimedia está operativo.",
    )
    validacion: Optional[ValidarFormatoResponse] = None
    aviso_privacidad: Optional[str] = Field(
        default=None,
        description="Notificación puntual ('flash') emitida cuando se detectan y anonimizan datos sensibles en el turno actual."
    )
    aviso_metadatos_heredados: Optional[str] = Field(
        default=None,
        description="Aviso informativo cuando el borrador heredó metadatos de una versión anterior que aún no fueron confirmados.",
    )
