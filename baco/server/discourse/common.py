"""Módulo común para clientes y utilidades de la API de Discourse."""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

from baco.server.db.ingesta import discourse_base_url, normalizar_articulo
from baco.server.services.embeddings import embedding_titulo, embedding_texto

DISCOURSE_API_KEY = os.getenv("DISCOURSE_API_KEY", "")
DISCOURSE_API_USERNAME = os.getenv("DISCOURSE_API_USERNAME", "system")

HEADERS = {
    "Api-Key": DISCOURSE_API_KEY,
    "Api-Username": DISCOURSE_API_USERNAME,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
}

PAUSA_ENTRE_REQUESTS = 0.3
MAX_INTENTOS = 5


class ErrorAPIDiscourse(RuntimeError):
    pass


def pedir(http: httpx.Client, ruta: str, params: dict | None = None) -> dict:
    """GET con reintentos para 429 (rate limits) y 5xx."""
    ultimo_error = None
    for intento in range(MAX_INTENTOS):
        try:
            r = http.get(ruta, params=params)
            if r.status_code == 429:
                espera = int(r.headers.get("Retry-After", 10))
                print(f"   Rate limit alcanzado. Esperando {espera}s...")
                ultimo_error = "429 Too Many Requests"
                time.sleep(espera)
                continue
            if r.status_code in (502, 503, 504):
                ultimo_error = f"HTTP {r.status_code}"
                time.sleep(2 * (intento + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            ultimo_error = e
            time.sleep(2 * (intento + 1))
    raise ErrorAPIDiscourse(f"Error persistente en {ruta} tras {MAX_INTENTOS} intentos: {ultimo_error}")


def actualizar_embeddings_articulo(conn, art_id: int, titulo: str, texto: str) -> bool:
    """Calcula y persiste en PostgreSQL los embeddings de título y/o texto si están en NULL."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT embedding_titulo IS NULL, embedding_texto IS NULL FROM articulos WHERE id = %s;",
            (art_id,)
        )
        row = cur.fetchone()
        if not row:
            return False
        necesita_tit, necesita_txt = row

    if not necesita_tit and not necesita_txt:
        return False

    v_tit = embedding_titulo(titulo) if (necesita_tit and titulo and titulo.strip()) else None
    v_txt = embedding_texto(texto) if (necesita_txt and texto and texto.strip()) else None

    str_tit = ("[" + ",".join(str(f) for f in v_tit) + "]") if v_tit else None
    str_txt = ("[" + ",".join(str(f) for f in v_txt) + "]") if v_txt else None

    with conn.cursor() as cur:
        if str_tit and str_txt:
            cur.execute(
                "UPDATE articulos SET embedding_titulo = %s, embedding_texto = %s WHERE id = %s;",
                (str_tit, str_txt, art_id)
            )
        elif str_tit:
            cur.execute(
                "UPDATE articulos SET embedding_titulo = %s WHERE id = %s;",
                (str_tit, art_id)
            )
        elif str_txt:
            cur.execute(
                "UPDATE articulos SET embedding_texto = %s WHERE id = %s;",
                (str_txt, art_id)
            )
    conn.commit()
    print(f"       [EMBEDDINGS] Recalculados para ID {art_id} (título: {bool(str_tit)}, texto: {bool(str_txt)})")
    return True


def descargar_articulo(
    http: httpx.Client,
    tema_o_id: int | dict | None = None,
    tema_parcial: dict | None = None,
    *,
    tema_id: int | None = None,
    tema: dict | None = None,
) -> dict | None:
    """Descarga el detalle completo de un tema en Discourse y lo devuelve normalizado.
    
    Acepta tanto un tema_id int (con opcional tema_parcial dict) como un dict de tema directamente,
    por posición o por keyword (tema_id=..., tema=...).
    """
    if tema_id is not None:
        target_id = tema_id
        target_parcial = tema_parcial
    elif tema is not None:
        target_id = tema["id"]
        target_parcial = tema_parcial if tema_parcial is not None else tema
    elif isinstance(tema_o_id, dict):
        target_id = tema_o_id["id"]
        target_parcial = tema_parcial if tema_parcial is not None else tema_o_id
    elif tema_o_id is not None:
        target_id = tema_o_id
        target_parcial = tema_parcial
    else:
        raise ValueError("Se debe proporcionar tema_id o tema para descargar_articulo.")

    detalle = pedir(http, f"/t/{target_id}.json")
    posts = detalle.get("post_stream", {}).get("posts", [])
    if not posts:
        return None
    primer_post = posts[0]

    tags = detalle.get("tags")
    tags_listado = (target_parcial or {}).get("tags")
    if not (tags and isinstance(tags[0], dict)) and tags_listado and isinstance(tags_listado[0], dict):
        tags = tags_listado
    if tags is None:
        tags = tags_listado or []

    item = {
        "id": target_id,
        "title": detalle.get("title") or (target_parcial or {}).get("title"),
        "category_id": detalle.get("category_id", (target_parcial or {}).get("category_id")),
        "slug": detalle.get("slug") or (target_parcial or {}).get("slug"),
        "tags": tags,
        "raw": primer_post.get("raw"),
        "cooked": primer_post.get("cooked"),
        "updated_at": primer_post.get("updated_at") or (target_parcial or {}).get("bumped_at") or detalle.get("bumped_at"),
    }
    return normalizar_articulo(item, base_url=discourse_base_url())
