from enum import Enum
import re
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ValidationInfo, computed_field, field_validator, model_validator

from baco.server.config_limites import MAX_BLOQUES_TEXTO, TEXTO_MAX, TEXTO_MAX_PERCENTIL_99, TITULO_MAX
from baco.server.schemas.validacion import ValidarFormatoResponse
from baco.server.schemas.recurso import Recurso

_RE_MARCADOR_LEGACY = re.compile(r"\[\[recurso:[a-zA-Z0-9_\-]+\]\]")
_RE_CUALQUIER_MARCADOR = re.compile(r"\[\[(?:recurso:([a-zA-Z0-9_\-]+)|(R\d+))\]\]")


def _sanitizar_y_validar_bloques(
    bloques_raw: List[str],
    recursos_dict: Optional[Dict[str, Any]] = None,
    texto_base_limpio: Optional[str] = None,
) -> List[str]:
    """Valida que los bloques no contengan marcadores y aplica autosanitización PII/secretos."""
    from baco.server.services.validar_articulo import _limpiar_texto_sensible

    bloques_limpios: List[str] = []
    recs = recursos_dict if isinstance(recursos_dict, dict) else {}
    base = (texto_base_limpio or "").strip()
    parrafos_base = {p.strip() for p in re.split(r"\n\s*\n", base) if p.strip()} if base else set()

    for b in bloques_raw or []:
        if not isinstance(b, str):
            b = str(b)
        marcadores_r = re.findall(r"\[\[R\d+\]\]", b)
        if marcadores_r:
            raise ValueError(
                f"El texto contiene marcadores no canónicos ({', '.join(marcadores_r)}). "
                f"No se permiten marcadores en bloques_texto."
            )
        marcadores_rec = re.findall(r"\[\[recurso:([a-zA-Z0-9_\-]+)\]\]", b)
        if marcadores_rec:
            invalidos = [m for m in marcadores_rec if m not in recs]
            if invalidos:
                raise ValueError(
                    f"El texto contiene marcadores que no referencian ningún recurso existente: "
                    f"{', '.join(f'[[recurso:{m}]]' for m in invalidos)}. "
                    f"No se permite ingresar marcadores manualmente."
                )
            raise ValueError(
                "bloques_texto no puede contener marcadores [[recurso:...]]; "
                "los recursos se ubican mediante su atributo posicion."
            )
        b_strip = b.strip()
        if b_strip:
            if base and (b_strip == base or b_strip in parrafos_base):
                b_san = b_strip
            elif base and base in b_strip:
                pre, post = b_strip.split(base, 1)
                pre_san = _limpiar_texto_sensible(pre.strip())[0] if pre.strip() else ""
                post_san = _limpiar_texto_sensible(post.strip())[0] if post.strip() else ""
                b_san = "\n\n".join(p.strip() for p in (pre_san, base, post_san) if p and p.strip())
            else:
                b_san, _ = _limpiar_texto_sensible(b_strip)
            if b_san.strip():
                bloques_limpios.append(b_san.strip())

    if len(bloques_limpios) > MAX_BLOQUES_TEXTO:
        raise ValueError(
            f"La cantidad de bloques de texto ({len(bloques_limpios)}) supera el máximo permitido de {MAX_BLOQUES_TEXTO}."
        )
    return bloques_limpios


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


class BotonOpcion(BaseModel):
    accion: str = Field(..., description="Identificador de la acción ('volver', 'confirmar_texto', etc.)")
    label: str = Field(..., description="Texto visible del botón ('Volver', 'Confirmar texto', etc.)")
    estilo: str = Field(default="btn-ghost", description="Clase CSS del botón")


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
    bloques_texto: List[str] = Field(
        default_factory=list,
        description="Fuente de verdad única del texto: lista ordenada de bloques de texto limpio (sin marcadores).",
    )
    recursos: Dict[str, Recurso] = Field(default_factory=dict)
    ultimo_id_recurso: int = Field(
        default=0,
        description="Contador monotónico por borrador que nunca reutiliza el ID de un recurso eliminado.",
    )
    texto_base_limpio: str = ""
    texto_en_edicion: str = ""
    texto_editor: Optional[str] = Field(
        default=None,
        description="Texto escrito exclusivamente por la persona en el Editor, independiente de la Vista previa.",
    )
    orden_multimedia: List[int] = Field(
        default_factory=list,
        description="Vector numérico que guarda el orden explícito de los contenidos multimedia en el borrador."
    )
    posiciones: List[int] = Field(
        default_factory=list,
        description="Vector numérico con las posiciones de bloque de los contenidos multimedia."
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
    categoria_nombre: Optional[str] = Field(
        default=None,
        description="Nombre legible de la categoría para visualización y resúmenes."
    )
    tags: List[str] = Field(default_factory=list)
    metadatos_anteriores: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Metadatos heredados del artículo original: categoria_id, categoria_nombre, tags",
    )
    revision_intermedia: bool = Field(
        default=False,
        description="True durante revision intermedia.",
    )
    texto_base_revision_final: Optional[str] = Field(
        default=None,
        description="Texto base revision final.",
    )
    metadatos_heredados_revisados: bool = Field(
        default=False,
        description="Indica si el usuario ya revisó o confirmó los metadatos heredados.",
    )

    @model_validator(mode="before")
    @classmethod
    def preparar_datos_borrador(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            # Seguridad: el cliente no puede forzar flags ni campos derivados calculados por el servidor
            data.pop("skills_habilitadas", None)
            data.pop("skills_motivo", None)
            data.pop("texto_alineado_discourse", None)

            tiene_bloques = "bloques_texto" in data and data["bloques_texto"] is not None
            txt = data.pop("texto", None)
            txt_limpio = data.pop("texto_limpio", None)

            if not tiene_bloques:
                if txt_limpio is not None:
                    v = str(txt_limpio)
                    marcadores_legacy_r = re.findall(r"\[\[R\d+\]\]", v)
                    if marcadores_legacy_r:
                        raise ValueError(
                            f"El texto contiene marcadores no canónicos ({', '.join(marcadores_legacy_r)}). "
                            f"El marcador canónico único es [[recurso:rec_N]]."
                        )
                    marcadores_recurso = re.findall(r"\[\[recurso:([a-zA-Z0-9_\-]+)\]\]", v)
                    recursos_raw = data.get("recursos")
                    recursos_dict = dict(recursos_raw) if isinstance(recursos_raw, dict) else {}
                    if marcadores_recurso:
                        invalidos = [m for m in marcadores_recurso if m not in recursos_dict]
                        if invalidos:
                            raise ValueError(
                                f"El texto contiene marcadores que no referencian ningún recurso existente: "
                                f"{', '.join(f'[[recurso:{m}]]' for m in invalidos)}. "
                                f"No se permite ingresar marcadores manualmente."
                            )
                        # Convertir texto con marcadores válidos en bloques_texto limpios + posicion en recursos
                        partes = re.split(r"(\[\[recurso:[a-zA-Z0-9_\-]+\]\])", v)
                        bloques_derivados: List[str] = []
                        orden_vista = 0
                        for parte in partes:
                            m_rec = re.fullmatch(r"\[\[recurso:([a-zA-Z0-9_\-]+)\]\]", parte.strip())
                            if m_rec:
                                rid = m_rec.group(1)
                                rec_item = recursos_dict.get(rid)
                                pos_calc = len(bloques_derivados) - 1
                                if isinstance(rec_item, dict):
                                    rec_item = dict(rec_item)
                                    rec_item["posicion"] = pos_calc
                                    rec_item["orden"] = orden_vista
                                    recursos_dict[rid] = rec_item
                                elif hasattr(rec_item, "model_copy"):
                                    recursos_dict[rid] = rec_item.model_copy(
                                        update={"posicion": pos_calc, "orden": orden_vista}
                                    )
                                orden_vista += 1
                            else:
                                sub_bloques = [b.strip() for b in re.split(r"\n\s*\n", parte) if b.strip()]
                                bloques_derivados.extend(sub_bloques)
                        data["bloques_texto"] = bloques_derivados
                        data["recursos"] = recursos_dict
                    else:
                        s = v.strip()
                        if not s:
                            data["bloques_texto"] = []
                        elif recursos_dict:
                            data["bloques_texto"] = [b.strip() for b in re.split(r"\n\s*\n", s) if b.strip()]
                        else:
                            data["bloques_texto"] = [s]
                elif txt:
                    from baco.server.services.orquestador.recursos_service import extraer_recursos_y_bloques_texto
                    bloques_ext, recs = extraer_recursos_y_bloques_texto(str(txt))
                    data["bloques_texto"] = bloques_ext
                    if recs and not data.get("recursos"):
                        data["recursos"] = recs
                else:
                    data["bloques_texto"] = []

            cid = data.get("categoria_id")
            if cid is not None and not data.get("categoria_nombre"):
                try:
                    from baco.server.services.orquestador.validaciones import DICCIONARIO_OFICIAL_CATEGORIAS
                    if int(cid) in DICCIONARIO_OFICIAL_CATEGORIAS:
                        data["categoria_nombre"] = DICCIONARIO_OFICIAL_CATEGORIAS[int(cid)]
                except Exception:
                    pass
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def texto_limpio(self) -> str:
        """Texto limpio derivado de bloques_texto (nunca contiene marcadores ni recursos)."""
        return "\n\n".join(b for b in self.bloques_texto if b).strip()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def texto_alineado_discourse(self) -> str:
        """Vista compuesta derivada para Discourse: intercala bloques_texto y recursos según (posicion, orden)."""
        from baco.server.services.orquestador.recursos_service import componer_texto_publicable
        return componer_texto_publicable(self.bloques_texto, self.recursos)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def skills_habilitadas(self) -> bool:
        """Indica si las skills del agente están habilitadas para el borrador.

        Calculado estrictamente en el servidor:
        False si el largo efectivo supera TEXTO_MAX (6687).
        """
        from baco.server.config_limites import TEXTO_MAX
        from baco.server.services.orquestador.recursos_service import texto_efectivo_sin_marcadores

        largo = len(texto_efectivo_sin_marcadores(self.texto_limpio or ""))
        if largo > TEXTO_MAX:
            return False
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def skills_motivo(self) -> Optional[str]:
        """Texto explicativo del motivo por el cual las skills están deshabilitadas."""
        from baco.server.config_limites import TEXTO_MAX
        from baco.server.services.orquestador.recursos_service import texto_efectivo_sin_marcadores

        largo = len(texto_efectivo_sin_marcadores(self.texto_limpio or ""))
        if largo > TEXTO_MAX:
            return (
                f"El texto supera el límite de {TEXTO_MAX} caracteres para el uso de skills "
                f"({largo} caracteres recibidos)."
            )
        return None


    @model_validator(mode="after")
    def sincronizar_bloques_y_vector_multimedia(self) -> "BorradorSesion":
        """Sanitiza bloques_texto (PII/secretos) y garantiza los invariantes de recursos:
        - posicion en [-1, len(bloques_texto) - 1]
        - orden único y contiguo 0..N-1
        - recursos ordenados por (posicion, orden)
        """
        base_api = self.texto_base_limpio if self.modo == "enriquecimiento" else None
        bloques_sanitizados = _sanitizar_y_validar_bloques(self.bloques_texto, self.recursos, texto_base_limpio=base_api)
        super().__setattr__("bloques_texto", bloques_sanitizados)

        from baco.server.services.validar_articulo import sanitizar_borrador
        if self.titulo:
            res_tit = sanitizar_borrador(texto="", titulo=self.titulo, sanitizar_redundancia_titulo=False)
            super().__setattr__("titulo", res_tit["titulo_sanitizado"] or self.titulo)

        items = list(self.recursos.values())
        self._sincronizar_orden_recursos(items, invalidar_conformidad=False)
        return self

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("texto", "texto_alineado_discourse"):
            raise AttributeError(f"'{name}' no es un atributo asignable en BorradorSesion.")
        if name == "texto_limpio":
            v = str(value or "")
            marcadores_r = re.findall(r"\[\[R\d+\]\]", v)
            if marcadores_r:
                raise ValueError(f"Marcadores no permitidos: {marcadores_r}")
            v_sin_marc = _RE_MARCADOR_LEGACY.sub("", v).strip()
            if v_sin_marc == self.texto_limpio and self.bloques_texto:
                return
            if not v_sin_marc:
                nuevos_bloques: List[str] = []
            elif self.recursos and len(self.bloques_texto) > 1:
                nuevos_bloques = [b.strip() for b in re.split(r"\n\s*\n", v_sin_marc) if b.strip()]
            else:
                nuevos_bloques = [v_sin_marc]
            self.__setattr__("bloques_texto", nuevos_bloques)
            return
        if name == "bloques_texto":
            base_api = getattr(self, "texto_base_limpio", None) if getattr(self, "modo", None) == "enriquecimiento" else None
            bloques_san = _sanitizar_y_validar_bloques(value or [], getattr(self, "recursos", None), texto_base_limpio=base_api)
            super().__setattr__("bloques_texto", bloques_san)
            if hasattr(self, "recursos"):
                self._sincronizar_orden_recursos(list(self.recursos.values()), invalidar_conformidad=False)
            return
        super().__setattr__(name, value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def multimedia(self) -> List[Recurso]:
        """Lista de recursos multimedia ordenados por (posicion, orden)."""
        return sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))

    def reordenar_recurso(
        self,
        elemento: Union[str, int],
        nueva_posicion: Optional[int] = None,
        nuevo_orden: Optional[int] = None,
    ) -> List[Recurso]:
        """Mueve un recurso (identificado por ID o por su índice de orden actual)
        a un nuevo (posicion, orden), preservando invariantes:
        - posicion en [-1, len(bloques_texto) - 1]
        - orden único y contiguo 0..N-1
        - recursos ordenados por (posicion, orden)
        """
        items = sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))
        if not items:
            raise ValueError("No hay recursos para reordenar.")

        target_idx: Optional[int] = None
        if isinstance(elemento, int) or (
            isinstance(elemento, str) and elemento.isdigit() and elemento not in self.recursos
        ):
            idx = int(elemento)
            if 0 <= idx < len(items):
                target_idx = idx
        else:
            rid = str(elemento)
            for i, r in enumerate(items):
                if r.id == rid:
                    target_idx = i
                    break

        if target_idx is None:
            raise ValueError(f"Recurso o índice fuera de rango: {elemento}")

        max_pos = len(self.bloques_texto) - 1
        # Si no se especifica nueva_posicion pero sí nuevo_orden, adopta la posicion del slot destino
        if nueva_posicion is not None:
            pos_destino = max(-1, min(int(nueva_posicion), max_pos))
        elif nuevo_orden is not None:
            idx_slot = max(0, min(int(nuevo_orden), len(items) - 1))
            pos_destino = max(-1, min(items[idx_slot].posicion, max_pos))
        else:
            pos_destino = max(-1, min(items[target_idx].posicion, max_pos))

        item = items.pop(target_idx)
        item.posicion = pos_destino

        # Determinar rango de índices válidos para pos_destino manteniendo orden por posicion
        first_idx = 0
        while first_idx < len(items) and items[first_idx].posicion < pos_destino:
            first_idx += 1
        last_idx = first_idx
        while last_idx < len(items) and items[last_idx].posicion == pos_destino:
            last_idx += 1

        if nuevo_orden is not None:
            ins_idx = max(first_idx, min(int(nuevo_orden), last_idx))
        else:
            ins_idx = last_idx

        items.insert(ins_idx, item)
        self._sincronizar_orden_recursos(items)
        return sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))

    def reorder(
        self,
        from_index: int,
        to_index: int,
        nueva_posicion: Optional[int] = None,
    ) -> List[Recurso]:
        """Reordena los recursos multimedia moviendo el elemento en from_index a to_index."""
        items = sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))
        if not (0 <= from_index < len(items) and 0 <= to_index < len(items)):
            raise ValueError(
                f"Índices de reordenamiento fuera de rango: from_index={from_index}, to_index={to_index} (total: {len(items)})"
            )
        if nueva_posicion is not None:
            return self.reordenar_recurso(from_index, nueva_posicion=nueva_posicion, nuevo_orden=to_index)

        posiciones_slots = [r.posicion for r in items]
        item = items.pop(from_index)
        items.insert(to_index, item)
        for i, r in enumerate(items):
            r.posicion = posiciones_slots[i]
        self._sincronizar_orden_recursos(items)
        return sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))

    def reordenar_por_ids(self, orden_ids: List[str]) -> List[Recurso]:
        """Reordena los recursos multimedia según una lista ordenada de IDs."""
        items_antes = sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))
        posiciones_slots = [r.posicion for r in items_antes]
        items_map = {r.id: r for r in items_antes}
        nuevos: List[Recurso] = []
        for rid in orden_ids:
            if rid in items_map:
                nuevos.append(items_map.pop(rid))
        for sobrante in sorted(items_map.values(), key=lambda r: (r.posicion, r.orden)):
            nuevos.append(sobrante)
        for i, r in enumerate(nuevos):
            r.posicion = posiciones_slots[i]
        self._sincronizar_orden_recursos(nuevos)
        return sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))

    def reordenar_por_indices(self, orden_indices: List[int]) -> List[Recurso]:
        """Reordena los recursos multimedia según una lista ordenada de índices."""
        items = sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))
        posiciones_slots = [r.posicion for r in items]
        nuevos: List[Recurso] = []
        vistos = set()
        for idx in orden_indices:
            if 0 <= idx < len(items) and idx not in vistos:
                nuevos.append(items[idx])
                vistos.add(idx)
        for i, item in enumerate(items):
            if i not in vistos:
                nuevos.append(item)
        for i, r in enumerate(nuevos):
            r.posicion = posiciones_slots[i]
        self._sincronizar_orden_recursos(nuevos)
        return sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))

    def eliminar_multimedia(self, elemento: Union[str, int]) -> Optional[Recurso]:
        """Elimina un recurso multimedia por ID (str) o por índice (int).
        Regla de fusión de bloques:
        Fusiona bloques_texto[pos] y bloques_texto[pos + 1] SOLO si:
        - pos >= 0 y pos < len(bloques_texto) - 1
        - ningún otro recurso restante queda con esa misma posicion == pos.
        Si posicion == -1 o queda otro recurso con la misma posicion, no fusiona.
        """
        items = sorted(self.recursos.values(), key=lambda r: (r.posicion, r.orden))
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

        m = re.fullmatch(r"rec_(\d+)", str(rec_id))
        if m:
            super().__setattr__("ultimo_id_recurso", max(self.ultimo_id_recurso, int(m.group(1))))

        eliminado = self.recursos.pop(rec_id, None)
        if eliminado is None:
            return None

        pos = eliminado.posicion
        restantes = [r for r in items if r.id != rec_id]

        # Fusión condicional de bloques_texto[pos] y bloques_texto[pos + 1]
        hay_otro_en_misma_pos = any(r.posicion == pos for r in restantes)
        if 0 <= pos < len(self.bloques_texto) - 1 and not hay_otro_en_misma_pos:
            b_izq = self.bloques_texto[pos].strip()
            b_der = self.bloques_texto[pos + 1].strip()
            fusionado = f"{b_izq}\n\n{b_der}".strip() if (b_izq and b_der) else (b_izq or b_der)
            nuevos_bloques = (
                list(self.bloques_texto[:pos])
                + ([fusionado] if fusionado else [])
                + list(self.bloques_texto[pos + 2 :])
            )
            super().__setattr__("bloques_texto", nuevos_bloques)
            for r in restantes:
                if r.posicion > pos:
                    r.posicion -= 1

        self._sincronizar_orden_recursos(restantes)
        return eliminado

    def agregar_multimedia(
        self,
        recurso: Recurso,
        posicion: Optional[int] = None,
        orden: Optional[int] = None,
    ) -> Recurso:
        """Inserta o añade un recurso multimedia respetando (posicion, orden) y los invariantes."""
        items = sorted(
            [r for r in self.recursos.values() if r.id != recurso.id],
            key=lambda r: (r.posicion, r.orden),
        )
        max_pos = len(self.bloques_texto) - 1
        if posicion is not None:
            pos_final = max(-1, min(int(posicion), max_pos))
        elif "posicion" in recurso.model_fields_set:
            pos_final = max(-1, min(int(recurso.posicion), max_pos))
        else:
            pos_final = max_pos

        recurso.posicion = pos_final

        first_idx = 0
        while first_idx < len(items) and items[first_idx].posicion < pos_final:
            first_idx += 1
        last_idx = first_idx
        while last_idx < len(items) and items[last_idx].posicion == pos_final:
            last_idx += 1

        if orden is not None:
            ins_idx = max(first_idx, min(int(orden), last_idx))
        elif posicion is not None:
            ins_idx = max(first_idx, min(int(posicion), last_idx))
        else:
            ins_idx = last_idx

        items.insert(ins_idx, recurso)
        self._sincronizar_orden_recursos(items)
        return self.recursos[recurso.id]

    def _sincronizar_orden_recursos(
        self,
        items_ordenados: List[Recurso],
        invalidar_conformidad: bool = True,
    ) -> None:
        """Garantiza invariantes:
        - posicion en [-1, len(bloques_texto) - 1]
        - recursos ordenados por (posicion, orden_relativo)
        - orden único y contiguo 0..N-1
        """
        max_pos = len(self.bloques_texto) - 1
        for r in items_ordenados:
            if r.posicion < -1:
                r.posicion = -1
            elif r.posicion > max_pos:
                r.posicion = max_pos

        # Ordenar de forma estable por posicion conservando el orden relativo dentro de cada posicion
        ordenados = [
            r for _, r in sorted(enumerate(items_ordenados), key=lambda pair: (pair[1].posicion, pair[0]))
        ]

        max_num = self.ultimo_id_recurso
        for i, r in enumerate(ordenados):
            r.orden = i
            m = re.fullmatch(r"rec_(\d+)", str(r.id))
            if m:
                max_num = max(max_num, int(m.group(1)))

        super().__setattr__("ultimo_id_recurso", max_num)
        super().__setattr__("recursos", {r.id: r for r in ordenados})
        vec = list(range(len(ordenados)))
        super().__setattr__("orden_multimedia", list(vec))
        super().__setattr__("posiciones", [r.posicion for r in ordenados])
        if invalidar_conformidad and self.conforme:
            super().__setattr__("conforme", False)
            super().__setattr__("conforme_en", None)
            super().__setattr__("conformidad_invalidada", True)

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
    texto_editor: Optional[str] = Field(
        default=None,
        description="Texto escrito exclusivamente por la persona en el Editor."
    )
    categoria_id: Optional[int] = Field(
        default=None,
        description="Categoría o ID de módulo ERP del borrador."
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Lista de tags del borrador."
    )
    aviso_privacidad_detectado: Optional[str] = Field(
        default=None,
        exclude=True,
        description="Aviso de privacidad detectado en las entradas del request.",
    )

    @model_validator(mode="before")
    @classmethod
    def sanitizar_entradas_sensibles(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        from baco.server.services.validar_articulo import sanitizar_borrador

        sid = data.get("session_id")
        base_api = None
        if sid:
            from baco.server.services.orquestador.sesion import gestor_sesiones
            ses = gestor_sesiones.obtener_sesion(sid)
            if ses and ses.borrador and ses.borrador.modo == "enriquecimiento" and ses.borrador.texto_base_limpio:
                base_api = ses.borrador.texto_base_limpio

        avisos = []
        for campo in ("mensaje", "texto", "texto_editor"):
            val = data.get(campo)
            if isinstance(val, str) and val.strip():
                if base_api and base_api in val:
                    from baco.server.services.orquestador.validaciones import consolidar_texto_enriquecimiento
                    val_cons, av = consolidar_texto_enriquecimiento(base_api, val)
                    data[campo] = val_cons
                    if av:
                        avisos.append(av)
                else:
                    res = sanitizar_borrador(texto=val, sanitizar_redundancia_titulo=False)
                    data[campo] = res["texto_sanitizado"]
                    if res.get("aviso_privacidad"):
                        avisos.append(res["aviso_privacidad"])

        val_tit = data.get("titulo")
        if isinstance(val_tit, str) and val_tit.strip():
            res_tit = sanitizar_borrador(texto="", titulo=val_tit, sanitizar_redundancia_titulo=False)
            data["titulo"] = res_tit["titulo_sanitizado"] or val_tit
            if res_tit.get("aviso_privacidad"):
                avisos.append(res_tit["aviso_privacidad"])

        tags_raw = data.get("tags")
        if isinstance(tags_raw, list):
            tags_sanitizados = []
            for t in tags_raw:
                if isinstance(t, str) and t.strip():
                    res_t = sanitizar_borrador(texto=t, sanitizar_redundancia_titulo=False)
                    tags_sanitizados.append(res_t["texto_sanitizado"])
                    if res_t.get("aviso_privacidad"):
                        avisos.append(res_t["aviso_privacidad"])
                else:
                    tags_sanitizados.append(t)
            data["tags"] = tags_sanitizados

        if avisos:
            data["aviso_privacidad_detectado"] = "\n".join(dict.fromkeys(avisos))

        return data

    @field_validator("texto", "mensaje", "texto_editor", mode="before")
    @classmethod
    def validar_longitud_texto(cls, v: Optional[str]) -> Optional[str]:
        if v and len(v) > TEXTO_MAX_PERCENTIL_99:
            from baco.server.services.orquestador.recursos_service import (
                extraer_recursos_y_texto_limpio,
                texto_efectivo_sin_marcadores,
            )
            tl, _ = extraer_recursos_y_texto_limpio(str(v))
            if len(texto_efectivo_sin_marcadores(tl)) > TEXTO_MAX_PERCENTIL_99:
                raise ValueError(f"El texto supera los {TEXTO_MAX_PERCENTIL_99} caracteres. Dividilo o resumilo.")
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
    botones: List[BotonOpcion] = Field(
        default_factory=list,
        description="Botones inyectados dinámicamente por el servidor.",
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
    titulo: Optional[str] = Field(default=None, description="Título limpio y sanitizado actual de la sesión o borrador.")
    texto_limpio: Optional[str] = Field(
        default=None,
        description="Texto limpio y sanitizado actual de la sesión o borrador."
    )
    multimedia_habilitada: bool = Field(
        default=False,
        description="True una vez superada buscar_duplicados (en cualquier rama): el mini panel multimedia está operativo.",
    )
    skills_habilitadas: bool = Field(
        default=True,
        description="Indica si las skills del agente están habilitadas para el borrador actual (calculado en el servidor).",
    )
    skills_motivo: Optional[str] = Field(
        default=None,
        description="Motivo explicativo si las skills están deshabilitadas.",
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

    @model_validator(mode="before")
    @classmethod
    def poblar_botones(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("botones"):
                from baco.server.services.orquestador.mensajes import DESCRIPTORES_BOTONES
                ops = data.get("opciones") or []
                bts = []
                for op in ops:
                    if isinstance(op, str):
                        desc = DESCRIPTORES_BOTONES.get(
                            op,
                            {"accion": op, "label": op.replace("_", " ").capitalize(), "estilo": "btn-ghost"},
                        )
                        bts.append(desc)
                    elif isinstance(op, dict):
                        bts.append(op)
                data["botones"] = bts
        return data
