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

    preservando las imágenes, adjuntos y videos en sus posiciones originales.
    """
    if not cooked_html:
        return ""

    soup = BeautifulSoup(cooked_html, "html.parser")

    # 1. Imágenes con Lightbox (capturas principales)
    for a in soup.select("a.lightbox"):
        href = a.get("href", "")
        if href:
            url_img = href if href.startswith("http") else f"{base_url}{href}"
            img = a.find("img")
            alt = (img.get("alt") if img else "") or "image"
            a.replace_with(f"\n\n![{alt}]({url_img})\n\n")

    # 2. Imágenes estándar o sin lightbox (íconos, capturas menores)
    for img in soup.find_all("img"):
        if "emoji" in img.get("class", []):
            continue
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            url_img = src if src.startswith("http") else f"{base_url}{src}"
            alt = img.get("alt") or "image"
            img.replace_with(f"\n\n![{alt}]({url_img})\n\n")

    # 3. Diapositivas o Archivos adjuntos (PDFs, PPTs, etc.)
    for a in soup.select("a.attachment"):
        href = a.get("href", "")
        if href:
            url_adjunto = href if href.startswith("http") else f"{base_url}{href}"
            nombre = a.get_text(strip=True) or "archivo"
            a.replace_with(f"\n\n[{nombre}|attachment]({url_adjunto})\n\n")

    # 4. Videos embebidos (iframes de YouTube / Vimeo)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if "youtube" in src or "vimeo" in src:
            iframe.replace_with(f"\n\n{src}\n\n")

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
