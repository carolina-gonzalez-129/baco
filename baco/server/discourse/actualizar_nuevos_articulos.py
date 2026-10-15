"""
Pipeline de sincronización para baco_db desde la API de Finnegans (Discourse).

Modos:
  - Incremental (por defecto): descarga ÚNICAMENTE los artículos nuevos. Recorre /latest.json
    ordenado por creación y corta cuando encuentra MAX_CONSECUTIVOS_EXISTENTES artículos seguidos
    que ya están en la base. Si un artículo es nuevo, calcula sus embeddings de inmediato.
    (Para detectar y sincronizar artículos editados, ver baco.server.discourse.actualizar_articulos_editados).
  - Completo (--completo): recorre TODOS los temas y vuelve a descargar cada uno. Reconcilia
    artículos y reporta los que están en la base pero ya no en Discourse.

En ambos modos la escritura pasa por baco.server.db.ingesta.upsert_articulos.

Ubicación: baco/server/discourse/actualizar_nuevos_articulos.py
Uso:
    python -m baco.server.discourse.actualizar_nuevos_articulos            # solo artículos nuevos
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
from datetime import datetime
from typing import Any
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
from baco.server.discourse.common import (
    ErrorAPIDiscourse,
    HEADERS,
    MAX_INTENTOS,
    PAUSA_ENTRE_REQUESTS,
    actualizar_embeddings_articulo,
    descargar_articulo,
    pedir,
)

DISCOURSE_API_KEY = os.getenv("DISCOURSE_API_KEY", "")
DISCOURSE_API_USERNAME = os.getenv("DISCOURSE_API_USERNAME", "system")

MAX_CONSECUTIVOS_EXISTENTES = 15


def __getattr__(name: str) -> str:
    if name == "BASE_URL":
        return discourse_base_url()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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


def sincronizar_articulos(completo: bool = False, purgar: bool = False) -> int:
    modo = "COMPLETA" if completo else "Incremental (Nuevos)"
    print(f"=== Sincronización {modo}: Finnegans API -> {DB_NAME} ===")

    conn = get_conn()
    resumen = ResumenIngesta()
    errores: list[tuple[int, str]] = []
    vistos: set[int] = set()

    base_url = discourse_base_url()
    try:
        ids_existentes = obtener_ids_existentes(conn)
        print(f"1. Artículos existentes actualmente en baco_db: {len(ids_existentes)}")
        print(f"2. Consultando nuevos artículos en {base_url}...")

        consecutivos_existentes = 0
        with httpx.Client(base_url=base_url, headers=HEADERS, timeout=30) as http:
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
                        actualizar_embeddings_articulo(conn, tema_id, articulo["titulo"], articulo["texto"])
                    elif parcial.actualizados:
                        print(f"   ✏️  [ACTUALIZADO] ID {tema_id}: {articulo['titulo'][:60]}")
                        actualizar_embeddings_articulo(conn, tema_id, articulo["titulo"], articulo["texto"])
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
                print(f"⚠️ {len(huerfanos)} artículos están en la base pero ya no en Discourse "
                      f"(borrados u ocultos). IDs: {huerfanos[:50]}{' ...' if len(huerfanos) > 50 else ''}")
                if purgar:
                    if errores:
                        print(f"⛔ Se canceló la purga automática porque hubo {len(errores)} temas con error de red/API. "
                              f"Se debe garantizar 0 errores para evitar borrar artículos válidos.")
                    else:
                        print(f"🗑️ [PURGA] Eliminando físicamente {len(huerfanos)} artículos huérfanos de PostgreSQL...")
                        with conn.cursor() as cur:
                            cur.execute("DELETE FROM articulos WHERE id = ANY(%s);", (huerfanos,))
                        conn.commit()
                        print(f"   ✓ {len(huerfanos)} artículos huérfanos eliminados exitosamente de PostgreSQL.")

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
    parser.add_argument("--purgar", action="store_true",
                        help="Elimina físicamente de la base los artículos huérfanos que ya no existen en Discourse.")
    args = parser.parse_args()
    try:
        sys.exit(sincronizar_articulos(completo=args.completo, purgar=args.purgar))
    except ErrorAPIDiscourse as e:
        print(f"❌ {e}")
        sys.exit(2)
    except Exception as e:
        # Errores inesperados (ej. DB caída): código >= 2 para que el .bat aborte
        import traceback
        traceback.print_exc()
        print(f"❌ Error inesperado en la sincronización: {e}")
        sys.exit(3)
