from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit, urlunsplit
from typing import Dict, Iterable, List, Optional, Tuple, Union

from baco.server.config_limites import (
    MAX_RECURSOS_POR_SESION,
    MAX_RECURSOS_TOTAL_BYTES,
    PERMITIR_SUBIDA_RECURSOS,
    RECURSO_MAX_BYTES,
)
from baco.server.schemas.recurso import (
    BloqueItem,
    OrigenRecurso,
    Recurso,
    TipoRecurso,
    sanitizar_url_recurso,
)

logger = logging.getLogger(__name__)

DIR_TEMP_SESIONES = Path("data/temp_sesiones")

# Extensiones / URLs para clasificación de tipo (SVG estrictamente bloqueado por seguridad)
EXTS_IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
EXTS_VIDEO = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv"}
EXTS_AUDIO = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
EXTS_DOCUMENTO = {".pdf", ".doc", ".docx", ".odt", ".ppt", ".pptx", ".odp", ".xls", ".xlsx", ".csv", ".txt"}

MIMES_PERMITIDOS = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
    "video/mp4",
    "video/webm",
    "audio/mpeg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
    "text/plain",
    "text/csv",
}


class SubidaRecursosDeshabilitadaError(Exception):
    """Lanzada cuando se intenta subir un recurso y la bandera está desactivada."""
    pass


class RecursoInvalidoError(Exception):
    """Lanzada cuando un recurso no pasa las validaciones de tamaño, tipo o cantidad."""
    pass


class RecursoDuplicadoError(RecursoInvalidoError):
    """El recurso ya está en el borrador."""


def clasificar_tipo_recurso(
    url_o_path: str, nombre: str = "", mime: Optional[str] = None
) -> TipoRecurso:
    """Clasifica el recurso en imagen, video, audio, documento u otro."""
    u = (url_o_path or "").lower()
    n = (nombre or "").lower()
    m = (mime or "").lower()

    if m.startswith("image/") or any(u.endswith(ext) or n.endswith(ext) for ext in EXTS_IMAGEN):
        return "imagen"
    if m.startswith("video/") or any(u.endswith(ext) or n.endswith(ext) for ext in EXTS_VIDEO) or any(
        k in u for k in ("youtube.com", "youtu.be", "vimeo.com", "loom.com")
    ):
        return "video"
    if m.startswith("audio/") or any(u.endswith(ext) or n.endswith(ext) for ext in EXTS_AUDIO):
        return "audio"
    if (
        m.startswith("application/pdf")
        or "docs.google.com" in u
        or any(u.endswith(ext) or n.endswith(ext) for ext in EXTS_DOCUMENTO)
    ):
        return "documento"
    return "otro"


def detectar_mime_type_real(contenido_bytes: bytes, filename: str) -> str:
    """Detecta el tipo MIME real inspeccionando magic bytes o mimetypes."""
    if contenido_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contenido_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contenido_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if contenido_bytes.startswith(b"RIFF") and len(contenido_bytes) >= 12 and contenido_bytes[8:12] == b"WEBP":
        return "image/webp"
    if contenido_bytes.startswith(b"%PDF-"):
        return "application/pdf"
    if len(contenido_bytes) >= 8 and contenido_bytes[4:8] in (b"ftyp", b"moov"):
        return "video/mp4"
    if contenido_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if contenido_bytes.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        return "audio/mpeg"
    if contenido_bytes.startswith(b"PK\x03\x04"):
        # Podría ser DOCX/PPTX/XLSX/ZIP
        ext = Path(filename).suffix.lower()
        if ext == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if ext == ".pptx":
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        if ext == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    if contenido_bytes.startswith(b"<svg") or (b"<svg" in contenido_bytes[:200] and b"xmlns" in contenido_bytes[:300]):
        return "image/svg+xml"
    if contenido_bytes.startswith(b"MZ") or contenido_bytes.startswith(b"\x7fELF"):
        return "application/x-executable"

    ext = Path(filename).suffix.lower()
    # Si la extensión declara un formato binario específico pero no coincide con los magic bytes:
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".mp4", ".webm", ".docx", ".pptx", ".xlsx", ".zip"}:
        return "application/octet-stream"

    tipo_adivinado, _ = mimetypes.guess_type(filename)
    return tipo_adivinado or "application/octet-stream"


def sanitizar_nombre_archivo(filename: str) -> str:
    """Sanitiza el nombre de archivo eliminando path traversal y caracteres peligrosos."""
    nombre_base = Path(filename).name
    limpio = re.sub(r"[^\w\.\-]", "_", nombre_base)
    return limpio or "archivo_adjunto"


def _extraer_attr_html(tag_html: str, attr: str) -> str:
    m = re.search(rf'\b{attr}\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>]+))', tag_html, flags=re.IGNORECASE)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3) or "").strip()


def _max_num_recurso(recursos: Optional[Dict[str, Recurso]], ultimo_id: int = 0) -> int:
    max_num = max(0, int(ultimo_id or 0))
    for rid in (recursos or {}):
        m = re.fullmatch(r"rec_(\d+)", str(rid))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num


def extraer_recursos_y_texto_limpio(
    texto: str,
    recursos_previos: Optional[Dict[str, Recurso]] = None,
    ultimo_id: int = 0,
) -> Tuple[str, Dict[str, Recurso]]:
    """Separa el contenido recibido en:

    1. texto_limpio: texto donde cada referencia multimedia válida se reemplaza por
       su marcador canónico [[recurso:rec_N]], y las referencias no válidas (rutas relativas,
       data: URIs o tags locales no registrables) se sanitizan por completo para que nunca
       lleguen crudas al agente.
    2. recursos: diccionario de {id: Recurso}, con `orden` 0-based según su aparición.

    Detecta imágenes Markdown (absolutas, relativas, data URIs), etiquetas HTML (<img>,
    <video>, <audio>, <iframe>), adjuntos ([|attachment]()) y URLs sueltas.
    """
    if not texto:
        return "", {}

    recursos: Dict[str, Recurso] = {}
    contador = _max_num_recurso(recursos_previos, ultimo_id) + 1
    urls_registradas: Dict[str, str] = {}

    prev_por_url: Dict[str, Recurso] = {}
    if recursos_previos:
        for r in recursos_previos.values():
            if r.referencia:
                prev_por_url[r.referencia] = r
                try:
                    prev_por_url[sanitizar_url_recurso(r.referencia)] = r
                except ValueError:
                    pass

    resultado = str(texto)

    # 1. Enmascarar bloques de código cercados e inline para preservar ejemplos de código
    bloques_codigo_cercados: List[str] = []
    bloques_codigo_inline: List[str] = []

    def _mask_fenced(m: re.Match) -> str:
        idx = len(bloques_codigo_cercados)
        bloques_codigo_cercados.append(m.group(0))
        return f"\x00BACO_CODE_FENCED_{idx}\x00"

    def _mask_inline(m: re.Match) -> str:
        idx = len(bloques_codigo_inline)
        bloques_codigo_inline.append(m.group(0))
        return f"\x00BACO_CODE_INLINE_{idx}\x00"

    resultado = re.sub(r"(?:```[\s\S]*?```|~~~[\s\S]*?~~~)", _mask_fenced, resultado)
    resultado = re.sub(r"(`+)([^`\n]+?)\1", _mask_inline, resultado)

    def _registrar(url_raw: str, tipo: TipoRecurso, nombre_raw: str = "", fallback_prefix: str = "Recurso") -> Optional[str]:
        nonlocal contador
        try:
            url_limpia = sanitizar_url_recurso(url_raw)
        except ValueError:
            return None

        partes_u = urlsplit(url_limpia)
        fallback_nom = Path(partes_u.path).name or f"{fallback_prefix} {len(recursos) + 1}"
        nombre = (nombre_raw or "").strip() or fallback_nom
        from baco.server.services.validar_articulo import sanitizar_borrador
        nombre = sanitizar_borrador(texto=nombre)["texto_sanitizado"].strip()

        if url_limpia in urls_registradas:
            return f"[[recurso:{urls_registradas[url_limpia]}]]"

        if url_limpia in prev_por_url:
            rec_prev = prev_por_url[url_limpia]
            rec_id = rec_prev.id
            urls_registradas[url_limpia] = rec_id
            recursos[rec_id] = Recurso(
                id=rec_id,
                tipo=rec_prev.tipo or tipo,
                nombre=nombre or rec_prev.nombre,
                origen=rec_prev.origen,
                tamano_bytes=rec_prev.tamano_bytes,
                mime_type=rec_prev.mime_type,
                referencia=url_limpia,
                orden=len(recursos),
            )
            return f"[[recurso:{rec_id}]]"

        while f"rec_{contador}" in recursos or (recursos_previos and f"rec_{contador}" in recursos_previos):
            contador += 1
        rec_id = f"rec_{contador}"
        contador += 1
        urls_registradas[url_limpia] = rec_id
        recursos[rec_id] = Recurso(
            id=rec_id,
            tipo=tipo,
            nombre=nombre,
            origen="existente",
            referencia=url_limpia,
            orden=len(recursos),
        )
        return f"[[recurso:{rec_id}]]"

    # 2. Convertir o sanitizar etiquetas HTML multimedia
    def _sub_html_img(m: re.Match) -> str:
        tag = m.group(0)
        src = _extraer_attr_html(tag, "src")
        if not src:
            return ""
        alt = _extraer_attr_html(tag, "alt") or _extraer_attr_html(tag, "title")
        marcador = _registrar(src, "imagen", alt, "Imagen")
        return marcador if marcador is not None else ""

    def _sub_html_video(m: re.Match) -> str:
        bloque = m.group(0)
        src = _extraer_attr_html(bloque, "src")
        if not src:
            m_source = re.search(r"<source\b[^>]*>", bloque, flags=re.IGNORECASE)
            if m_source:
                src = _extraer_attr_html(m_source.group(0), "src")
        if not src:
            return ""
        titulo = _extraer_attr_html(bloque, "title") or "Video"
        marcador = _registrar(src, "video", titulo, "Video")
        return marcador if marcador is not None else ""

    def _sub_html_audio(m: re.Match) -> str:
        bloque = m.group(0)
        src = _extraer_attr_html(bloque, "src")
        if not src:
            m_source = re.search(r"<source\b[^>]*>", bloque, flags=re.IGNORECASE)
            if m_source:
                src = _extraer_attr_html(m_source.group(0), "src")
        if not src:
            return ""
        titulo = _extraer_attr_html(bloque, "title") or "Audio"
        marcador = _registrar(src, "audio", titulo, "Audio")
        return marcador if marcador is not None else ""

    def _sub_html_iframe(m: re.Match) -> str:
        bloque = m.group(0)
        src = _extraer_attr_html(bloque, "src")
        if not src:
            return ""
        u_low = src.lower()
        dominios_iframe_permitidos = ("youtube.com", "youtu.be", "vimeo.com", "loom.com", "docs.google.com")
        if not any(d in u_low for d in dominios_iframe_permitidos):
            return bloque
        if "docs.google.com" in u_low or "presentation" in u_low or "slides" in u_low or "document" in u_low:
            tipo: TipoRecurso = "documento"
            def_nom = "Documento"
        else:
            t_det = clasificar_tipo_recurso(src)
            tipo = t_det if t_det != "otro" else "video"
            def_nom = "Video embebido"
        titulo = _extraer_attr_html(bloque, "title") or def_nom
        marcador = _registrar(src, tipo, titulo, def_nom)
        return marcador if marcador is not None else ""

    resultado = re.sub(r"<video\b[^>]*>[\s\S]*?</video>|<video\b[^>]*/>", _sub_html_video, resultado, flags=re.IGNORECASE)
    resultado = re.sub(r"<audio\b[^>]*>[\s\S]*?</audio>|<audio\b[^>]*/>", _sub_html_audio, resultado, flags=re.IGNORECASE)
    resultado = re.sub(r"<iframe\b[^>]*>[\s\S]*?</iframe>|<iframe\b[^>]*/>", _sub_html_iframe, resultado, flags=re.IGNORECASE)
    resultado = re.sub(r"<img\b[^>]*>", _sub_html_img, resultado, flags=re.IGNORECASE)

    # 3. Enlaces Markdown y URLs sueltas
    # Soporta imágenes absolutas, relativas o data URIs
    re_media = re.compile(r"(!)?\[([^\]]*)\]\(([^\s\)]+)\)")
    re_url_suelta = re.compile(r"^(https?://[^\s]+)$")

    def _sub_media(match: re.Match) -> str:
        es_bang = match.group(1) == "!"
        texto_link = match.group(2).strip()
        url = match.group(3).strip()

        if es_bang:
            tipo = "imagen"
            nombre = texto_link
            marcador = _registrar(url, tipo, nombre, "Imagen")
            # Si no se puede registrar como recurso formal (relativa, data: URI, etc.), sanitizar
            return marcador if marcador is not None else ""
        elif "|attachment" in texto_link:
            nombre = texto_link.split("|attachment")[0].strip() or f"Adjunto {len(recursos) + 1}"
            tipo = clasificar_tipo_recurso(url, nombre)
            if tipo == "otro":
                tipo = "documento"
            marcador = _registrar(url, tipo, nombre, "Adjunto")
            return marcador if marcador is not None else ""
        else:
            nombre = texto_link
            u_low = url.lower()
            u_sin_q = url.split("?")[0].split("#")[0].lower()
            tipo = clasificar_tipo_recurso(u_sin_q, nombre)
            es_multimedia = tipo in ("imagen", "video", "audio", "documento") and (
                "docs.google" in u_low
                or "youtube" in u_low
                or "youtu.be" in u_low
                or "vimeo" in u_low
                or "loom.com" in u_low
                or "/uploads/" in u_low
                or any(u_sin_q.endswith(ext) for ext in EXTS_IMAGEN | EXTS_VIDEO | EXTS_DOCUMENTO | EXTS_AUDIO)
            )
            if not es_multimedia:
                return match.group(0)
            marcador = _registrar(url, tipo, nombre, "Recurso")
            return marcador if marcador is not None else ""

    # Procesar línea a línea de arriba hacia abajo para preservar el orden secuencial de IDs y aparición
    lineas = resultado.splitlines()
    nuevas_lineas = []
    for linea in lineas:
        l_strip = linea.strip()
        m = re_url_suelta.match(l_strip)
        if m:
            url = m.group(1)
            u_sin_q = url.split("?")[0].split("#")[0].lower()
            tipo = clasificar_tipo_recurso(u_sin_q)
            if tipo in ("imagen", "video", "audio", "documento") and (
                "youtube" in url
                or "youtu.be" in url
                or "vimeo" in url
                or "docs.google" in url
                or any(u_sin_q.endswith(ext) for ext in EXTS_IMAGEN | EXTS_VIDEO | EXTS_DOCUMENTO | EXTS_AUDIO)
            ):
                marcador = _registrar(url, tipo, "Video tutorial" if tipo == "video" else "Documento de soporte", "Recurso")
                if marcador is not None:
                    nuevas_lineas.append(marcador)
                    continue
        nuevas_lineas.append(re_media.sub(_sub_media, linea))

    resultado = "\n".join(nuevas_lineas)

    # Limpieza: espacios sobrantes donde estaba el recurso y saltos de línea repetidos
    resultado = "\n".join(l.rstrip() for l in resultado.splitlines())
    resultado = re.sub(r"[ \t]{2,}", " ", resultado)
    resultado = re.sub(r"[ \t]+([.,;:!?])", r"\1", resultado)
    bloques = [b.strip() for b in re.split(r"\n\s*\n", resultado)]
    bloques = [b for b in bloques if b]
    while bloques and bloques[-1] == SECCION_RECURSOS_TITULO:
        bloques.pop()
    texto_limpio = "\n\n".join(bloques).strip()

    # 4. Restaurar bloques de código inline y cercados
    for idx, codigo_inline in enumerate(bloques_codigo_inline):
        texto_limpio = texto_limpio.replace(f"\x00BACO_CODE_INLINE_{idx}\x00", codigo_inline)
    for idx, codigo_cercado in enumerate(bloques_codigo_cercados):
        texto_limpio = texto_limpio.replace(f"\x00BACO_CODE_FENCED_{idx}\x00", codigo_cercado)

    sincronizar_orden_recursos_desde_texto(texto_limpio, recursos)

    return texto_limpio, recursos


def sincronizar_orden_recursos_desde_texto(texto: str, recursos: Dict[str, Recurso]) -> List[Recurso]:
    """Sincroniza r.orden según la posición de aparición de cada marcador [[recurso:<id>]] en el texto.
    Los IDs de los recursos permanecen estables (no se renumeran)."""
    marcadores = re.findall(r"\[\[recurso:([a-zA-Z0-9_\-]+)\]\]", texto or "")
    vistos = set()
    orden_idx = 0
    for rid in marcadores:
        if rid in recursos and rid not in vistos:
            recursos[rid].orden = orden_idx
            orden_idx += 1
            vistos.add(rid)
    for r in sorted(recursos.values(), key=lambda x: x.orden):
        if r.id not in vistos:
            r.orden = orden_idx
            orden_idx += 1
            vistos.add(r.id)
    return sorted(recursos.values(), key=lambda r: r.orden)


def derivar_desde_bloques(
    bloques: List[BloqueItem],
    recursos_previos: Optional[Dict[str, Recurso]] = None,
    ultimo_id: int = 0,
) -> Tuple[str, Dict[str, Recurso], Optional[str]]:
    r"""Función pura que deriva texto_limpio (con marcadores [[recurso:rec_N]]) y
    el diccionario de recursos ordenados correlativamente.

    Garantiza:
    - Pureza: no muta los objetos de entrada ni estado global.
    - Rechazo estricto si el usuario intentó inyectar [[recurso:...]] o [[R\d+]] manualmente en texto.
    - Sanitización de URL (sin query strings sensibles, fragmentos ni credenciales).
    - Bloqueo de SVG y validación de tipos / tamaños.
    - Idempotencia: re-ejecutar con los mismos bloques genera exactamente el mismo resultado e IDs estables.
    - Aviso con únicamente tipo y cantidad de recursos detectados.
    """
    if not bloques:
        return "", {}, None

    partes_texto: List[str] = []
    recursos: Dict[str, Recurso] = {}
    conteo_tipos: Dict[str, int] = {}
    rec_counter = max(_max_num_recurso(recursos_previos, ultimo_id), int(ultimo_id or 0)) + 1

    prev_por_url: Dict[str, str] = {}
    if recursos_previos:
        for r in recursos_previos.values():
            if r.referencia:
                prev_por_url[r.referencia] = r.id

    for b in bloques:
        if b.tipo == "texto":
            contenido = str(b.contenido or "").strip()
            if re.search(r"\[\[recurso:[^\]]+\]\]", contenido) or re.search(r"\[\[R\d+\]\]", contenido):
                raise RecursoInvalidoError(
                    "El texto no puede incluir marcadores reservados del sistema como [[recurso:...]] o [[R1]]."
                )
            if contenido:
                partes_texto.append(contenido)
        elif b.tipo == "recurso":
            rec_in = b.recurso
            if not rec_in or not rec_in.url:
                raise RecursoInvalidoError("El bloque de recurso no contiene una URL válida.")

            try:
                url_limpia = sanitizar_url_recurso(rec_in.url)
            except ValueError as ve:
                raise RecursoInvalidoError(str(ve))
            partes_url = urlsplit(url_limpia)
            ext = Path(partes_url.path).suffix.lower()

            if ext == ".svg" or (rec_in.mime_type and "svg" in rec_in.mime_type.lower()):
                raise RecursoInvalidoError("No se permiten archivos SVG por razones de seguridad.")

            if rec_in.tamano_bytes is not None and rec_in.tamano_bytes > RECURSO_MAX_BYTES:
                raise RecursoInvalidoError(
                    f"El recurso supera el tamaño máximo permitido de {RECURSO_MAX_BYTES // (1024 * 1024)} MB."
                )

            tipo = rec_in.tipo or clasificar_tipo_recurso(url_limpia, rec_in.nombre or "", rec_in.mime_type)

            # ID estable: si ya existía con la misma URL en recursos_previos o en la misma pasada, reutilizar su id
            if url_limpia in prev_por_url:
                rec_id = prev_por_url[url_limpia]
            else:
                rec_id = f"rec_{rec_counter}"
                while rec_id in recursos or (recursos_previos and rec_id in recursos_previos):
                    rec_counter += 1
                    rec_id = f"rec_{rec_counter}"
                prev_por_url[url_limpia] = rec_id
                rec_counter += 1

            marcador = f"[[recurso:{rec_id}]]"
            partes_texto.append(marcador)

            if rec_id not in recursos:
                nombre = (rec_in.nombre or "").strip() or Path(partes_url.path).name or f"Recurso {len(recursos) + 1}"
                recursos[rec_id] = Recurso(
                    id=rec_id,
                    tipo=tipo,
                    nombre=nombre,
                    origen="existente",
                    tamano_bytes=rec_in.tamano_bytes,
                    mime_type=rec_in.mime_type,
                    referencia=url_limpia,
                    orden=len(recursos),
                )
                conteo_tipos[tipo] = conteo_tipos.get(tipo, 0) + 1

    texto_limpio = "\n\n".join(partes_texto).strip()

    # Aviso con solo tipo y cantidad
    aviso = None
    if recursos:
        partes_aviso = []
        for t, cnt in conteo_tipos.items():
            plural = "imágenes" if t == "imagen" else f"{t}s"
            partes_aviso.append(f"{cnt} {t}" if cnt == 1 else f"{cnt} {plural}")
        aviso = f"Se detectaron {len(recursos)} recursos ({', '.join(partes_aviso)})."

    return texto_limpio, recursos, aviso


def reindexar_marcadores_tras_eliminar(texto: str, orden_eliminado: int) -> str:
    """Elimina [[R{orden_eliminado+1}]] y renumera correlativamente los marcadores posteriores."""
    if not texto:
        return ""
    marcador_a_quitar = f"[[R{orden_eliminado + 1}]]"
    nuevo = texto.replace(marcador_a_quitar, "")

    def _sub_renum(m: re.Match) -> str:
        num = int(m.group(1))
        if num > orden_eliminado + 1:
            return f"[[R{num - 1}]]"
        return m.group(0)

    nuevo = re.sub(r"\[\[R(\d+)\]\]", _sub_renum, nuevo)
    bloques = [b.strip() for b in re.split(r"\n\s*\n", nuevo)]
    return "\n\n".join(b for b in bloques if b).strip()


def reindexar_marcadores_tras_reordenar(texto: str, mapa_orden: Dict[int, int]) -> str:
    """Actualiza los marcadores [[R{n}]] en el texto según el nuevo orden (0-indexed)."""
    if not texto or not mapa_orden:
        return texto

    def _sub_orden(m: re.Match) -> str:
        viejo_idx = int(m.group(1)) - 1
        nuevo_idx = mapa_orden.get(viejo_idx, viejo_idx)
        return f"[[__TEMP_R_{nuevo_idx + 1}__]]"

    temp = re.sub(r"\[\[R(\d+)\]\]", _sub_orden, texto)
    return re.sub(r"\[\[__TEMP_R_(\d+)__\]\]", r"[[R\1]]", temp)


SECCION_RECURSOS_TITULO = "## Recursos"


def _recursos_ordenados(recursos: Union[Dict[str, Recurso], Iterable[Recurso], None]) -> List[Recurso]:
    if not recursos:
        return []
    valores = recursos.values() if isinstance(recursos, dict) else recursos
    return sorted(valores, key=lambda r: r.orden)


def _recurso_a_markdown(rec: Recurso) -> str:
    if rec.tipo == "imagen":
        return f"![{rec.nombre}]({rec.referencia})"
    if rec.tipo == "video":
        if rec.referencia.startswith("http://") or rec.referencia.startswith("https://"):
            return rec.referencia
        return f"[{rec.nombre}]({rec.referencia})"
    if rec.tipo == "documento" and (
        "/uploads/" in rec.referencia or rec.referencia.endswith((".pdf", ".zip", ".docx"))
    ):
        return f"[{rec.nombre}|attachment]({rec.referencia})"
    return f"[{rec.nombre}]({rec.referencia})"


def componer_texto_publicable(
    texto_limpio: str, recursos: Union[Dict[str, Recurso], Iterable[Recurso], None]
) -> str:
    """Cambio 4: sustituye cada marcador por su Markdown en la posición exacta,

    sin sección ## Recursos al final. Los recursos sin marcador en el texto se
    anexan al final como Markdown sin encabezado ## Recursos.
    """
    cuerpo = (texto_limpio or "").strip()
    if not recursos:
        return cuerpo

    recs_map: Dict[str, Recurso] = {}
    if isinstance(recursos, dict):
        recs_map = dict(recursos)
    else:
        recs_map = {r.id: r for r in recursos}

    items_ordenados = sorted(recs_map.values(), key=lambda r: r.orden)
    recursos_sustituidos = set()

    def _sustituir(m: re.Match) -> str:
        rec_id = m.group(1)
        if rec_id and rec_id in recs_map:
            recursos_sustituidos.add(rec_id)
            return _recurso_a_markdown(recs_map[rec_id])

        r_num = m.group(2)
        if r_num:
            idx = int(r_num) - 1
            if 0 <= idx < len(items_ordenados):
                r = items_ordenados[idx]
                recursos_sustituidos.add(r.id)
                return _recurso_a_markdown(r)
        return m.group(0)

    patron = r"\[\[(?:recurso:([a-zA-Z0-9_\-]+)|R(\d+))\]\]"
    resultado = re.sub(patron, _sustituir, cuerpo) if cuerpo else ""

    # Recursos en el borrador que no tenían marcador en el texto (sin sección ## Recursos)
    restantes = [r for r in items_ordenados if r.id not in recursos_sustituidos]
    if restantes:
        bloque_restantes = "\n\n".join(_recurso_a_markdown(r) for r in restantes)
        resultado = f"{resultado}\n\n{bloque_restantes}" if resultado else bloque_restantes

    return resultado


def reconstruir_texto_con_recursos(
    texto_limpio: str, recursos: Union[Dict[str, Recurso], Iterable[Recurso], None]
) -> str:
    """Compatibilidad: compone el texto para publicación/vista previa a partir de texto_limpio y recursos."""
    return componer_texto_publicable(texto_limpio, recursos)


def verificar_y_restaurar_marcadores(
    texto: str, recursos: Dict[str, Recurso]
) -> Tuple[str, List[str]]:
    """Verifica determinísticamente que todos los marcadores de recursos existan en el texto.
    Si falta alguno, lo restaura al final del texto y genera una advertencia."""
    advertencias: List[str] = []
    texto_res = texto or ""
    for r in sorted(recursos.values(), key=lambda x: x.orden):
        marcador = f"[[recurso:{r.id}]]"
        if marcador not in texto_res:
            advertencias.append(
                f"Se restauró el marcador faltante para '{r.nombre}' ({marcador}) al final del texto."
            )
            texto_res = f"{texto_res}\n\n{marcador}".strip()
    return texto_res, advertencias


def generar_id_recurso_libre(
    recursos: Optional[Dict[str, Recurso]], ultimo_id: int = 0
) -> str:
    """Devuelve el primer `rec_N` que no esté en uso (nunca pisa un recurso existente ni IDs ya usados)."""
    usados = set(recursos or {})
    n = max(int(ultimo_id or 0), _max_num_recurso(recursos, ultimo_id)) + 1
    while f"rec_{n}" in usados:
        n += 1
    return f"rec_{n}"


def _ruta_sin_query(url: str) -> str:
    """Para clasificar por extensión: descarta ?query y #fragmento de la URL."""
    return urlsplit(url)._replace(query="", fragment="").geturl()


def crear_recurso_desde_url(
    url: str,
    recursos_actuales: Dict[str, Recurso],
    nombre: Optional[str] = None,
    tipo_sugerido: Optional[TipoRecurso] = None,
    ultimo_id: int = 0,
) -> Recurso:
    """Crea un recurso multimedia a partir de una URL pegada en el mini panel.

    - Solo http/https.
    - Respeta el cupo MAX_RECURSOS_POR_SESION.
    - Rechaza URLs ya presentes en el borrador.
    - Detecta el tipo; `tipo_sugerido` solo se usa si la detección no es concluyente.
    """
    url = (url or "").strip()
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.netloc:
        raise RecursoInvalidoError("La URL debe comenzar con http:// o https://.")
    if len(url) > 2048:
        raise RecursoInvalidoError("La URL es demasiado larga (máximo 2048 caracteres).")
    if len(recursos_actuales) >= MAX_RECURSOS_POR_SESION:
        raise RecursoInvalidoError(
            f"Se alcanzó el límite máximo de {MAX_RECURSOS_POR_SESION} recursos para este borrador."
        )
    if any(r.referencia == url for r in recursos_actuales.values()):
        raise RecursoDuplicadoError("Ese recurso ya está en el borrador.")

    tipo = clasificar_tipo_recurso(_ruta_sin_query(url), nombre or "")
    if tipo == "otro":
        if not tipo_sugerido or tipo_sugerido == "otro":
            raise RecursoInvalidoError(
                "No se reconoce el enlace como imagen, video, audio o documento. "
                "Indicá el tipo si estás seguro de que lo es."
            )
        tipo = tipo_sugerido

    nombre_final = (nombre or "").strip() or Path(partes.path).name or partes.netloc
    return Recurso(
        id=generar_id_recurso_libre(recursos_actuales, ultimo_id=ultimo_id),
        tipo=tipo,
        nombre=nombre_final[:200],
        origen="existente",
        referencia=url,
        orden=len(recursos_actuales),
    )


def fusionar_recursos(
    existentes: Optional[Dict[str, Recurso]], nuevos: Optional[Dict[str, Recurso]]
) -> Dict[str, Recurso]:
    """Suma `nuevos` al final de `existentes` sin pisar IDs.

    - Si un recurso nuevo apunta a la misma referencia que uno existente, se conserva el existente.
    - Los nuevos reciben un ID libre (rec_N) y un orden correlativo a continuación.
    """
    base = _recursos_ordenados(existentes)
    resultado: Dict[str, Recurso] = {}
    for i, r in enumerate(base):
        r.orden = i
        resultado[r.id] = r

    referencias = {r.referencia for r in base if r.referencia}
    for r in _recursos_ordenados(nuevos):
        if r.referencia and r.referencia in referencias:
            continue
        nuevo = r.model_copy(update={"id": generar_id_recurso_libre(resultado), "orden": len(resultado)})
        resultado[nuevo.id] = nuevo
        if nuevo.referencia:
            referencias.add(nuevo.referencia)
    return resultado


def eliminar_recurso_borrador(
    recursos: Dict[str, Recurso], recurso_id: str
) -> Tuple[Dict[str, Recurso], bool]:
    """Elimina el recurso del diccionario de recursos del borrador.

    No lee ni modifica texto_limpio: los recursos multimedia viven siempre aparte.
    Si es un recurso subido físicamente, elimina el archivo temporal en disco.
    Retorna (nuevos_recursos, fue_eliminado).
    """
    if recurso_id not in recursos:
        return recursos, False

    rec = recursos.pop(recurso_id)

    # Si era archivo subido temporal en disco, lo eliminamos físicamente
    if rec.origen == "subido" and rec.referencia:
        p = Path(rec.referencia)
        if p.exists() and p.is_file():
            try:
                p.unlink()
            except Exception as e:
                logger.warning("No se pudo eliminar el archivo temporal %s: %s", p, e)

    # Re-indexar correlativamente los recursos restantes
    restantes = sorted(recursos.values(), key=lambda r: r.orden)
    for i, r in enumerate(restantes):
        r.orden = i

    return recursos, True


def guardar_recurso_temporal_sesion(
    session_id: str,
    filename: str,
    contenido_bytes: bytes,
    content_type_declarado: Optional[str],
    recursos_actuales: Dict[str, Recurso],
    ultimo_id: int = 0,
) -> Recurso:
    """Valida y guarda un recurso subido por el usuario en el almacenamiento temporal de sesión.

    Verifica:
    - Flag PERMITIR_SUBIDA_RECURSOS
    - Cantidad máxima de recursos por sesión
    - Tamaño máximo en bytes
    - Tipo MIME real verificado
    """
    if not PERMITIR_SUBIDA_RECURSOS:
        raise SubidaRecursosDeshabilitadaError(
            "La subida de recursos nuevos está deshabilitada en esta fase de BACO (modo validador)."
        )

    if len(recursos_actuales) >= MAX_RECURSOS_POR_SESION:
        raise RecursoInvalidoError(
            f"Se alcanzó el límite máximo de {MAX_RECURSOS_POR_SESION} recursos para este borrador."
        )

    if len(contenido_bytes) > RECURSO_MAX_BYTES:
        raise RecursoInvalidoError(
            f"El archivo supera el tamaño máximo permitido de {RECURSO_MAX_BYTES // (1024 * 1024)} MB "
            f"({len(contenido_bytes)} bytes)."
        )

    nombre_seguro = sanitizar_nombre_archivo(filename)
    mime_real = detectar_mime_type_real(contenido_bytes, nombre_seguro)

    if mime_real == "image/svg+xml" or nombre_seguro.lower().endswith(".svg"):
        raise RecursoInvalidoError("No se permiten archivos SVG por razones de seguridad.")

    if mime_real not in MIMES_PERMITIDOS or mime_real == "application/octet-stream":
        raise RecursoInvalidoError(
            f"Tipo de archivo no permitido o MIME no reconocido ({mime_real})."
        )

    if content_type_declarado and content_type_declarado != "application/octet-stream":
        cat_decl = content_type_declarado.split("/")[0]
        cat_real = mime_real.split("/")[0]
        if cat_decl in ("image", "video", "audio") and cat_decl != cat_real:
            raise RecursoInvalidoError(
                f"Inconsistencia de tipo MIME detectada: se declaró '{content_type_declarado}' pero el contenido real es '{mime_real}'."
            )

    tipo = clasificar_tipo_recurso(nombre_seguro, nombre=nombre_seguro, mime=mime_real)
    if tipo == "otro":
        raise RecursoInvalidoError(f"No se pudo determinar una categoría válida para el archivo '{nombre_seguro}'.")

    # Crear carpeta temporal de la sesión
    dir_sesion = DIR_TEMP_SESIONES / session_id
    dir_sesion.mkdir(parents=True, exist_ok=True)

    rec_id = generar_id_recurso_libre(recursos_actuales, ultimo_id=ultimo_id)
    archivo_destino = dir_sesion / f"{rec_id}_{nombre_seguro}"
    archivo_destino.write_bytes(contenido_bytes)

    # Preparado para Redis: referencia guarda solo la ruta relativa en disco, nunca bytes
    return Recurso(
        id=rec_id,
        tipo=tipo,
        nombre=nombre_seguro,
        origen="subido",
        tamano_bytes=len(contenido_bytes),
        mime_type=mime_real,
        referencia=str(archivo_destino),
        orden=len(recursos_actuales),
    )


def limpiar_archivos_temporales_sesion(session_id: str) -> None:
    """Elimina el directorio de almacenamiento temporal y todos los archivos de la sesión."""
    if not session_id:
        return
    dir_sesion = DIR_TEMP_SESIONES / session_id
    if dir_sesion.exists() and dir_sesion.is_dir():
        try:
            shutil.rmtree(dir_sesion)
        except Exception as exc:
            logger.warning("Error al limpiar archivos temporales de sesión %s: %s", session_id, exc)


RE_MARCADORES_CANONICOS = re.compile(r"\[\[(?:recurso:[a-zA-Z0-9_\-]+|R\d+)\]\]", re.IGNORECASE)


def texto_efectivo_sin_marcadores(texto: str) -> str:
    """Elimina marcadores canónicos de recursos ([[recurso:...]] y [[R1]]) para medir
    o comparar el contenido textual efectivo real (los marcadores PII se conservan).
    """
    if not texto:
        return ""
    limpio = RE_MARCADORES_CANONICOS.sub("", str(texto))
    lineas = [re.sub(r"[ \t]+", " ", l).strip() for l in limpio.splitlines()]
    bloques = [b for b in "\n".join(lineas).split("\n\n") if b.strip()]
    return "\n\n".join(bloques).strip()


def fusionar_texto_y_recursos_sin_colision(
    texto: str,
    recursos_base: Optional[Dict[str, Recurso]],
    recursos_nuevos: Optional[Dict[str, Recurso]],
    ultimo_id: int = 0,
) -> Tuple[str, Dict[str, Recurso]]:
    """Fusiona recursos_nuevos dentro de recursos_base evitando colisiones de ID
    y reusando recursos si la URL/referencia ya existe.
    Si un ID de recurso nuevo es remapeado a otro ID, actualiza [[recurso:<id>]] en el texto.
    """
    recs_resultado: Dict[str, Recurso] = dict(recursos_base or {})
    if not recursos_nuevos:
        return texto, recs_resultado

    referencias_existentes: Dict[str, str] = {}
    for r in recs_resultado.values():
        if r.referencia:
            referencias_existentes[r.referencia] = r.id
            try:
                referencias_existentes[sanitizar_url_recurso(r.referencia)] = r.id
            except ValueError:
                pass

    contador = max(_max_num_recurso(recs_resultado, ultimo_id), _max_num_recurso(recursos_nuevos, ultimo_id)) + 1
    texto_actualizado = texto

    for rec in _recursos_ordenados(recursos_nuevos):
        rec_id = rec.id
        ref = rec.referencia
        ref_sanitizada = None
        if ref:
            try:
                ref_sanitizada = sanitizar_url_recurso(ref)
            except ValueError:
                pass

        target_id = None
        if ref and ref in referencias_existentes:
            target_id = referencias_existentes[ref]
        elif ref_sanitizada and ref_sanitizada in referencias_existentes:
            target_id = referencias_existentes[ref_sanitizada]

        if target_id is not None:
            if rec_id != target_id:
                texto_actualizado = texto_actualizado.replace(f"[[recurso:{rec_id}]]", f"[[recurso:{target_id}]]")
            continue

        nuevo_id = rec_id
        if nuevo_id in recs_resultado:
            while f"rec_{contador}" in recs_resultado or (recursos_nuevos and f"rec_{contador}" in recursos_nuevos):
                contador += 1
            nuevo_id = f"rec_{contador}"
            contador += 1
            texto_actualizado = texto_actualizado.replace(f"[[recurso:{rec_id}]]", f"[[recurso:{nuevo_id}]]")

        recurso_agregado = rec.model_copy(update={"id": nuevo_id, "orden": len(recs_resultado)})
        recs_resultado[nuevo_id] = recurso_agregado
        if ref:
            referencias_existentes[ref] = nuevo_id
        if ref_sanitizada:
            referencias_existentes[ref_sanitizada] = nuevo_id

    sincronizar_orden_recursos_desde_texto(texto_actualizado, recs_resultado)
    return texto_actualizado, recs_resultado


def procesar_recursos_y_marcadores(
    texto: str,
    recursos_previos: Optional[Dict[str, Recurso]] = None,
    ultimo_id: int = 0,
    validar_marcadores_existentes: bool = True,
    mensaje_error_custom: Optional[str] = None,
) -> Tuple[str, Dict[str, Recurso], Optional[str]]:
    """Procesa el texto de entrada:
    1. Valida si contiene marcadores manuales no permitidos (p. ej. [[R1]] o [[recurso:X]] no existente en recursos_previos).
       Si contiene marcadores manuales no válidos y validar_marcadores_existentes es True, retorna un mensaje de error.
    2. Extrae recursos nuevos (Markdown, HTML, URLs) y sanitiza referencias relativas o data URIs.
    3. Fusiona sin colisiones con los recursos previos.
    Retorna (texto_limpio, recursos, error).
    """
    if not texto:
        return "", dict(recursos_previos or {}), None

    recs_prev = dict(recursos_previos or {})

    if validar_marcadores_existentes:
        marcadores_encontrados = re.findall(r"\[\[(?:recurso:([a-zA-Z0-9_\-]+)|(R\d+))\]\]", texto)
        invalidos = []
        for m_rec, m_r in marcadores_encontrados:
            if m_r:
                invalidos.append(f"[[{m_r}]]")
            elif m_rec and m_rec not in recs_prev:
                invalidos.append(f"[[recurso:{m_rec}]]")

        if invalidos:
            msg_tpl = mensaje_error_custom or (
                "El texto contiene marcadores no válidos ({marcadores}). "
                "Los recursos multimedia deben adjuntarse mediante enlaces o subida de archivos, no escribiendo marcadores manualmente."
            )
            return texto, recs_prev, msg_tpl.format(marcadores=", ".join(invalidos))

    tl, recs_nuevos = extraer_recursos_y_texto_limpio(
        texto, recursos_previos=recs_prev, ultimo_id=ultimo_id
    )

    tl_fused, recs_fused = fusionar_texto_y_recursos_sin_colision(
        tl, recs_prev, recs_nuevos, ultimo_id=ultimo_id
    )
    return tl_fused, recs_fused, None


def sincronizar_recursos_con_marcadores(
    texto: str, recursos: Optional[Dict[str, Recurso]]
) -> Dict[str, Recurso]:
    """Filtra y ordena los recursos presentes en el texto según la posición de sus marcadores.
    Si el usuario eliminó un marcador del texto, el recurso se elimina de la colección.
    """
    if not recursos:
        return {}
    marcadores = re.findall(r"\[\[recurso:([a-zA-Z0-9_\-]+)\]\]", texto or "")
    resultado: Dict[str, Recurso] = {}
    vistos = set()
    orden_idx = 0
    for rid in marcadores:
        if rid in recursos and rid not in vistos:
            rec = recursos[rid].model_copy(update={"orden": orden_idx})
            resultado[rid] = rec
            vistos.add(rid)
            orden_idx += 1
    return resultado


def eliminar_marcador_recurso_de_texto(texto: str, recurso_id: str) -> str:
    """Elimina el marcador [[recurso:<id>]] del texto limpio y normaliza espacios y párrafos."""
    if not texto or not recurso_id:
        return texto or ""
    patron = rf"\[\[recurso:{re.escape(str(recurso_id))}\]\]"
    resultado = re.sub(patron, "", texto)
    lineas = [re.sub(r"[ \t]+", " ", l).strip() for l in resultado.splitlines()]
    bloques = [b for b in "\n".join(lineas).split("\n\n") if b.strip()]
    return "\n\n".join(bloques).strip()


def permutar_marcadores_en_texto(
    texto: str, ids_antes: List[str], ids_despues: List[str]
) -> str:
    """Permuta la posición de los marcadores [[recurso:<id>]] en el texto siguiendo
    la reordenación de ids_antes a ids_despues.
    """
    if not texto or not ids_antes or not ids_despues or ids_antes == ids_despues:
        return texto or ""
    temp_map = {}
    for i, rid in enumerate(ids_antes):
        temp_map[f"[[recurso:{rid}]]"] = f"\x00REC_PERM_{i}\x00"

    res = texto
    for orig, temp in temp_map.items():
        res = res.replace(orig, temp)

    for i, rid in enumerate(ids_despues):
        res = res.replace(f"\x00REC_PERM_{i}\x00", f"[[recurso:{rid}]]")

    return res
