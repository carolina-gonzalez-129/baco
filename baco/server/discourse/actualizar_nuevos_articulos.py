"""
Pipeline de sincronización para baco_db desde la API de Finnegans (Discourse).

Modos:
  - Incremental (por defecto): descarga ÚNICAMENTE los artículos nuevos. Recorre /latest.json
    ordenado por creación y corta cuando encuentra MAX_CONSECUTIVOS_EXISTENTES artículos seguidos
    que ya están en la base.
  - Completo (--completo): recorre TODOS los temas y vuelve a descargar cada uno. Detecta
    artículos EDITADOS (Discourse no "bumpea" un tema al editar el primer post, así que no hay
    otra forma confiable de detectarlos) y reporta los que están en la base pero ya no en Discourse.
    Recomendado: correrlo una vez por semana.

En ambos modos la escritura pasa por baco.server.db.ingesta.upsert_articulos, que actualiza
todos los campos, invalida embeddings si cambió el contenido y sincroniza los tags.

Ubicación: baco/server/discourse/actualizar_nuevos_articulos.py
Uso:
    python -m baco.server.discourse.actualizar_nuevos_articulos            # incremental
    python -m baco.server.discourse.actualizar_nuevos_articulos --completo # reconciliación total
"""

import argparse
import sys

# Asegurar codificación utf-8 en terminal de Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

from baco.server.db.config import DB_NAME, get_conn
from baco.server.db.ingesta import (
    ResumenIngesta,
    discourse_base_url,
    normalizar_articulo,
    upsert_articulos,
)

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
MAX_CONSECUTIVOS_EXISTENTES = 15
MAX_INTENTOS = 5


class ErrorAPIDiscourse(RuntimeError):
    pass


def pedir(http: httpx.Client, ruta: str, params: dict = None) -> dict:
    """GET con reintentos. Si se agotan, LANZA excepción (antes devolvía {} y el pipeline
    lo interpretaba como 'no hay más temas', terminando 'con éxito' sin sincronizar)."""
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


def obtener_ids_existentes(conn) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM articulos;")
        return set(row[0] for row in cur.fetchall())


def listar_temas(http: httpx.Client):
    """Itera todos los temas públicos de /latest.json ordenados por fecha de creación."""
    pagina = 0
    while True:
        datos = pedir(http, "/latest.json", params={"page": pagina, "order": "created"})
        topic_list = datos.get("topic_list", {})
        temas = topic_list.get("topics", [])
        if not temas:
            return
        for tema in temas:
            # Ignorar mensajes privados o temas ocultos
            if not tema.get("visible", True) or tema.get("archetype") == "private_message":
                continue
            if tema.get("id"):
                yield tema
        if not topic_list.get("more_topics_url"):
            return
        pagina += 1


def descargar_articulo(http: httpx.Client, tema: dict) -> dict | None:
    """Descarga el detalle del tema y lo devuelve normalizado para la ingesta."""
    tema_id = tema["id"]
    detalle = pedir(http, f"/t/{tema_id}.json")
    posts = detalle.get("post_stream", {}).get("posts", [])
    if not posts:
        return None
    primer_post = posts[0]

    # Según la versión de Discourse, los tags vienen como dicts (con id) o como strings.
    # Preferimos la fuente que traiga dicts, para no depender de IDs sintéticos.
    tags = detalle.get("tags")
    tags_listado = tema.get("tags")
    if not (tags and isinstance(tags[0], dict)) and tags_listado and isinstance(tags_listado[0], dict):
        tags = tags_listado
    if tags is None:
        tags = tags_listado or []

    item = {
        "id": tema_id,
        "title": detalle.get("title") or tema.get("title"),
        "category_id": detalle.get("category_id", tema.get("category_id")),
        "slug": detalle.get("slug") or tema.get("slug"),
        "tags": tags,
        "raw": primer_post.get("raw"),
        "cooked": primer_post.get("cooked"),
        "updated_at": primer_post.get("updated_at") or tema.get("bumped_at"),
    }
    return normalizar_articulo(item, base_url=BASE_URL)


def sincronizar_articulos(completo: bool = False) -> int:
    modo = "COMPLETA" if completo else "Incremental"
    print(f"=== Sincronización {modo}: Finnegans API -> {DB_NAME} ===")

    conn = get_conn()
    resumen = ResumenIngesta()
    errores: list[tuple[int, str]] = []
    vistos: set[int] = set()

    try:
        ids_existentes = obtener_ids_existentes(conn)
        print(f"1. Artículos existentes actualmente en baco_db: {len(ids_existentes)}")
        print(f"2. Consultando artículos en {BASE_URL}...")

        consecutivos_existentes = 0
        with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=30) as http:
            for tema in listar_temas(http):
                tema_id = tema["id"]
                vistos.add(tema_id)

                if tema_id in ids_existentes and not completo:
                    consecutivos_existentes += 1
                    # Si encontramos varios seguidos que ya existen, ya llegamos al punto donde estábamos al día
                    if consecutivos_existentes >= MAX_CONSECUTIVOS_EXISTENTES:
                        print(f"   Alcanzado el historial existente ({consecutivos_existentes} artículos consecutivos ya en la base).")
                        break
                    continue
                consecutivos_existentes = 0

                try:
                    articulo = descargar_articulo(http, tema)
                    if articulo is None:
                        continue
                    parcial = upsert_articulos(conn, [articulo])
                    conn.commit()
                    resumen.sumar(parcial)
                    ids_existentes.add(tema_id)

                    if parcial.insertados:
                        print(f"   🆕 [NUEVO] ID {tema_id}: {articulo['titulo'][:60]}")
                    elif parcial.actualizados:
                        print(f"   ✏️  [ACTUALIZADO] ID {tema_id}: {articulo['titulo'][:60]}")
                except ErrorAPIDiscourse:
                    conn.rollback()
                    raise
                except Exception as e:
                    conn.rollback()
                    errores.append((tema_id, str(e)))
                    print(f"      ⚠️ Error al procesar tema {tema_id}: {e}")
                finally:
                    time.sleep(PAUSA_ENTRE_REQUESTS)

        print("\n=== RESUMEN DE LA SINCRONIZACIÓN ===")
        print(f"   {resumen}")
        if resumen.insertados == 0 and resumen.actualizados == 0:
            print(f"✨ No hubo cambios. Tu base '{DB_NAME}' ya estaba al día.")

        if completo:
            huerfanos = sorted(ids_existentes - vistos)
            if huerfanos:
                # No se borran automáticamente: la decisión queda en manos de una persona
                print(f"⚠️ {len(huerfanos)} artículos están en la base pero ya no en Discourse "
                      f"(borrados u ocultos). IDs: {huerfanos[:50]}{' ...' if len(huerfanos) > 50 else ''}")

        if errores:
            print(f"⚠️ {len(errores)} temas no se pudieron procesar: {[i for i, _ in errores][:50]}")
            return 1
        return 0

    finally:
        conn.close()


# Alias por compatibilidad con el nombre anterior
def sincronizar_nuevos_articulos():
    return sincronizar_articulos(completo=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sincroniza artículos de Discourse con baco_db.")
    parser.add_argument("--completo", action="store_true",
                        help="Recorre y re-descarga todos los temas (detecta ediciones y borrados).")
    args = parser.parse_args()
    try:
        sys.exit(sincronizar_articulos(completo=args.completo))
    except ErrorAPIDiscourse as e:
        print(f"❌ {e}")
        sys.exit(2)
    except Exception as e:
        # Errores inesperados (ej. DB caída): código >= 2 para que el .bat aborte
        import traceback
        traceback.print_exc()
        print(f"❌ Error inesperado en la sincronización: {e}")
        sys.exit(3)
