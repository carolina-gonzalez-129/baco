"""Descarga la base de conocimiento de Discourse a data/articulos.json.

SOLO DEBE HACERSE SI QUEDO DESINCRONIZADA, es para que cuando el server se inicia no tenga que pedir tooodas las entradas
de la base de conocimiento de nuevo
Idealmente habria q volver a ejecutar esto solo cuando estemos x dar la demo, xq son muchas entradas

"""
from pathlib import Path
import json
import os
import time


import httpx
from bs4 import BeautifulSoup

from baco.server.discourse.client import BASE, headers

# Carpeta data en la raíz del proyecto
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
SALIDA = DATA_DIR / "articulos.json"

PAUSA = 0.2
GUARDAR_CADA = 50


CATEGORIA_ID = None


def pedir(http, ruta, params=None):
    """GET con reintentos para 429, 5xx y errores de conexión."""
    for intento in range(5):
        try:
            r = http.get(ruta, params=params)
            if r.status_code == 429:
                espera = int(r.headers.get("Retry-After", 10))
                print(f"Rate limit (429). Esperando {espera}s...")
                time.sleep(espera)
                continue
            if r.status_code in (502, 503, 504):
                time.sleep(2 * (intento + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.RequestError, httpx.HTTPStatusError):
            if intento == 4:
                raise
            time.sleep(2 * (intento + 1))
    raise RuntimeError(f"Demasiados reintentos en {ruta}")


def listar_temas(http):

    pagina = 0
    endpoint = f"/c/{CATEGORIA_ID}/l/latest.json" if CATEGORIA_ID else "/latest.json"

    while True:
        datos = pedir(http, endpoint, params={"page": pagina})
        topic_list = datos.get("topic_list", {})
        temas = topic_list.get("topics", [])
        if not temas:
            return

        yield from temas


        if not topic_list.get("more_topics_url"):
            return
        pagina += 1


def limpiar_texto(cooked_html: str) -> str:
    """Extrae texto preservando saltos de línea para no aplanar títulos y párrafos."""
    soup = BeautifulSoup(cooked_html, "html.parser")
    lineas = [l.strip() for l in soup.get_text("\n").splitlines()]
    return "\n".join(l for l in lineas if l)


def guardar(articulos):
    """Escribe a un archivo temp y renombra para evitar archivos corruptos."""
    tmp = SALIDA.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(list(articulos.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(SALIDA)


def main():
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else None
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    articulos = {}
    if SALIDA.exists():
        previos = json.loads(SALIDA.read_text(encoding="utf-8"))
        articulos = {a["id"]: a for a in previos}
        print(f"Retomando: ya hay {len(articulos)} artículos guardados.")

    nuevos = 0
    with httpx.Client(base_url=BASE, headers=headers, timeout=30) as http:
        for n, tema in enumerate(listar_temas(http), start=1):
            if limite and n > limite:
                break

            # Ignorar mensajes privados o temas ocultos
            if not tema.get("visible", True) or tema.get("archetype") == "private_message":
                continue

            tema_id = tema["id"]

            # Si ya existe y no se actualizó después de descargarlo, lo salteamos
            if tema_id in articulos:
                fecha_guardada = articulos[tema_id].get("actualizado")
                fecha_tema = tema.get("bumped_at") or tema.get("last_posted_at")
                if fecha_guardada and fecha_tema and fecha_guardada >= fecha_tema:
                    continue

            try:
                datos = pedir(http, f"/t/{tema_id}.json")
                posts = datos.get("post_stream", {}).get("posts", [])
                if not posts:
                    continue

                post = posts[0]
                texto = post.get("raw") or limpiar_texto(post.get("cooked", ""))

                articulos[tema_id] = {
                    "id": tema_id,
                    "titulo": tema.get("title", ""),
                    "categoria_id": tema.get("category_id"),
                    "tags": tema.get("tags", []),
                    "url": f"{BASE}/t/{tema.get('slug', 'topic')}/{tema_id}",
                    "texto": texto,
                    "actualizado": post.get("updated_at") or tema.get("bumped_at"),
                }
                nuevos += 1
                print(f"[{n}] {tema['title'][:70]}")

                if nuevos % GUARDAR_CADA == 0:
                    guardar(articulos)
                time.sleep(PAUSA)

            except Exception as e:
                print(f"Error en tema {tema_id}: {e}", file=sys.stderr)
                continue

    guardar(articulos)
    print(f"\n✅ ¡Listo! {len(articulos)} artículos guardados en {SALIDA}")


if __name__ == "__main__":
    main()