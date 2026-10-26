import re
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator

from baco.server.config_limites import (
    MAX_RECURSOS_POR_SESION,
    MAX_RECURSOS_TOTAL_BYTES,
    RECURSO_MAX_BYTES,
)

TipoRecurso = Literal["imagen", "video", "audio", "documento", "otro"]
OrigenRecurso = Literal["existente", "subido"]

PARAMETROS_QUERY_SENSIBLES = frozenset({
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "auth",
    "authorization",
    "key",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "sig",
    "signature",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "password",
    "passwd",
    "pwd",
    "jwt",
    "session",
    "session_id",
    "credential",
    "credentials",
})

_RE_PARAM_SENSIBLE = re.compile(
    r"(?:token|secret|key|sig|auth|password|passwd|pwd|credential|session)",
    re.IGNORECASE,
)


def sanitizar_url_recurso(url: str) -> str:
    """Sanitiza una URL eliminando credenciales embebidas, fragmento y parámetros sensibles de la query."""
    if not url or not isinstance(url, str):
        raise ValueError("La URL del recurso no puede estar vacía.")
    u = url.strip()
    partes = urlsplit(u)
    if partes.scheme not in ("http", "https"):
        raise ValueError("La URL debe comenzar con http:// o https://.")
    hostname = partes.hostname
    if not hostname:
        raise ValueError("La URL debe incluir un nombre de host válido.")
    port_part = f":{partes.port}" if partes.port else ""
    netloc = f"{hostname}{port_part}"
    path = partes.path or "/"

    # Bloqueo estricto de SVG sobre el path sin query
    if path.lower().endswith(".svg") or ".svg" in path.lower():
        raise ValueError("No se permiten archivos SVG por razones de seguridad.")

    query_limpia = ""
    if partes.query:
        pares = parse_qsl(partes.query, keep_blank_values=True)
        pares_filtrados = [
            (k, v)
            for k, v in pares
            if k.strip().lower() not in PARAMETROS_QUERY_SENSIBLES
            and not _RE_PARAM_SENSIBLE.search(k.strip())
        ]
        query_limpia = urlencode(pares_filtrados, doseq=True)

    return urlunsplit((partes.scheme, netloc, path, query_limpia, ""))


class Recurso(BaseModel):
    id: str = Field(..., description="Identificador único del recurso (ej: 'rec_1', 'rec_2')")
    tipo: TipoRecurso = Field(..., description="Tipo de recurso multimedia (imagen, video, audio, documento, otro)")
    nombre: str = Field(..., description="Nombre descriptivo o nombre del archivo")
    origen: OrigenRecurso = Field(default="existente", description="Origen del recurso: 'existente' (Discourse/externo) o 'subido' (temporal de sesión)")
    tamano_bytes: Optional[int] = Field(default=None, description="Tamaño del archivo en bytes si está disponible")
    mime_type: Optional[str] = Field(default=None, description="Tipo MIME verificado del recurso")
    referencia: str = Field(default="", description="URL original del recurso o ruta temporal en disco de la sesión")
    orden: int = Field(default=0, description="Posición ordinal de aparición en el texto")


class RecursoBloqueInput(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")

    url: str = Field(..., min_length=1, max_length=2048, description="URL o enlace del recurso.")
    nombre: Optional[str] = Field(default=None, max_length=255, description="Nombre descriptivo.")
    tipo: Optional[TipoRecurso] = Field(default=None, description="Tipo sugerido de recurso.")
    mime_type: Optional[str] = Field(default=None, max_length=100, description="Tipo MIME del recurso.")
    tamano_bytes: Optional[int] = Field(default=None, ge=0, description="Tamaño en bytes.")

    @model_validator(mode="after")
    def validar_recurso(self) -> "RecursoBloqueInput":
        if self.mime_type and "svg" in self.mime_type.lower():
            raise ValueError("No se permiten archivos SVG por razones de seguridad.")
        if self.tamano_bytes is not None and self.tamano_bytes > RECURSO_MAX_BYTES:
            raise ValueError(
                f"El recurso supera el tamaño máximo permitido de {RECURSO_MAX_BYTES // (1024 * 1024)} MB."
            )
        # Sanitizar y validar URL
        self.url = sanitizar_url_recurso(self.url)
        return self


class BloqueItem(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")

    tipo: Literal["texto", "recurso"]
    contenido: Optional[str] = Field(default=None, description="Texto si tipo=='texto', o URL si tipo=='recurso'.")
    recurso: Optional[RecursoBloqueInput] = Field(default=None, description="Objeto de recurso si tipo=='recurso'.")

    @model_validator(mode="after")
    def validar_cruzado(self) -> "BloqueItem":
        if self.tipo == "texto":
            if not self.contenido or not self.contenido.strip():
                raise ValueError("Un bloque de tipo 'texto' debe incluir 'contenido' con texto no vacío.")
            if self.recurso is not None:
                raise ValueError("Un bloque de tipo 'texto' no debe incluir el campo 'recurso'.")
            if re.search(r"\[\[(?:recurso:[a-zA-Z0-9_\-]+|R\d+)\]\]", self.contenido):
                raise ValueError("El bloque de texto no puede contener marcadores reservados del sistema como [[recurso:rec_1]].")
        elif self.tipo == "recurso":
            if self.recurso is None and not self.contenido:
                raise ValueError("Un bloque de tipo 'recurso' debe incluir 'recurso' o una URL en 'contenido'.")
            if self.recurso is None and self.contenido:
                self.recurso = RecursoBloqueInput(url=self.contenido.strip())
                self.contenido = None
            elif self.recurso is not None and self.contenido:
                # Si vienen ambos, verificar coherencia o limpiar contenido
                self.contenido = None
        return self


class ConfirmarBloquesRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")

    session_id: Optional[str] = Field(default=None, description="ID de sesión.")
    bloques: List[BloqueItem] = Field(..., min_length=1, description="Lista ordenada de bloques.")

    @model_validator(mode="after")
    def validar_recursos_unicos_y_limites(self) -> "ConfirmarBloquesRequest":
        urls_vistas = set()
        total_recursos = 0
        total_bytes = 0
        for b in self.bloques:
            if b.tipo == "recurso" and b.recurso:
                url_limpia = b.recurso.url
                if url_limpia not in urls_vistas:
                    urls_vistas.add(url_limpia)
                    total_recursos += 1
                    if b.recurso.tamano_bytes:
                        total_bytes += b.recurso.tamano_bytes
        if total_recursos > MAX_RECURSOS_POR_SESION:
            raise ValueError(
                f"Se supera el límite máximo de {MAX_RECURSOS_POR_SESION} recursos permitidos por borrador."
            )
        if total_bytes > MAX_RECURSOS_TOTAL_BYTES:
            raise ValueError(
                f"El tamaño total acumulado de recursos supera el límite de {MAX_RECURSOS_TOTAL_BYTES // (1024 * 1024)} MB."
            )
        return self


class ConfirmarBloquesResponse(BaseModel):
    session_id: str
    texto_limpio: str
    recursos: List[Recurso]
    aviso: Optional[str] = None
    borrador: Optional[Any] = None

