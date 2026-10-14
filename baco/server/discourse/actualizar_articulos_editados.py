"""
Pipeline de sincronización para artículos EDITADOS en Discourse -> baco_db.

Responsabilidad Única:
  - Audita el stream de actividad reciente en Discourse (/posts.json).
  - Filtra los posts raíz de artículos (post_number == 1).
  - Si un artículo ya existe en la base y su fecha de edición (updated_at) es posterior
    a la registrada en PostgreSQL, descarga el contenido actualizado, ejecuta el upsert
    y recalcula de inmediato sus embeddings vectoriales (título y/o texto) con ONNX INT8.
  - Las columnas calculadas STORED (normalizados, títulos base, textos limpios y hashes MD5)
    se recalculan automáticamente dentro del motor de PostgreSQL.

Uso:
    python -m baco.server.discourse.actualizar_articulos_editados
    python -m baco.server.discourse.actualizar_articulos_editados --paginas 5
"""

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Any

# Asegurar codificación utf-8 en terminal de Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx
from dotenv import load_dotenv

load_dotenv()

from baco.server.db.config import DB_NAME, get_conn
from baco.server.db.ingesta import (
    ResumenIngesta,
    discourse_base_url,
    normalizar_articulo,
    parsear_fecha,
    upsert_articulos,
)
from baco.server.services.embeddings import embedding_titulo, embedding_texto

DISCOURSE_API_KEY = os.getenv("DISCOURSE_API_KEY", "")
DISCOURSE_API_USERNAME = os.getenv("DISCOURSE_API_USERNAME", "system")
BASE_URL = discourse_base_url()

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


def pedir(http: httpx.Client, ruta: str, params: dict = None) -> dict:
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


def obtener_articulos_existentes(conn) -> dict[int, datetime | None]:
    """Retorna un mapeo {id: fecha_actualizado} de todos los artículos en la base."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, actualizado FROM articulos;")
        return {row[0]: row[1] for row in cur.fetchall()}


def actualizar_embeddings_articulo(conn, art_id: int, titulo: str, texto: str) -> bool:
    """Calcula y persiste los embeddings de título y/o texto si quedaron en NULL tras la edición."""
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


def descargar_articulo(http: httpx.Client, tema_id: int, tema_parcial: dict = None) -> dict | None:
    """Descarga el detalle completo de un tema en Discourse y lo devuelve normalizado."""
    detalle = pedir(http, f"/t/{tema_id}.json")
    posts = detalle.get("post_stream", {}).get("posts", [])
    if not posts:
        return None
    primer_post = posts[0]

    tags = detalle.get("tags")
    tags_listado = (tema_parcial or {}).get("tags")
    if not (tags and isinstance(tags[0], dict)) and tags_listado and isinstance(tags_listado[0], dict):
        tags = tags_listado
    if tags is None:
        tags = tags_listado or []

    item = {
        "id": tema_id,
        "title": detalle.get("title") or (tema_parcial or {}).get("title"),
        "category_id": detalle.get("category_id", (tema_parcial or {}).get("category_id")),
        "slug": detalle.get("slug") or (tema_parcial or {}).get("slug"),
        "tags": tags,
        "raw": primer_post.get("raw"),
        "cooked": primer_post.get("cooked"),
        "updated_at": primer_post.get("updated_at") or detalle.get("bumped_at"),
    }
    return normalizar_articulo(item, base_url=BASE_URL)


def sincronizar_articulos_editados(max_paginas: int = 3) -> int:
    print(f"=== Sincronización de Artículos Editados: Finnegans API -> {DB_NAME} ===")
    conn = get_conn()
    resumen = ResumenIngesta()
    errores: list[tuple[int, str]] = []
    editados_procesados: set[int] = set()
    eliminados_procesados: set[int] = set()

    try:
        articulos_existentes = obtener_articulos_existentes(conn)
        print(f"1. Artículos existentes en base de datos: {len(articulos_existentes)}")
        print(f"2. Auditando stream de actividad reciente en {BASE_URL} (/posts.json, máx {max_paginas} páginas)...")

        ultimo_post_id = None
        with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=30) as http:
            for num_pagina in range(1, max_paginas + 1):
                params = {"before": ultimo_post_id} if ultimo_post_id else None
                datos = pedir(http, "/posts.json", params=params)
                posts = datos.get("latest_posts", [])
                if not posts:
                    break

                for post in posts:
                    ultimo_post_id = post.get("id")

                    # Solo nos interesan los posts principales (artículos)
                    if post.get("post_number") != 1:
                        continue

                    tema_id = post.get("topic_id")
                    if not tema_id or tema_id in editados_procesados or tema_id in eliminados_procesados:
                        continue

                    # 1. Caso: Artículo eliminado o despublicado en Discourse
                    es_eliminado = bool(post.get("deleted_at")) or not post.get("visible", True) or bool(post.get("user_deleted"))
                    if es_eliminado:
                        if tema_id in articulos_existentes:
                            try:
                                with conn.cursor() as cur:
                                    cur.execute("DELETE FROM articulos WHERE id = %s;", (tema_id,))
                                conn.commit()
                                eliminados_procesados.add(tema_id)
                                articulos_existentes.pop(tema_id, None)
                                titulo = post.get("topic_title") or f"ID {tema_id}"
                                print(f"   🗑️  [ELIMINADO] ID {tema_id}: {titulo[:60]} borrado físicamente de PostgreSQL.")
                            except Exception as e:
                                conn.rollback()
                                errores.append((tema_id, f"Error al eliminar: {e}"))
                                print(f"      ⚠️ Error al eliminar tema {tema_id}: {e}")
                        continue

                    # 2. Caso: Artículo modificado
                    fecha_post = parsear_fecha(post.get("updated_at") or post.get("created_at"))
                    fecha_db = articulos_existentes.get(tema_id)

                    # Si el artículo ya existe en la base y fue modificado posteriormente en Discourse:
                    if tema_id in articulos_existentes and fecha_db is not None and fecha_post is not None:
                        if fecha_post > fecha_db:
                            editados_procesados.add(tema_id)
                            try:
                                tema_info = {
                                    "title": post.get("topic_title"),
                                    "slug": post.get("topic_slug"),
                                    "category_id": post.get("category_id"),
                                }
                                articulo = descargar_articulo(http, tema_id, tema_info)
                                if articulo is None:
                                    continue

                                parcial = upsert_articulos(conn, [articulo])
                                conn.commit()
                                resumen.sumar(parcial)
                                articulos_existentes[tema_id] = articulo["actualizado"]

                                if parcial.actualizados:
                                    print(f"   ✏️  [EDITADO] ID {tema_id}: {articulo['titulo'][:60]}")
                                    actualizar_embeddings_articulo(conn, tema_id, articulo["titulo"], articulo["texto"])
                                elif parcial.insertados:
                                    print(f"   🆕 [INGESTADO] ID {tema_id}: {articulo['titulo'][:60]}")
                                    actualizar_embeddings_articulo(conn, tema_id, articulo["titulo"], articulo["texto"])
                            except ErrorAPIDiscourse:
                                conn.rollback()
                                raise
                            except Exception as e:
                                conn.rollback()
                                errores.append((tema_id, str(e)))
                                print(f"      ⚠️ Error al procesar artículo editado {tema_id}: {e}")
                            finally:
                                time.sleep(PAUSA_ENTRE_REQUESTS)

        print("\n=== RESUMEN DE EDICIONES Y BORRADOS SINCRONIZADOS ===")
        print(f"   Artículos editados actualizados: {len(editados_procesados)}")
        print(f"   Artículos eliminados purgados:   {len(eliminados_procesados)}")
        print(f"   Detalle de ingesta: {resumen}")
        if len(editados_procesados) == 0 and len(eliminados_procesados) == 0:
            print("✨ No se detectaron ediciones ni eliminaciones pendientes. Todos los artículos coinciden con Discourse.")

        if errores:
            print(f"⚠️ {len(errores)} artículos no se pudieron procesar: {[i for i, _ in errores][:50]}")
            return 1
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sincroniza artículos editados de Discourse y actualiza embeddings.")
    parser.add_argument("--paginas", type=int, default=3, help="Cantidad de páginas de /posts.json a revisar (50 posts por página).")
    args = parser.parse_args()

    try:
        sys.exit(sincronizar_articulos_editados(max_paginas=args.paginas))
    except ErrorAPIDiscourse as e:
        print(f"❌ {e}")
        sys.exit(2)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ Error inesperado: {e}")
        sys.exit(3)
