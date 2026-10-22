from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import secrets
from typing import Dict, List, Optional, Tuple

from baco.server.schemas.chat_orquestado import (
    BorradorSesion,
    CoincidenciaArticulo,
    EstadoFlujo,
)
from baco.server.schemas.validacion import ValidarFormatoResponse
from baco.server.services.orquestador.excepciones import (
    EstadoInvalidoError,
    SesionNoEncontradaError,
)
from baco.server.services.validar_articulo import sanitizar_borrador


@dataclass
class SesionChat:
    session_id: str
    estado: EstadoFlujo = EstadoFlujo.ESPERANDO_TITULO
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    titulo: str = ""
    texto: str = ""
    categoria_id: int = 1
    tags: List[str] = field(default_factory=list)
    coincidencias: List[CoincidenciaArticulo] = field(default_factory=list)
    borrador: Optional[BorradorSesion] = None
    validacion: Optional[ValidarFormatoResponse] = None
    intentos_correccion: int = 0
    intentos_fallidos_por_estado: Dict[str, int] = field(default_factory=dict)
    confirmando_rechazo: bool = False

    def registrar_fallo(self, estado_clave: Optional[str] = None) -> int:
        clave = estado_clave or self.estado.value
        actual = self.intentos_fallidos_por_estado.get(clave, 0)
        self.intentos_fallidos_por_estado[clave] = actual + 1
        return actual

    def limpiar_fallos(self, estado_clave: Optional[str] = None) -> None:
        clave = estado_clave or self.estado.value
        self.intentos_fallidos_por_estado.pop(clave, None)


def _sanitizar_y_clonar_borrador(borrador: BorradorSesion) -> BorradorSesion:
    limpio = sanitizar_borrador(texto=borrador.texto, titulo=borrador.titulo)
    borrador.titulo = limpio["titulo_sanitizado"]
    borrador.texto = limpio["texto_sanitizado"]
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
        self._sesiones.pop(session_id, None)

    def obtener_borrador_aprobado(self, session_id: Optional[str]) -> Optional[BorradorSesion]:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)

        if not session_id or session_id not in self._sesiones:
            return None

        sesion = self._sesiones[session_id]
        if sesion.estado != EstadoFlujo.APROBADO or sesion.borrador is None:
            return None

        sesion.updated_at = ahora
        return _sanitizar_y_clonar_borrador(sesion.borrador)

    def obtener_borrador_sesion_validado(self, session_id: str) -> BorradorSesion:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)

        if not session_id or session_id not in self._sesiones:
            raise SesionNoEncontradaError(f"No existe la sesión '{session_id}' o la sesión expiró.")

        sesion = self._sesiones[session_id]
        if sesion.estado != EstadoFlujo.APROBADO or sesion.borrador is None:
            raise EstadoInvalidoError(f"El borrador no está en estado APROBADO (estado actual: '{sesion.estado.value}').")

        sesion.updated_at = ahora
        return _sanitizar_y_clonar_borrador(sesion.borrador)

    def actualizar_borrador_texto(self, session_id: str, nuevo_texto: str) -> bool:
        ahora = datetime.now(timezone.utc)
        self.limpiar_expiradas(ahora)

        if not session_id or session_id not in self._sesiones:
            return False

        sesion = self._sesiones[session_id]
        if sesion.borrador is not None:
            if not sesion.borrador.texto_original_aprobado:
                sesion.borrador.texto_original_aprobado = sesion.borrador.texto
            sesion.borrador.texto = nuevo_texto
            sesion.texto = nuevo_texto
            sesion.updated_at = ahora
            return True
        return False


gestor_sesiones = GestorSesiones()
SESIONES = gestor_sesiones.sesiones
TTL_SESION = gestor_sesiones.ttl
TTL_SEGUNDOS = gestor_sesiones.ttl_segundos
obtener_borrador_aprobado = gestor_sesiones.obtener_borrador_aprobado
obtener_borrador_sesion_validado = gestor_sesiones.obtener_borrador_sesion_validado
actualizar_borrador_texto = gestor_sesiones.actualizar_borrador_texto
