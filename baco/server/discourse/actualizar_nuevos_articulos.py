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
import json
import os
from pathlib import Path
import sys
import time

# Asegurar codificación utf-8 en terminal de Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx
from datetime import datetime
from typing import Any
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from baco.server.db.config import DB_NAME, get_conn
from baco.server.db.ingesta import (
    ResumenIngesta,
    discourse_base_url,
    normalizar_articulo,
    parsear_fecha,
    upsert_articulos,
)
from baco.server.services.embeddings import embedding_titulo, embedding_texto

from baco.server.discourse.common import (
    ErrorAPIDiscourse,
    HEADERS,
    MAX_INTENTOS,
    PAUSA_ENTRE_REQUESTS,
    RecursoNoDisponible,
    actualizar_embeddings_articulo,
    descargar_articulo,
    pedir,
    validar_credenciales_discourse,
)

DISCOURSE_API_KEY = os.getenv("DISCOURSE_API_KEY", "")
DISCOURSE_API_USERNAME = os.getenv("DISCOURSE_API_USERNAME", "system")

MAX_CONSECUTIVOS_EXISTENTES = 15
MAX_HUERFANOS_PERMITIDOS = 50


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


def respaldar_articulos_purgados(conn, ids: list[int]) -> Path:
    """Exporta los artículos que van a ser purgados a un archivo JSON de respaldo."""
    backup_dir = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data")) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"articulos_purgados_{timestamp}.json"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, titulo, categoria_id, url, texto, actualizado FROM articulos WHERE id = ANY(%s);",
            (ids,)
        )
        filas = cur.fetchall()

    articulos_backup = [
        {
            "id": r[0],
            "titulo": r[1],
            "categoria_id": r[2],
            "url": r[3],
            "texto": r[4],
            "actualizado": r[5].isoformat() if r[5] else None,
        }
        for r in filas
    ]
    backup_file.write_text(json.dumps(articulos_backup, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_file


def confirmar_huerfano(http: httpx.Client, tema_id: int) -> bool:
    """Consulta directamente /t/{id}.json para verificar si el tema realmente no existe.

    Retorna True solo si Discourse responde 404/410 (RecursoNoDisponible) o si el tema
    está explícitamente borrado/despublicado.
    Retorna False si el tema sigue activo (por ejemplo, en categoría privada o paginación no alcanzada).
    """
    try:
        detalle = pedir(http, f"/t/{tema_id}.json")
        posts = detalle.get("post_stream", {}).get("posts", [])
        if not posts:
            return True
        primer_post = posts[0]
        es_borrado = bool(primer_post.get("deleted_at")) or not primer_post.get("visible", True) or bool(primer_post.get("user_deleted"))
        return es_borrado
    except RecursoNoDisponible:
        return True
    except Exception as e:
        print(f"      ⚠️ No se pudo confirmar estado del tema {tema_id} en Discourse: {e}")
        return False


def sincronizar_articulos(completo: bool = False, purgar: bool = False, forzar_purga: bool = False) -> int:
    validar_credenciales_discourse()
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

            if completo:
                candidatos_huerfanos = sorted(ids_existentes - vistos)
                if candidatos_huerfanos:
                    print(f"⚠️ {len(candidatos_huerfanos)} artículos están en la base pero ya no en Discourse "
                          f"(borrados u ocultos). IDs: {candidatos_huerfanos[:50]}{' ...' if len(candidatos_huerfanos) > 50 else ''}")
                    if purgar:
                        if errores:
                            print(f"⛔ Se canceló la purga automática porque hubo {len(errores)} temas con error de red/API. "
                                  f"Se debe garantizar 0 errores para evitar borrar artículos válidos.")
                        elif len(candidatos_huerfanos) > MAX_HUERFANOS_PERMITIDOS and not forzar_purga:
                            print(f"⛔ [CIRCUIT BREAKER] Se detectaron {len(candidatos_huerfanos)} artículos huérfanos potenciales, lo cual supera el límite de seguridad de {MAX_HUERFANOS_PERMITIDOS}. "
                                  f"La purga fue cancelada para prevenir pérdida masiva accidental de datos. "
                                  f"Use --forzar-purga si realmente desea verificarlos y eliminarlos.")
                        else:
                            print(f"🔍 [AUDITORÍA DE PURGA] Verificando individualmente {len(candidatos_huerfanos)} candidatos con /t/{{id}}.json...")
                            huerfanos_confirmados: list[int] = []
                            for hid in candidatos_huerfanos:
                                if confirmar_huerfano(http, hid):
                                    huerfanos_confirmados.append(hid)
                                else:
                                    print(f"   🛡️ ID {hid} no apareció en /latest.json pero sigue activo en Discourse. Conservado en PostgreSQL.")
                                time.sleep(PAUSA_ENTRE_REQUESTS)

                            if not huerfanos_confirmados:
                                print("✨ No se confirmaron artículos huérfanos reales. Ningún artículo fue eliminado de PostgreSQL.")
                            else:
                                backup_file = respaldar_articulos_purgados(conn, huerfanos_confirmados)
                                print(f"💾 [BACKUP] Respaldo de {len(huerfanos_confirmados)} artículos guardado en: {backup_file}")
                                print(f"🗑️ [PURGA] Eliminando físicamente {len(huerfanos_confirmados)} artículos confirmados de PostgreSQL...")
                                with conn.cursor() as cur:
                                    cur.execute("DELETE FROM articulos WHERE id = ANY(%s);", (huerfanos_confirmados,))
                                conn.commit()
                                print(f"   ✓ {len(huerfanos_confirmados)} artículos huérfanos eliminados exitosamente de PostgreSQL.")
                    else:
                        print(f"ℹ️ Modo sin purga: los {len(candidatos_huerfanos)} artículos no coincidentes se conservan intactos en la base. IDs: {candidatos_huerfanos[:30]}")


        print("\n=== RESUMEN DE LA SINCRONIZACIÓN ===")
        print(f"   {resumen}")
        if resumen.insertados == 0 and resumen.actualizados == 0:
            print(f"✨ No hubo cambios. Tu base '{DB_NAME}' ya estaba al día.")

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
                        help="Elimina físicamente de la base los artículos huérfanos confirmados que ya no existen en Discourse.")
    parser.add_argument("--forzar-purga", action="store_true",
                        help="Omite el límite de seguridad del circuit breaker para purgar huérfanos confirmados.")
    args = parser.parse_args()
    try:
        sys.exit(sincronizar_articulos(completo=args.completo, purgar=args.purgar, forzar_purga=args.forzar_purga))
    except ErrorAPIDiscourse as e:
        print(f"❌ {e}")
        sys.exit(2)
    except Exception as e:
        # Errores inesperados (ej. DB caída): código >= 2 para que el .bat aborte
        import traceback
        traceback.print_exc()
        print(f"❌ Error inesperado en la sincronización: {e}")
        sys.exit(3)

