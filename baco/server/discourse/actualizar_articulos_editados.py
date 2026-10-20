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
    parsear_fecha,
    upsert_articulos,
)
from baco.server.services.embeddings import embedding_titulo, embedding_texto

from baco.server.discourse.common import (
    ErrorAPIDiscourse,
    HEADERS,
    MAX_INTENTOS,
    PAUSA_ENTRE_REQUESTS,
    actualizar_embeddings_articulo,
    descargar_articulo,
    pedir,
    validar_credenciales_discourse,
)

DISCOURSE_API_KEY = os.getenv("DISCOURSE_API_KEY", "")
DISCOURSE_API_USERNAME = os.getenv("DISCOURSE_API_USERNAME", "system")


def __getattr__(name: str) -> str:
    if name == "BASE_URL":
        return discourse_base_url()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def obtener_articulos_existentes(conn) -> dict[int, datetime | None]:
    """Retorna un mapeo {id: fecha_actualizado} de todos los artículos en la base."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, actualizado FROM articulos;")
        return {row[0]: row[1] for row in cur.fetchall()}


def sincronizar_articulos_editados(max_paginas: int = 3) -> int:
    validar_credenciales_discourse()
    print(f"=== Sincronización de Artículos Editados: Finnegans API -> {DB_NAME} ===")
    conn = get_conn()
    resumen = ResumenIngesta()
    errores: list[tuple[int, str]] = []
    editados_procesados: set[int] = set()
    eliminados_procesados: set[int] = set()

    base_url = discourse_base_url()
    try:
        articulos_existentes = obtener_articulos_existentes(conn)
        print(f"1. Artículos existentes en base de datos: {len(articulos_existentes)}")

        with httpx.Client(base_url=base_url, headers=HEADERS, timeout=30) as http:
            # Fase A: Auditar actividad reciente por topics en /latest.json (actividad/bumped)
            print(f"2. Auditando actividad reciente en {base_url} (/latest.json, máx {max_paginas} páginas)...")
            for num_pagina in range(max_paginas):
                try:
                    datos = pedir(http, "/latest.json", params={"page": num_pagina})
                    topics = datos.get("topic_list", {}).get("topics", [])
                    if not topics:
                        break

                    for topic in topics:
                        tema_id = topic.get("id")
                        if not tema_id or tema_id in editados_procesados or tema_id in eliminados_procesados:
                            continue

                        # Si el tema fue marcado como no visible o borrado
                        if not topic.get("visible", True) or bool(topic.get("deleted_at")):
                            if tema_id in articulos_existentes:
                                eliminados_procesados.add(tema_id)
                                titulo = topic.get("title") or f"ID {tema_id}"
                                print(f"   ⚠️  [DESPUBLICADO EN DISCOURSE] ID {tema_id}: {titulo[:60]} despublicado/eliminado en Discourse. Se preserva en PostgreSQL por histórico.")
                            continue

                        # Fecha de actividad del tema
                        fecha_act = parsear_fecha(topic.get("bumped_at") or topic.get("last_posted_at") or topic.get("updated_at") or topic.get("created_at"))
                        fecha_db = articulos_existentes.get(tema_id)

                        if tema_id in articulos_existentes and fecha_db is not None and fecha_act is not None:
                            if fecha_act > fecha_db:
                                editados_procesados.add(tema_id)
                                try:
                                    articulo = descargar_articulo(http, tema_id, topic)
                                    if articulo is None:
                                        continue

                                    parcial = upsert_articulos(conn, [articulo])
                                    conn.commit()
                                    resumen.sumar(parcial)
                                    articulos_existentes[tema_id] = articulo["actualizado"]

                                    if parcial.actualizados:
                                        print(f"   ✏️  [EDITADO/ACTUALIZADO] ID {tema_id}: {articulo['titulo'][:60]}")
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
                except ErrorAPIDiscourse:
                    raise
                except Exception as e:
                    print(f"      ⚠️ Error al auditar página {num_pagina} de /latest.json: {e}")
                    break

            # Fase B: Auditar stream de posts recientes en /posts.json
            print(f"3. Auditando stream de actividad reciente en {base_url} (/posts.json, máx {max_paginas} páginas)...")
            ultimo_post_id = None
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

                    # 1. Caso: Artículo eliminado o despublicado en Discourse -> auditar y preservar (sin DELETE físico)
                    es_eliminado = bool(post.get("deleted_at")) or not post.get("visible", True) or bool(post.get("user_deleted"))
                    if es_eliminado:
                        if tema_id in articulos_existentes:
                            eliminados_procesados.add(tema_id)
                            titulo = post.get("topic_title") or f"ID {tema_id}"
                            print(f"   ⚠️  [DESPUBLICADO EN DISCOURSE] ID {tema_id}: {titulo[:60]} despublicado/eliminado en Discourse. Se preserva en PostgreSQL por histórico.")
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

        print("\n=== RESUMEN DE EDICIONES Y AUDITORÍA DE BORRADOS ===")
        print(f"   Artículos editados actualizados: {len(editados_procesados)}")
        print(f"   Artículos despublicados auditados (preservados): {len(eliminados_procesados)}")
        print(f"   Detalle de ingesta: {resumen}")
        if len(editados_procesados) == 0 and len(eliminados_procesados) == 0:
            print("✨ No se detectaron ediciones pendientes. Todos los artículos coinciden con Discourse.")

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
