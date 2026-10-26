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
    eliminar_marcador_recurso_de_texto,
    eliminar_recurso_borrador as servicio_eliminar_recurso,
    componer_texto_publicable,
    extraer_recursos_y_texto_limpio,
    fusionar_texto_y_recursos_sin_colision,
    limpiar_archivos_temporales_sesion,
    permutar_marcadores_en_texto,
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
        """Sincroniza atómicamente el contenido textual, recursos y metadatos entre la sesión y su borrador."""
        if titulo is not None:
            self.titulo = titulo.strip()
            if self.borrador is not None:
                self.borrador.titulo = self.titulo

        if recursos is not None:
            self.recursos = recursos
            max_rec = _max_num_recurso(recursos)
            self.ultimo_id_recurso = max(self.ultimo_id_recurso, max_rec, ultimo_id_recurso or 0)
            self.orden_multimedia = list(range(len(recursos)))
            self.posiciones = list(range(len(recursos)))
            if self.borrador is not None:
                self.borrador.recursos = self.recursos
                self.borrador.ultimo_id_recurso = self.ultimo_id_recurso
        elif ultimo_id_recurso is not None:
            self.ultimo_id_recurso = max(self.ultimo_id_recurso, ultimo_id_recurso)
            if self.borrador is not None:
                self.borrador.ultimo_id_recurso = self.ultimo_id_recurso

        if texto_limpio is not None:
            self.texto_limpio = texto_limpio
            if self.borrador is not None:
                self.borrador.texto_limpio = texto_limpio

        if texto_base_limpio is not None:
            if self.borrador is not None:
                self.borrador.texto_base_limpio = texto_base_limpio

        if texto_en_edicion is not None:
            self.texto_en_edicion = texto_en_edicion
            if self.borrador is not None:
                self.borrador.texto_en_edicion = texto_en_edicion

        if texto is not None:
            self.texto = texto
        elif texto_limpio is not None:
            self.texto = componer_texto_publicable(self.texto_limpio, self.recursos)

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
    if borrador.texto_limpio:
        tl, recs_extra = extraer_recursos_y_texto_limpio(
            borrador.texto_limpio,
            recursos_previos=borrador.recursos,
            ultimo_id=ultimo_id,
        )
        if recs_extra:
            tl, recs_merged = fusionar_texto_y_recursos_sin_colision(
                tl, borrador.recursos, recs_extra, ultimo_id=ultimo_id
            )
            borrador.recursos = recs_merged
            borrador.ultimo_id_recurso = max(ultimo_id, _max_num_recurso(recs_merged))
            if sesion:
                sesion.recursos = dict(recs_merged)
                sesion.ultimo_id_recurso = max(sesion.ultimo_id_recurso, borrador.ultimo_id_recurso)
        if borrador.modo == "enriquecimiento" and borrador.texto_base_limpio:
            base_limpio = borrador.texto_base_limpio.strip()
            if base_limpio and base_limpio not in tl:
                tl = f"{base_limpio}\n\n{tl.strip()}" if tl.strip() else base_limpio
        limpio_tl = sanitizar_borrador(texto=tl, titulo=borrador.titulo)
        borrador.titulo = limpio_tl["titulo_sanitizado"]
        borrador.texto_limpio = limpio_tl["texto_sanitizado"]
    else:
        tl, recs = extraer_recursos_y_texto_limpio(
            borrador.texto,
            recursos_previos=borrador.recursos,
            ultimo_id=ultimo_id,
        )
        limpio_tl = sanitizar_borrador(texto=tl, titulo=borrador.titulo)
        borrador.titulo = limpio_tl["titulo_sanitizado"]
        borrador.texto_limpio = limpio_tl["texto_sanitizado"]
        if recs and not borrador.recursos:
            borrador.recursos = recs
            borrador.ultimo_id_recurso = max(ultimo_id, _max_num_recurso(recs))
    return borrador.model_copy(deep=True)


class GestorSesiones:
    def __init__(self, ttl_minutos: int = 30) -> None:
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
            and sesion.borrador.texto != sesion.borrador.texto_original_conforme
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
            and sesion.borrador.texto != sesion.borrador.texto_original_conforme
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
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)

        if not session_id or session_id not in self._sesiones:
            return False

        sesion = self._sesiones[session_id]
        if sesion.borrador is not None:
            if not sesion.borrador.texto_original_conforme:
                sesion.borrador.texto_original_conforme = sesion.borrador.texto
            if sesion.borrador.texto_limpio != nuevo_texto:
                sesion.borrador.conforme = False
                sesion.borrador.conforme_en = None
                sesion.borrador.conformidad_invalidada = True
                sesion.estado = EstadoFlujo.REVISION_BORRADOR
            sesion.borrador.texto_limpio = nuevo_texto
            sesion.texto = sesion.borrador.texto
            sesion.texto_limpio = nuevo_texto
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
        return sorted(recursos_dict.values(), key=lambda r: r.orden)

    def _aplicar_cambio_multimedia(self, sesion: SesionChat, items_ordenados: List[Recurso]) -> List[Recurso]:
        """Persiste un nuevo estado de la lista multimedia en sesión y borrador."""
        for i, r in enumerate(items_ordenados):
            r.orden = i
        recs_dict = {r.id: r for r in items_ordenados}
        vec_orden = list(range(len(items_ordenados)))
        max_id = max(sesion.ultimo_id_recurso, _max_num_recurso(recs_dict))

        sesion.recursos = recs_dict
        sesion.ultimo_id_recurso = max_id
        sesion.orden_multimedia = list(vec_orden)
        sesion.posiciones = list(vec_orden)

        b = sesion.borrador
        if b:
            b.recursos = recs_dict
            b.ultimo_id_recurso = max(b.ultimo_id_recurso, max_id)
            b.orden_multimedia = list(vec_orden)
            b.posiciones = list(vec_orden)
            sesion.texto = b.texto
            # texto_original_conforme NO se actualiza: el cambio debe quedar visible como modificación
            if b.conforme:
                b.conforme = False
                b.conforme_en = None
                b.conformidad_invalidada = True
                if sesion.estado == EstadoFlujo.CONFORMIDAD_USUARIO:
                    sesion.estado = EstadoFlujo.REVISION_BORRADOR
        return items_ordenados

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
        """Elimina un recurso por ID o por índice y remueve su marcador en texto_limpio."""
        sesion = self._obtener_sesion_activa(session_id)
        recursos = dict(self._recursos_actuales(sesion))

        if isinstance(recurso_id_or_index, int) or (
            isinstance(recurso_id_or_index, str)
            and recurso_id_or_index.isdigit()
            and recurso_id_or_index not in recursos
        ):
            idx = int(recurso_id_or_index)
            items_ord = sorted(recursos.values(), key=lambda r: r.orden)
            if not (0 <= idx < len(items_ord)):
                return False
            recurso_id = items_ord[idx].id
        else:
            recurso_id = str(recurso_id_or_index)

        # Conservar el máximo ID histórico antes de eliminar (contador monotónico)
        max_antes = max(
            sesion.ultimo_id_recurso,
            sesion.borrador.ultimo_id_recurso if sesion.borrador else 0,
            _max_num_recurso(recursos),
        )
        sesion.ultimo_id_recurso = max_antes
        if sesion.borrador:
            sesion.borrador.ultimo_id_recurso = max_antes

        nuevos_recursos, eliminado = servicio_eliminar_recurso(recursos, recurso_id)
        if not eliminado:
            return False

        if sesion.texto_limpio:
            sesion.texto_limpio = eliminar_marcador_recurso_de_texto(sesion.texto_limpio, recurso_id)
        if sesion.texto_en_edicion:
            sesion.texto_en_edicion = eliminar_marcador_recurso_de_texto(sesion.texto_en_edicion, recurso_id)
        if sesion.borrador:
            if sesion.borrador.texto_limpio:
                sesion.borrador.texto_limpio = eliminar_marcador_recurso_de_texto(
                    sesion.borrador.texto_limpio, recurso_id
                )
            if sesion.borrador.texto_en_edicion:
                sesion.borrador.texto_en_edicion = eliminar_marcador_recurso_de_texto(
                    sesion.borrador.texto_en_edicion, recurso_id
                )

        self._aplicar_cambio_multimedia(sesion, sorted(nuevos_recursos.values(), key=lambda r: r.orden))
        return True

    eliminar_recurso_borrador = eliminar_recurso_multimedia

    def agregar_recurso_multimedia(
        self, session_id: str, recurso: Recurso, posicion: Optional[int] = None
    ) -> Recurso:
        """Agrega o inserta un recurso en cualquier flujo. No toca texto_limpio."""
        sesion = self._obtener_sesion_activa(session_id)
        items = sorted(
            (r for r in self._recursos_actuales(sesion).values() if r.id != recurso.id),
            key=lambda r: r.orden,
        )
        if posicion is None or posicion < 0 or posicion >= len(items):
            items.append(recurso)
        else:
            items.insert(posicion, recurso)
        self._aplicar_cambio_multimedia(sesion, items)
        return recurso

    def agregar_recurso_subido(self, session_id: str, recurso: Recurso, posicion: Optional[int] = None) -> Recurso:
        return self.agregar_recurso_multimedia(session_id, recurso, posicion)

    def reordenar_multimedia(
        self,
        session_id: str,
        from_index: Optional[int] = None,
        to_index: Optional[int] = None,
        nuevo_orden: Optional[Union[List[int], List[str]]] = None,
    ) -> List[Recurso]:
        """Reordena recursos y permuta qué recurso ocupa cada slot de marcador en texto_limpio."""
        sesion = self._obtener_sesion_activa(session_id)
        items = sorted(self._recursos_actuales(sesion).values(), key=lambda r: r.orden)
        if not items and not sesion.borrador:
            raise EstadoInvalidoError("No existen contenidos multimedia para reordenar en la sesión.")

        ids_antes = [r.id for r in items]

        if from_index is not None and to_index is not None:
            if not (0 <= from_index < len(items) and 0 <= to_index < len(items)):
                raise ValueError(
                    f"Índices de reordenamiento fuera de rango: from_index={from_index}, "
                    f"to_index={to_index} (total: {len(items)})"
                )
            it = items.pop(from_index)
            items.insert(to_index, it)
        elif nuevo_orden is not None:
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
        else:
            raise EstadoInvalidoError("Debe proveer from_index y to_index, o un vector nuevo_orden de IDs o índices.")

        ids_despues = [r.id for r in items]
        if ids_antes != ids_despues:
            if sesion.texto_limpio:
                sesion.texto_limpio = permutar_marcadores_en_texto(
                    sesion.texto_limpio, ids_antes, ids_despues
                )
            if sesion.borrador and sesion.borrador.texto_limpio:
                sesion.borrador.texto_limpio = permutar_marcadores_en_texto(
                    sesion.borrador.texto_limpio, ids_antes, ids_despues
                )

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
