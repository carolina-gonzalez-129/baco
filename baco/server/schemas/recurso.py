from pathlib import PurePosixPath
import re
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator

from baco.server.config_limites import (
    MAX_BLOQUES_TEXTO,
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


def sanitizar_url_recurso(
    url: str,
    session_id: Optional[str] = None,
    recursos_actuales: Optional[Dict[str, Any]] = None,
) -> str:
    """Sanitiza una URL externa http(s) eliminando credenciales embebidas, fragmento
    y parámetros sensibles de la query. Solo permite esquemas http:// y https://.
    """
    if not url or not isinstance(url, str):
        raise ValueError("La URL del recurso no puede estar vacía.")
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("La URL contiene caracteres de control no permitidos.")
    u = url.strip()
    if not u:
        raise ValueError("La URL del recurso no puede estar vacía.")

    if "\\" in u:
        raise ValueError("La URL no puede contener backslashes.")

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
    referencia: str = Field(default="", description="URL externa del recurso o URL lógica de previsualización (/api/recursos-temp/{session_id}/{archivo})")
    posicion: int = Field(default=0, description="Índice del bloque de texto tras el cual se ubica (-1 si va antes del primer bloque)")
    orden: int = Field(default=0, description="Posición ordinal global única y contigua 0..N-1")
    archivo_disco: Optional[str] = Field(
        default=None,
        exclude=True,
        description="Nombre de archivo guardado en almacenamiento temporal de la sesión (excluido de la serialización hacia el front y respuestas API).",
    )

    @model_validator(mode="after")
    def sincronizar_archivo_disco(self) -> "Recurso":
        if self.origen == "subido" and not self.archivo_disco and self.referencia.startswith("/api/recursos-temp/"):
            self.archivo_disco = self.referencia.rsplit("/", 1)[-1]
        return self


class RecursoBloqueInput(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")

    id: Optional[str] = Field(default=None, max_length=100, description="ID del recurso subido en la sesión.")
    url: Optional[str] = Field(default=None, max_length=2048, description="URL o enlace del recurso externo.")
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
        if self.id and str(self.id).strip():
            self.id = str(self.id).strip()
            # El servidor ignora cualquier URL enviada por el cliente para recursos con id (subidos)
            self.url = None
            return self

        if not self.url or not str(self.url).strip():
            raise ValueError("Un bloque de recurso debe incluir 'id' (si es subido) o 'url' http(s) (si es externo).")
        self.url = sanitizar_url_recurso(str(self.url).strip())
        return self


class BloqueItem(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")

    tipo: Literal["texto", "recurso"]
    contenido: Optional[str] = Field(default=None, description="Texto si tipo=='texto', o ID/URL si tipo=='recurso'.")
    recurso: Optional[RecursoBloqueInput] = Field(default=None, description="Objeto de recurso si tipo=='recurso'.")

    @model_validator(mode="after")
    def validar_cruzado(self) -> "BloqueItem":
        if self.tipo == "texto":
            if self.contenido is None:
                self.contenido = ""
            if self.recurso is not None:
                raise ValueError("Un bloque de tipo 'texto' no debe incluir el campo 'recurso'.")
            if re.search(r"\[\[(?:recurso:[a-zA-Z0-9_\-]+|R\d+)\]\]", self.contenido):
                raise ValueError("El bloque de texto no puede contener marcadores reservados del sistema como [[recurso:rec_1]].")
        elif self.tipo == "recurso":
            if self.recurso is None and not self.contenido:
                raise ValueError("Un bloque de tipo 'recurso' debe incluir 'recurso' o una URL/ID en 'contenido'.")
            if self.recurso is None and self.contenido:
                c_str = self.contenido.strip()
                if c_str.startswith("http://") or c_str.startswith("https://"):
                    self.recurso = RecursoBloqueInput(url=c_str)
                else:
                    self.recurso = RecursoBloqueInput(id=c_str)
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
        recursos_vistos = set()
        total_recursos = 0
        total_bytes = 0
        total_bloques_texto = 0
        for b in self.bloques:
            if b.tipo == "texto":
                if (b.contenido or "").strip():
                    total_bloques_texto += 1
            elif b.tipo == "recurso" and b.recurso:
                clave = b.recurso.id or b.recurso.url
                if clave and clave not in recursos_vistos:
                    recursos_vistos.add(clave)
                    total_recursos += 1
                    if b.recurso.tamano_bytes:
                        total_bytes += b.recurso.tamano_bytes
        if total_bloques_texto > MAX_BLOQUES_TEXTO:
            raise ValueError(
                f"Se supera el límite máximo de {MAX_BLOQUES_TEXTO} bloques de texto permitidos por borrador."
            )
        if total_recursos > MAX_RECURSOS_POR_SESION:
            raise ValueError(
                f"Se supera el límite máximo de {MAX_RECURSOS_POR_SESION} recursos permitidos por borrador."
            )
        if total_bytes > MAX_RECURSOS_TOTAL_BYTES:
            raise ValueError(
                f"El tamaño total acumulado de recursos supera el límite de {MAX_RECURSOS_TOTAL_BYTES // (1024 * 1024)} MB."
            )
        return self
        return self


class ConfirmarBloquesResponse(BaseModel):
    session_id: str
    bloques_texto: List[str] = Field(default_factory=list)
    texto_limpio: str
    recursos: List[Recurso]
    aviso: Optional[str] = None
    borrador: Optional[Any] = None


class EstadoRecursosResponse(BaseModel):
    bloques_texto: List[str] = Field(default_factory=list)
    recursos: List[Recurso] = Field(default_factory=list)
    texto_limpio: str = ""
    multimedia_habilitada: bool = False
    skills_habilitadas: bool = True
    skills_motivo: Optional[str] = None
    estado: Optional[str] = None
    borrador: Optional[Any] = None


