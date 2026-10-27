import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Dict, List, Optional, Tuple, Union

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    CategoriaOpcion,
    CoincidenciaArticulo,
    EstadoFlujo,
    ItemContenidoAdicional,
)
from baco.server.schemas.recurso import Recurso
from baco.server.schemas.validacion import ValidarFormatoResponse
from baco.server.services.orquestador.excepciones import (
    EstadoInvalidoError,
    SesionNoEncontradaError,
)
from baco.server.services.orquestador.recursos_service import (
    _max_num_recurso,
    _normalizar_invariantes_recursos,
    eliminar_recurso_borrador as servicio_eliminar_recurso,
    componer_texto_publicable,
    extraer_recursos_y_bloques_texto,
    fusionar_bloques_y_recursos_sin_colision,
    limpiar_archivos_temporales_sesion,
)
from baco.server.services.validar_articulo import sanitizar_borrador


@dataclass
class SesionChat:
    session_id: str
    estado: EstadoFlujo = EstadoFlujo.ESPERANDO_TITULO
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    titulo: str = ""
    texto: str = ""
    texto_limpio: str = ""
    bloques_texto: List[str] = field(default_factory=list)
    texto_en_edicion: str = ""
    recursos: Dict[str, Recurso] = field(default_factory=dict)
    ultimo_id_recurso: int = 0
    orden_multimedia: List[int] = field(default_factory=list)
    posiciones: List[int] = field(default_factory=list)
    contenido_adicional: List[ItemContenidoAdicional] = field(default_factory=list)
    categoria_id: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    metadatos_anteriores: Optional[Dict[str, Any]] = None
    metadatos_heredados_revisados: bool = False
    coincidencias: List[CoincidenciaArticulo] = field(default_factory=list)
    borrador: Optional[BorradorSesion] = None
    validacion: Optional[ValidarFormatoResponse] = None
    categorias_disponibles: List[CategoriaOpcion] = field(default_factory=list)
    tags_disponibles: List[str] = field(default_factory=list)
    intentos_correccion: int = 0
    intentos_fallidos_por_estado: Dict[str, int] = field(default_factory=dict)
    confirmando_rechazo: bool = False
    articulos_descartados_ids: List[int] = field(default_factory=list)
    descarto_serie: bool = False

    def registrar_fallo(self, estado_clave: Optional[str] = None) -> int:
        clave = estado_clave or self.estado.value
        actual = self.intentos_fallidos_por_estado.get(clave, 0)
        self.intentos_fallidos_por_estado[clave] = actual + 1
        return actual

    def limpiar_fallos(self, estado_clave: Optional[str] = None) -> None:
        clave = estado_clave or self.estado.value
        self.intentos_fallidos_por_estado.pop(clave, None)

    def actualizar_contenido_borrador(
        self,
        *,
        bloques_texto: Optional[List[str]] = None,
        texto_limpio: Optional[str] = None,
        recursos: Optional[Dict[str, Recurso]] = None,
        ultimo_id_recurso: Optional[int] = None,
        texto: Optional[str] = None,
        texto_base_limpio: Optional[str] = None,
        texto_en_edicion: Optional[str] = None,
        titulo: Optional[str] = None,
        categoria_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
        tipo_plantilla: Optional[str] = None,
    ) -> None:
        """Sincroniza atómicamente los bloques de texto, recursos y metadatos entre la sesión y su borrador."""
        if titulo is not None:
            self.titulo = titulo.strip()
            if self.borrador is not None:
                self.borrador.titulo = self.titulo

        if bloques_texto is not None:
            if self.borrador is not None:
                self.borrador.bloques_texto = list(bloques_texto)
                self.bloques_texto = list(self.borrador.bloques_texto)
                self.texto_limpio = self.borrador.texto_limpio
            else:
                self.bloques_texto = [b.strip() for b in bloques_texto if b and b.strip()]
                self.texto_limpio = "\n\n".join(self.bloques_texto).strip()
        elif texto_limpio is not None:
            if self.borrador is not None:
                self.borrador.texto_limpio = texto_limpio
                self.bloques_texto = list(self.borrador.bloques_texto)
                self.texto_limpio = self.borrador.texto_limpio
            else:
                self.texto_limpio = texto_limpio
                self.bloques_texto = [texto_limpio.strip()] if texto_limpio.strip() else []

        if recursos is not None:
            max_rec = _max_num_recurso(recursos)
            self.ultimo_id_recurso = max(self.ultimo_id_recurso, max_rec, ultimo_id_recurso or 0)
            if self.borrador is not None:
                self.borrador.ultimo_id_recurso = max(self.borrador.ultimo_id_recurso, self.ultimo_id_recurso)
                self.borrador._sincronizar_orden_recursos(
                    list(recursos.values()), invalidar_conformidad=False
                )
                self.recursos = dict(self.borrador.recursos)
                self.orden_multimedia = list(self.borrador.orden_multimedia)
                self.posiciones = list(self.borrador.posiciones)
            else:
                recs_norm = _normalizar_invariantes_recursos(recursos, len(self.bloques_texto) if self.bloques_texto else None)
                self.recursos = recs_norm
                self.orden_multimedia = list(range(len(recs_norm)))
                self.posiciones = [r.posicion for r in recs_norm.values()]
        elif ultimo_id_recurso is not None:
            self.ultimo_id_recurso = max(self.ultimo_id_recurso, ultimo_id_recurso)
            if self.borrador is not None:
                self.borrador.ultimo_id_recurso = self.ultimo_id_recurso

        if texto_base_limpio is not None:
            if self.borrador is not None:
                self.borrador.texto_base_limpio = texto_base_limpio

        if texto_en_edicion is not None:
            self.texto_en_edicion = texto_en_edicion
            if self.borrador is not None:
                self.borrador.texto_en_edicion = texto_en_edicion

        if texto is not None:
            self.texto = texto
        elif self.borrador is not None:
            self.texto = self.borrador.texto_alineado_discourse
        elif bloques_texto is not None or texto_limpio is not None:
            self.texto = componer_texto_publicable(
                self.bloques_texto if self.bloques_texto else self.texto_limpio,
                self.recursos,
            )

        if categoria_id is not None:
            self.categoria_id = categoria_id
            if self.borrador is not None:
                self.borrador.categoria_id = categoria_id

        if tags is not None:
            self.tags = list(tags)
            if self.borrador is not None:
                self.borrador.tags = list(tags)

        if tipo_plantilla is not None and self.borrador is not None:
            self.borrador.tipo_plantilla = tipo_plantilla


# Estados en los que todavía se está resolviendo la deduplicación (o no empezó)
_ESTADOS_PREVIOS_A_DEDUPLICACION = frozenset({
    EstadoFlujo.ESPERANDO_TITULO,
    EstadoFlujo.DECISION_TITULO,
    EstadoFlujo.DECISION_TEXTO,
    EstadoFlujo.RECHAZADO,
})


def multimedia_habilitada(sesion: Optional[SesionChat]) -> bool:
    """Criterio único: el mini panel multimedia está operativo una vez superada buscar_duplicados.

    Cubre las tres ramas (sin coincidencias, coincidencias descartadas y enriquecer/actualizar),
    porque todas crean el borrador al salir de la deduplicación. No depende de `modo`.
    """
    return (
        sesion is not None
        and sesion.borrador is not None
        and sesion.estado not in _ESTADOS_PREVIOS_A_DEDUPLICACION
    )


def _sanitizar_y_clonar_borrador(borrador: BorradorSesion, sesion: Optional[SesionChat] = None) -> BorradorSesion:
    ultimo_id = max(
        borrador.ultimo_id_recurso,
        _max_num_recurso(borrador.recursos),
        sesion.ultimo_id_recurso if sesion else 0,
    )
    if borrador.bloques_texto:
        bloques_actuales = list(borrador.bloques_texto)
        if borrador.modo == "enriquecimiento" and borrador.texto_base_limpio:
            base_limpio = borrador.texto_base_limpio.strip()
            unido = "\n\n".join(bloques_actuales)
            if base_limpio and base_limpio not in unido:
                bloques_actuales = [base_limpio] + bloques_actuales
        limpio_tit = sanitizar_borrador(texto="", titulo=borrador.titulo)
        borrador.titulo = limpio_tit["titulo_sanitizado"] or borrador.titulo
        borrador.bloques_texto = bloques_actuales
    else:
        bloques_ext, recs = extraer_recursos_y_bloques_texto(
            borrador.texto_alineado_discourse,
            recursos_previos=borrador.recursos,
            ultimo_id=ultimo_id,
        )
        limpio_tit = sanitizar_borrador(texto="", titulo=borrador.titulo)
        borrador.titulo = limpio_tit["titulo_sanitizado"] or borrador.titulo
        borrador.bloques_texto = bloques_ext
        if recs and not borrador.recursos:
            borrador.recursos = recs
            borrador.ultimo_id_recurso = max(ultimo_id, _max_num_recurso(recs))
    return borrador.model_copy(deep=True)


class GestorSesiones:
    def __init__(self, ttl_minutos: int = 340) -> None:
        self.ttl = timedelta(minutes=ttl_minutos)
        self._sesiones: Dict[str, SesionChat] = {}

    @property
    def ttl_segundos(self) -> int:
        return int(self.ttl.total_seconds())

    @property
    def sesiones(self) -> Dict[str, SesionChat]:
        return self._sesiones

    def limpiar_expiradas(self, ahora: datetime) -> None:
        expiradas = [sid for sid, s in self._sesiones.items() if (ahora - s.updated_at) > self.ttl]
        for sid in expiradas:
            limpiar_archivos_temporales_sesion(sid)
            self._sesiones.pop(sid, None)

    def obtener_o_crear(self, session_id: Optional[str]) -> Tuple[SesionChat, bool, bool]:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)

        if session_id and session_id in self._sesiones:
            sesion = self._sesiones[session_id]
            sesion.updated_at = ahora
            return sesion, False, False

        fue_expirada = bool(session_id)
        sid = secrets.token_urlsafe(32)
        nueva = SesionChat(session_id=sid, updated_at=ahora)
        self._sesiones[sid] = nueva
        return nueva, True, fue_expirada

    def eliminar(self, session_id: str) -> None:
        limpiar_archivos_temporales_sesion(session_id)
        self._sesiones.pop(session_id, None)

    def obtener_sesion(self, session_id: Optional[str]) -> Optional[SesionChat]:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            return None
        sesion = self._sesiones[session_id]
        sesion.updated_at = ahora
        return sesion

    def obtener_borrador_conforme(self, session_id: Optional[str]) -> Optional[BorradorSesion]:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)

        if not session_id or session_id not in self._sesiones:
            return None

        sesion = self._sesiones[session_id]
        if (
            sesion.estado != EstadoFlujo.CONFORMIDAD_USUARIO
            or sesion.borrador is None
            or not sesion.borrador.conforme
        ):
            return None

        # Invariante: no se puede quedar en CONFORMIDAD_USUARIO con texto distinto al confirmado
        if (
            sesion.borrador.texto_original_conforme is not None
            and sesion.borrador.texto_alineado_discourse != sesion.borrador.texto_original_conforme
        ):
            sesion.borrador.conforme = False
            sesion.borrador.conforme_en = None
            sesion.estado = EstadoFlujo.REVISION_BORRADOR
            return None

        sesion.updated_at = ahora
        return _sanitizar_y_clonar_borrador(sesion.borrador, sesion)

    obtener_borrador_aprobado = obtener_borrador_conforme

    def obtener_borrador_sesion_validado(self, session_id: str) -> BorradorSesion:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)

        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")

        sesion = self._sesiones[session_id]
        # Invariante: no se puede quedar en CONFORMIDAD_USUARIO con texto distinto al confirmado
        if (
            sesion.borrador is not None
            and sesion.borrador.texto_original_conforme is not None
            and sesion.borrador.texto_alineado_discourse != sesion.borrador.texto_original_conforme
        ):
            sesion.borrador.conforme = False
            sesion.borrador.conforme_en = None
            sesion.estado = EstadoFlujo.REVISION_BORRADOR

        if (
            sesion.estado != EstadoFlujo.CONFORMIDAD_USUARIO
            or sesion.borrador is None
            or not sesion.borrador.conforme
        ):
            raise EstadoInvalidoError(f"El borrador no está en estado CONFORMIDAD_USUARIO (estado actual: '{sesion.estado.value}').")

        sesion.updated_at = ahora
        return _sanitizar_y_clonar_borrador(sesion.borrador, sesion)

    def actualizar_borrador_texto(self, session_id: str, nuevo_texto: str) -> bool:
        """Actualiza el texto del borrador (p. ej. cuando una skill devuelve resultado).
        Regla 6: cuando una skill devuelve texto, bloques_texto = [resultado].
        """
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)

        if not session_id or session_id not in self._sesiones:
            return False

        sesion = self._sesiones[session_id]
        if sesion.borrador is not None:
            if not sesion.borrador.texto_original_conforme:
                sesion.borrador.texto_original_conforme = sesion.borrador.texto_alineado_discourse
            texto_strip = (nuevo_texto or "").strip()
            if sesion.borrador.texto_limpio != texto_strip:
                sesion.borrador.conforme = False
                sesion.borrador.conforme_en = None
                sesion.borrador.conformidad_invalidada = True
                sesion.estado = EstadoFlujo.REVISION_BORRADOR
            sesion.borrador.bloques_texto = [texto_strip] if texto_strip else []
            sesion.bloques_texto = list(sesion.borrador.bloques_texto)
            sesion.texto_limpio = sesion.borrador.texto_limpio
            sesion.texto = sesion.borrador.texto_alineado_discourse
            sesion.updated_at = ahora
            return True
        return False

    def obtener_recursos_borrador(self, session_id: str) -> List[Recurso]:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")
        sesion = self._sesiones[session_id]
        sesion.updated_at = ahora
        recursos_dict = (sesion.borrador.recursos if sesion.borrador else sesion.recursos) or {}
        return sorted(recursos_dict.values(), key=lambda r: (r.posicion, r.orden))

    def _sincronizar_sesion_desde_borrador(self, sesion: SesionChat) -> List[Recurso]:
        b = sesion.borrador
        if b is None:
            items = sorted(sesion.recursos.values(), key=lambda r: (r.posicion, r.orden))
            for i, r in enumerate(items):
                r.orden = i
            sesion.recursos = {r.id: r for r in items}
            sesion.orden_multimedia = list(range(len(items)))
            sesion.posiciones = [r.posicion for r in items]
            return items

        sesion.bloques_texto = list(b.bloques_texto)
        sesion.texto_limpio = b.texto_limpio
        sesion.recursos = dict(b.recursos)
        sesion.ultimo_id_recurso = max(sesion.ultimo_id_recurso, b.ultimo_id_recurso)
        b.ultimo_id_recurso = sesion.ultimo_id_recurso
        sesion.orden_multimedia = list(b.orden_multimedia)
        sesion.posiciones = list(b.posiciones)
        sesion.texto = b.texto_alineado_discourse
        if b.conformidad_invalidada and sesion.estado == EstadoFlujo.CONFORMIDAD_USUARIO:
            sesion.estado = EstadoFlujo.REVISION_BORRADOR
        return b.multimedia

    def _aplicar_cambio_multimedia(self, sesion: SesionChat, items_ordenados: List[Recurso]) -> List[Recurso]:
        """Persiste un nuevo estado de la lista multimedia en sesión y borrador."""
        b = sesion.borrador
        if b:
            b._sincronizar_orden_recursos(items_ordenados, invalidar_conformidad=True)
            return self._sincronizar_sesion_desde_borrador(sesion)

        recs_norm = _normalizar_invariantes_recursos(
            {r.id: r for r in items_ordenados},
            len(sesion.bloques_texto) if sesion.bloques_texto else None,
        )
        max_id = max(sesion.ultimo_id_recurso, _max_num_recurso(recs_norm))
        sesion.recursos = recs_norm
        sesion.ultimo_id_recurso = max_id
        sesion.orden_multimedia = list(range(len(recs_norm)))
        sesion.posiciones = [r.posicion for r in recs_norm.values()]
        return list(recs_norm.values())

    def _obtener_sesion_activa(self, session_id: str) -> SesionChat:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")
        sesion = self._sesiones[session_id]
        sesion.updated_at = ahora
        return sesion

    @staticmethod
    def _recursos_actuales(sesion: SesionChat) -> Dict[str, Recurso]:
        return (sesion.borrador.recursos if sesion.borrador else sesion.recursos) or {}

    def eliminar_recurso_multimedia(
        self, session_id: str, recurso_id_or_index: Union[str, int]
    ) -> bool:
        """Elimina un recurso por ID o por índice y aplica la fusión condicional de bloques."""
        sesion = self._obtener_sesion_activa(session_id)
        recursos = dict(self._recursos_actuales(sesion))

        if isinstance(recurso_id_or_index, int) or (
            isinstance(recurso_id_or_index, str)
            and recurso_id_or_index.isdigit()
            and recurso_id_or_index not in recursos
        ):
            idx = int(recurso_id_or_index)
            items_ord = sorted(recursos.values(), key=lambda r: (r.posicion, r.orden))
            if not (0 <= idx < len(items_ord)):
                return False
            recurso_id = items_ord[idx].id
        else:
            recurso_id = str(recurso_id_or_index)

        if recurso_id not in recursos:
            return False

        # Conservar el máximo ID histórico antes de eliminar (contador monotónico)
        max_antes = max(
            sesion.ultimo_id_recurso,
            sesion.borrador.ultimo_id_recurso if sesion.borrador else 0,
            _max_num_recurso(recursos),
        )
        sesion.ultimo_id_recurso = max_antes
        if sesion.borrador:
            sesion.borrador.ultimo_id_recurso = max_antes

        # Limpiar archivo temporal físico si corresponde
        servicio_eliminar_recurso(dict(recursos), recurso_id)

        if sesion.borrador is not None:
            eliminado = sesion.borrador.eliminar_multimedia(recurso_id)
            if eliminado is None:
                return False
            self._sincronizar_sesion_desde_borrador(sesion)
            return True

        recursos.pop(recurso_id, None)
        self._aplicar_cambio_multimedia(sesion, sorted(recursos.values(), key=lambda r: (r.posicion, r.orden)))
        return True

    eliminar_recurso_borrador = eliminar_recurso_multimedia

    def agregar_recurso_multimedia(
        self,
        session_id: str,
        recurso: Recurso,
        posicion: Optional[int] = None,
        orden: Optional[int] = None,
    ) -> Recurso:
        """Agrega o inserta un recurso en cualquier flujo respetando (posicion, orden)."""
        sesion = self._obtener_sesion_activa(session_id)
        if sesion.borrador is not None:
            rec_agregado = sesion.borrador.agregar_multimedia(
                recurso, posicion=posicion, orden=orden
            )
            self._sincronizar_sesion_desde_borrador(sesion)
            return rec_agregado

        items = sorted(
            (r for r in self._recursos_actuales(sesion).values() if r.id != recurso.id),
            key=lambda r: (r.posicion, r.orden),
        )
        if posicion is not None:
            recurso.posicion = max(-1, posicion)
        items.append(recurso)
        self._aplicar_cambio_multimedia(sesion, items)
        return sesion.recursos[recurso.id]

    def agregar_recurso_subido(
        self,
        session_id: str,
        recurso: Recurso,
        posicion: Optional[int] = None,
        orden: Optional[int] = None,
    ) -> Recurso:
        return self.agregar_recurso_multimedia(session_id, recurso, posicion=posicion, orden=orden)

    def reordenar_multimedia(
        self,
        session_id: str,
        from_index: Optional[int] = None,
        to_index: Optional[int] = None,
        nuevo_orden: Optional[Union[List[int], List[str]]] = None,
        recurso_id: Optional[str] = None,
        posicion: Optional[int] = None,
        orden: Optional[int] = None,
    ) -> List[Recurso]:
        """Reordena recursos manteniendo los invariantes de (posicion, orden)."""
        sesion = self._obtener_sesion_activa(session_id)
        items = sorted(self._recursos_actuales(sesion).values(), key=lambda r: (r.posicion, r.orden))
        if not items and not sesion.borrador:
            raise EstadoInvalidoError("No existen contenidos multimedia para reordenar en la sesión.")

        if sesion.borrador is not None:
            if recurso_id is not None:
                sesion.borrador.reordenar_recurso(
                    recurso_id,
                    nueva_posicion=posicion,
                    nuevo_orden=orden if orden is not None else to_index,
                )
            elif from_index is not None and (posicion is not None or orden is not None):
                sesion.borrador.reordenar_recurso(
                    from_index,
                    nueva_posicion=posicion,
                    nuevo_orden=orden if orden is not None else to_index,
                )
            elif from_index is not None and to_index is not None:
                sesion.borrador.reorder(from_index, to_index, nueva_posicion=posicion)
            elif nuevo_orden is not None:
                if nuevo_orden and isinstance(nuevo_orden[0], int):
                    sesion.borrador.reordenar_por_indices(nuevo_orden)  # type: ignore[arg-type]
                else:
                    sesion.borrador.reordenar_por_ids(nuevo_orden)  # type: ignore[arg-type]
            else:
                raise EstadoInvalidoError(
                    "Debe proveer recurso_id/from_index con posicion/orden/to_index, o un vector nuevo_orden."
                )
            return self._sincronizar_sesion_desde_borrador(sesion)

        if from_index is not None and to_index is not None:
            if not (0 <= from_index < len(items) and 0 <= to_index < len(items)):
                raise ValueError(
                    f"Índices de reordenamiento fuera de rango: from_index={from_index}, "
                    f"to_index={to_index} (total: {len(items)})"
                )
            posiciones_slots = [r.posicion for r in items]
            it = items.pop(from_index)
            items.insert(to_index, it)
            for i, r in enumerate(items):
                r.posicion = posiciones_slots[i] if posicion is None else posicion
        elif nuevo_orden is not None:
            posiciones_slots = [r.posicion for r in items]
            if nuevo_orden and isinstance(nuevo_orden[0], int):
                elegidos = []
                vistos = set()
                for idx in nuevo_orden:  # type: ignore[assignment]
                    if 0 <= idx < len(items) and idx not in vistos:
                        elegidos.append(items[idx])
                        vistos.add(idx)
            else:
                imap = {r.id: r for r in items}
                elegidos = [imap.pop(rid) for rid in nuevo_orden if rid in imap]  # type: ignore[misc]
            ids_elegidos = {r.id for r in elegidos}
            items = elegidos + [r for r in items if r.id not in ids_elegidos]
            for i, r in enumerate(items):
                r.posicion = posiciones_slots[i]
        else:
            raise EstadoInvalidoError("Debe proveer from_index y to_index, o un vector nuevo_orden de IDs o índices.")

        return self._aplicar_cambio_multimedia(sesion, items)

    def agregar_contenido_adicional(
        self, session_id: str, contenido: str, tipo: str = "texto"
    ) -> ItemContenidoAdicional:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")
        sesion = self._sesiones[session_id]
        sesion.updated_at = ahora

        if not sesion.borrador:
            raise EstadoInvalidoError("No existe un borrador activo en la sesión para agregar contenido.")

        if (
            sesion.borrador.modo not in ("enriquecimiento", "actualizar")
            and sesion.borrador.articulo_original_id is None
        ):
            raise EstadoInvalidoError(
                "El contenido adicional solo está permitido en flujos de actualizar o enriquecer un artículo existente."
            )

        contenido_sanitizado = sanitizar_borrador(texto=contenido).get("texto_sanitizado", contenido)
        items = sesion.borrador.contenido_adicional
        item_id = f"ca_{secrets.token_hex(4)}"
        nuevo_item = ItemContenidoAdicional(
            id=item_id,
            tipo=tipo,
            contenido=contenido_sanitizado,
            posicion=len(items),
        )
        items.append(nuevo_item)
        sesion.contenido_adicional = list(items)

        # Si el borrador ya tenía conformidad, cualquier agregado la invalida
        if sesion.borrador.conforme:
            sesion.borrador.conforme = False
            sesion.borrador.conforme_en = None
            sesion.borrador.conformidad_invalidada = True
            if sesion.estado == EstadoFlujo.CONFORMIDAD_USUARIO:
                sesion.estado = EstadoFlujo.REVISION_BORRADOR

        # Invariante innegociable: texto_limpio y recursos NO cambian
        return nuevo_item

    def eliminar_item_contenido_adicional(self, session_id: str, item_id: str) -> bool:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")
        sesion = self._sesiones[session_id]
        sesion.updated_at = ahora

        if not sesion.borrador:
            raise EstadoInvalidoError("No existe un borrador activo en la sesión.")

        items = sesion.borrador.contenido_adicional
        original_len = len(items)
        items_filtrados = [it for it in items if it.id != item_id]
        if len(items_filtrados) == original_len:
            return False

        # Re-indexar posiciones
        for i, it in enumerate(items_filtrados):
            it.posicion = i

        sesion.borrador.contenido_adicional = items_filtrados
        sesion.contenido_adicional = list(items_filtrados)

        # Si el borrador ya tenía conformidad, se invalida
        if sesion.borrador.conforme:
            sesion.borrador.conforme = False
            sesion.borrador.conforme_en = None
            sesion.borrador.conformidad_invalidada = True
            if sesion.estado == EstadoFlujo.CONFORMIDAD_USUARIO:
                sesion.estado = EstadoFlujo.REVISION_BORRADOR

        return True

    def reordenar_contenido_adicional(
        self, session_id: str, orden_ids: List[str]
    ) -> List[ItemContenidoAdicional]:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")
        sesion = self._sesiones[session_id]
        sesion.updated_at = ahora

        if not sesion.borrador:
            raise EstadoInvalidoError("No existe un borrador activo en la sesión.")

        items_map = {it.id: it for it in sesion.borrador.contenido_adicional}
        nuevos_items: List[ItemContenidoAdicional] = []
        for id_item in orden_ids:
            if id_item in items_map:
                nuevos_items.append(items_map.pop(id_item))
        # Conservar al final cualquier ítem que no haya sido listado explícitamente
        for sobrante in items_map.values():
            nuevos_items.append(sobrante)

        for i, it in enumerate(nuevos_items):
            it.posicion = i

        sesion.borrador.contenido_adicional = nuevos_items
        sesion.contenido_adicional = list(nuevos_items)

        # Si el borrador ya tenía conformidad, se invalida
        if sesion.borrador.conforme:
            sesion.borrador.conforme = False
            sesion.borrador.conforme_en = None
            sesion.borrador.conformidad_invalidada = True
            if sesion.estado == EstadoFlujo.CONFORMIDAD_USUARIO:
                sesion.estado = EstadoFlujo.REVISION_BORRADOR

        return nuevos_items

    def obtener_contenido_adicional(self, session_id: str) -> List[ItemContenidoAdicional]:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")
        sesion = self._sesiones[session_id]
        sesion.updated_at = ahora
        items = (sesion.borrador.contenido_adicional if sesion.borrador else sesion.contenido_adicional) or []
        return sorted(items, key=lambda x: x.posicion)

    def modificar_item_contenido_adicional(
        self, session_id: str, item_id: str, nuevo_contenido: str, nuevo_tipo: Optional[str] = None
    ) -> ItemContenidoAdicional:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")
        sesion = self._sesiones[session_id]
        sesion.updated_at = ahora

        if not sesion.borrador:
            raise EstadoInvalidoError("No existe un borrador activo en la sesión.")

        item = next((it for it in sesion.borrador.contenido_adicional if it.id == item_id), None)
        if not item:
            raise EstadoInvalidoError(f"No se encontró el ítem '{item_id}' en el contenido adicional.")

        item.contenido = sanitizar_borrador(texto=nuevo_contenido).get("texto_sanitizado", nuevo_contenido)
        if nuevo_tipo is not None:
            item.tipo = nuevo_tipo

        sesion.contenido_adicional = list(sesion.borrador.contenido_adicional)

        # Invalida conformidad si ya estaba dada
        if sesion.borrador.conforme:
            sesion.borrador.conforme = False
            sesion.borrador.conforme_en = None
            sesion.borrador.conformidad_invalidada = True
            if sesion.estado == EstadoFlujo.CONFORMIDAD_USUARIO:
                sesion.estado = EstadoFlujo.REVISION_BORRADOR

        return item

    def descartar_borrador(self, session_id: str) -> None:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)
        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")
        sesion = self._sesiones[session_id]
        sesion.borrador = None
        sesion.contenido_adicional = []
        sesion.updated_at = ahora


gestor_sesiones = GestorSesiones()
SESIONES = gestor_sesiones.sesiones
TTL_SESION = gestor_sesiones.ttl
TTL_SEGUNDOS = gestor_sesiones.ttl_segundos
obtener_borrador_conforme = gestor_sesiones.obtener_borrador_conforme
obtener_borrador_aprobado = gestor_sesiones.obtener_borrador_aprobado
obtener_borrador_sesion_validado = gestor_sesiones.obtener_borrador_sesion_validado
actualizar_borrador_texto = gestor_sesiones.actualizar_borrador_texto
obtener_recursos_borrador = gestor_sesiones.obtener_recursos_borrador
eliminar_recurso_borrador = gestor_sesiones.eliminar_recurso_borrador
eliminar_recurso_multimedia = gestor_sesiones.eliminar_recurso_multimedia
reordenar_multimedia = gestor_sesiones.reordenar_multimedia
agregar_recurso_multimedia = gestor_sesiones.agregar_recurso_multimedia
agregar_contenido_adicional = gestor_sesiones.agregar_contenido_adicional
eliminar_item_contenido_adicional = gestor_sesiones.eliminar_item_contenido_adicional
reordenar_contenido_adicional = gestor_sesiones.reordenar_contenido_adicional
modificar_item_contenido_adicional = gestor_sesiones.modificar_item_contenido_adicional
obtener_contenido_adicional = gestor_sesiones.obtener_contenido_adicional
descartar_borrador = gestor_sesiones.descartar_borrador
