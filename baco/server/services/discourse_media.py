"""
Servicio aislado para consultar en tiempo real el contenido de un artículo
desde la Base de Conocimiento pública de Finnegans (https://bc.finneg.com).

RESTRICCIONES ESTRICTAS:
1. ÚNICAMENTE peticiones GET.
2. NUNCA peticiones POST/PUT/DELETE hacia Discourse.
3. CERO persistencia: los datos recuperados no se guardan en PostgreSQL ni en disco.
4. Si el artículo no existe (404, timeout, error de red), falla con degradación elegante.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Tuple
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BC_PROD_URL = "https://bc.finneg.com"
TIMEOUT_SEGUNDOS = 5.0


def cooked_a_markdown_con_medios(cooked_html: str, base_url: str = BC_PROD_URL) -> str:
    """Convierte el HTML renderizado (cooked) de Discourse a texto Markdown
    preservando imágenes, diapositivas, documentos, videos, adjuntos y enlaces
    en sus posiciones originales con su formato y enlaces respetados.
    """
    if not cooked_html:
        return ""

    soup = BeautifulSoup(cooked_html, "html.parser")

    # 1. Bloques Onebox de Discourse (Google Docs, Slides, Wikipedia, etc.)
    for aside in soup.select("aside.onebox"):
        src = aside.get("data-onebox-src", "")
        h3_a = aside.select_one("article h3 a, h3 a, header a, a")
        href = (h3_a.get("href") if h3_a else "") or src
        if href:
            url = href if href.startswith(("http://", "https://")) else (src if src.startswith(("http://", "https://")) else f"{base_url}{href}")
            titulo = (h3_a.get_text(strip=True) if h3_a else "") or aside.get("data-onebox-title") or url
            aside.replace_with(f"\n\n[{titulo}]({url})\n\n")

    # 2. Videos de Discourse tipo lazyYT (reproductor YouTube diferido)
    for lyt in soup.select("div.lazyYT"):
        yt_id = lyt.get("data-youtube-id", "")
        yt_title = lyt.get("data-youtube-title", "") or "Video explicativo"
        if yt_id:
            yt_url = f"https://www.youtube.com/watch?v={yt_id}"
            lyt.replace_with(f"\n\n[{yt_title}]({yt_url})\n\n")

    # 3. Imágenes con Lightbox (capturas principales)
    for a in soup.select("a.lightbox"):
        href = a.get("href", "")
        if href:
            url_img = href if href.startswith("http") else f"{base_url}{href}"
            img = a.find("img")
            alt = (img.get("alt") if img else "") or "image"
            a.replace_with(f"\n\n![{alt}]({url_img})\n\n")

    # 4. Imágenes vinculadas mediante <a> no-lightbox (ej: <a href="..."><img src="..."></a>)
    for a in list(soup.find_all("a")):
        img = a.find("img")
        if img:
            if "emoji" in img.get("class", []):
                continue
            href = a.get("href", "")
            src = img.get("src", "")
            url_img = href or src
            if url_img and not url_img.startswith("data:"):
                url_final = url_img if url_img.startswith("http") else f"{base_url}{url_img}"
                alt = img.get("alt") or a.get_text(strip=True) or "image"
                a.replace_with(f"\n\n![{alt}]({url_final})\n\n")

    # 5. Imágenes estándar o sin lightbox (íconos, capturas menores)
    for img in soup.find_all("img"):
        if "emoji" in img.get("class", []):
            continue
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            url_img = src if src.startswith("http") else f"{base_url}{src}"
            alt = img.get("alt") or "image"
            img.replace_with(f"\n\n![{alt}]({url_img})\n\n")

    # 6. Diapositivas o Archivos adjuntos (PDFs, PPTs, etc.)
    for a in soup.select("a.attachment"):
        href = a.get("href", "")
        if href:
            url_adjunto = href if href.startswith("http") else f"{base_url}{href}"
            nombre = a.get_text(strip=True) or "archivo"
            a.replace_with(f"\n\n[{nombre}|attachment]({url_adjunto})\n\n")

    # 7. Videos HTML5 (<video><source src="..."></video>)
    for video in soup.find_all("video"):
        source = video.find("source")
        src = (source.get("src") if source else "") or video.get("src", "")
        if src:
            url_vid = src if src.startswith("http") else f"{base_url}{src}"
            video.replace_with(f"\n\n[Video]({url_vid})\n\n")

    # 8. Videos o presentaciones embebidas en <iframe> (YouTube, Vimeo, Google Slides, Google Docs)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if src:
            url_iframe = src if src.startswith("http") else f"{base_url}{src}"
            if "presentation" in url_iframe or "slides" in url_iframe:
                iframe.replace_with(f"\n\n[Diapositivas]({url_iframe})\n\n")
            elif "document" in url_iframe or "docs.google" in url_iframe:
                iframe.replace_with(f"\n\n[Documento]({url_iframe})\n\n")
            else:
                iframe.replace_with(f"\n\n{url_iframe}\n\n")

    # 9. Todos los demás enlaces <a> generales (Docs, Diapositivas, Videos y enlaces web)
    for a in list(soup.find_all("a")):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("javascript:"):
            continue
        url = href if href.startswith(("http://", "https://", "mailto:")) else f"{base_url}{href}"
        nombre = a.get_text(strip=True) or url
        a.replace_with(f" [{nombre}]({url}) ")

    # Extraer texto preservando saltos de línea y limpiando espacios superfluos
    lineas = [l.strip() for l in soup.get_text("\n").splitlines()]
    # Colapsar múltiples líneas vacías
    bloques: list[str] = []
    for l in lineas:
        if l:
            bloques.append(l)
        elif bloques and bloques[-1] != "":
            bloques.append("")

    return "\n".join(bloques).strip()


def consultar_articulo_bc_publico(
    articulo_id: int, client: Optional[httpx.Client] = None
) -> Tuple[Optional[str], Optional[int], List[str]]:
    """Consulta en tiempo real a bc.finneg.com vía GET anónimo.

    Retorna: (texto_con_medios, categoria_id, tags_slugs)
    Si ocurre cualquier error (404, 500, timeout, desconexión), retorna ("", None, []).
    """
    if not articulo_id:
        return None, None, []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    url = f"{BC_PROD_URL}/t/{articulo_id}.json"

    try:
        if client is not None:
            resp = client.get(url, headers=headers, timeout=TIMEOUT_SEGUNDOS)
        else:
            with httpx.Client(timeout=TIMEOUT_SEGUNDOS) as c:
                resp = c.get(url, headers=headers)

        if resp.status_code != 200:
            logger.info("bc.finneg.com retornó %s para tema %s (posible discrepancia dev/prod)", resp.status_code, articulo_id)
            return None, None, []

        data = resp.json()
        posts = data.get("post_stream", {}).get("posts", [])
        if not posts:
            return None, None, []

        cooked = posts[0].get("cooked", "")
        texto_md = cooked_a_markdown_con_medios(cooked, base_url=BC_PROD_URL)

        categoria_id = data.get("category_id")

        tags_raw = data.get("tags") or []
        tags_slugs: list[str] = []
        for t in tags_raw:
            if isinstance(t, dict):
                nombre = (t.get("slug") or t.get("name") or "").strip().lower()
                if nombre:
                    tags_slugs.append(nombre)
            elif isinstance(t, str) and t.strip():
                tags_slugs.append(t.strip().lower())

        return texto_md, categoria_id, tags_slugs

    except Exception as exc:
        logger.warning("Error de red consultando bc.finneg.com para tema %s: %s", articulo_id, exc)
        return None, None, []
