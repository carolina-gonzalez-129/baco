"""
Pipeline de sincronización incremental para baco_db.
Descarga e inserta ÚNICAMENTE artículos nuevos de la API de Finnegans (Discourse),
evitando duplicar registros existentes en PostgreSQL.

Ubicación: baco/server/discourse/actualizar_nuevos_articulos.py
"""

import os
import sys

# Asegurar codificación utf-8 en terminal de Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import time
from pathlib import Path
import re
import unicodedata
from datetime import datetime
import httpx
from bs4 import BeautifulSoup
import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv()


def generar_slug(texto: str) -> str:
    """Genera un slug simple para tags sin depender de normalizar.py."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^\w\s-]", "", t).strip().lower().replace(" ", "-")


from baco.server.db.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, get_conn


# Configuración de API Discourse
DISCOURSE_API_KEY = os.getenv("DISCOURSE_API_KEY", "")
DISCOURSE_API_USERNAME = os.getenv("DISCOURSE_API_USERNAME", "system")
DISCOURSE_URL = os.getenv("DISCOURSE_URL", "bc-dev.finneg.com").strip()

if not DISCOURSE_URL.startswith("http"):
    BASE_URL = f"https://{DISCOURSE_URL}"
else:
    BASE_URL = DISCOURSE_URL

HEADERS = {
    "Api-Key": DISCOURSE_API_KEY,
    "Api-Username": DISCOURSE_API_USERNAME,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
}

PAUSA_ENTRE_REQUESTS = 0.3


def limpiar_texto(cooked_html: str) -> str:
    """Extrae texto plano preservando saltos de línea."""
    soup = BeautifulSoup(cooked_html, "html.parser")
    lineas = [l.strip() for l in soup.get_text("\n").splitlines()]
    return "\n".join(l for l in lineas if l)


def pedir(http: httpx.Client, ruta: str, params: dict = None) -> dict:
    """Realiza una petición GET con reintentos para rate-limits (429) y errores temporales."""
    for intento in range(5):
        try:
            r = http.get(ruta, params=params)
            if r.status_code == 429:
                espera = int(r.headers.get("Retry-After", 10))
                print(f"   Rate limit alcanzado. Esperando {espera}s...")
                time.sleep(espera)
                continue
            if r.status_code in (502, 503, 504):
                time.sleep(2 * (intento + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            if intento == 4:
                raise RuntimeError(f"Error persistente en {ruta}: {e}")
            time.sleep(2 * (intento + 1))
    return {}


def obtener_ids_existentes(conn) -> set[int]:
    """Obtiene el conjunto de todos los IDs de artículos que ya existen en baco_db."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM articulos;")
        return set(row[0] for row in cur.fetchall())


def sincronizar_nuevos_articulos():
    print(f"=== Sincronización Incremental: Finnegans API -> {DB_NAME} ===")
    
    # 1. Conectar a PostgreSQL
    conn = get_conn()
    
    try:
        ids_existentes = obtener_ids_existentes(conn)
        print(f"1. Artículos existentes actualmente en baco_db: {len(ids_existentes)}")

        # 2. Conectar a Discourse
        nuevos_insertados = 0
        pagina = 0
        consecutivos_existentes = 0
        MAX_CONSECUTIVOS_EXISTENTES = 15  # Si vemos 15 temas que ya están en la BD, terminamos

        print(f"2. Consultando nuevos artículos en {BASE_URL}...")
        
        with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=30) as http:
            while True:
                # Pedimos los últimos temas ordenados por fecha de creación (los más nuevos primero)
                endpoint = "/latest.json"
                params = {"page": pagina, "order": "created"}
                
                try:
                    datos = pedir(http, endpoint, params=params)
                except Exception as e:
                    print(f"❌ Error al consultar la página {pagina}: {e}")
                    break

                topic_list = datos.get("topic_list", {})
                temas = topic_list.get("topics", [])
                
                if not temas:
                    print("   No hay más temas para revisar.")
                    break

                for tema in temas:
                    # Ignorar mensajes privados o temas ocultos
                    if not tema.get("visible", True) or tema.get("archetype") == "private_message":
                        continue

                    tema_id = tema.get("id")
                    if not tema_id:
                        continue

                    # FILTRO CLAVE: ¿Ya existe en baco_db?
                    if tema_id in ids_existentes:
                        consecutivos_existentes += 1
                        # Si encontramos varios seguidos que ya existen, ya llegamos al punto donde estábamos al día
                        if consecutivos_existentes >= MAX_CONSECUTIVOS_EXISTENTES:
                            print(f"   Alcanzado el historial existente ({consecutivos_existentes} artículos consecutivos ya en la base).")
                            break
                        continue

                    # Si es un tema nuevo:
                    consecutivos_existentes = 0  # reiniciamos el contador de corte
                    
                    titulo = tema.get("title", "Sin título")
                    cat_id = tema.get("category_id")
                    slug = tema.get("slug", "topic")
                    url = f"{BASE_URL}/t/{slug}/{tema_id}"
                    tags_data = tema.get("tags", [])
                    
                    print(f"   🆕 [NUEVO] ID {tema_id}: {titulo[:60]}...")

                    # Descargamos el detalle del post (cuerpo del texto)
                    try:
                        detalle = pedir(http, f"/t/{tema_id}.json")
                        posts = detalle.get("post_stream", {}).get("posts", [])
                        if not posts:
                            continue

                        primer_post = posts[0]
                        texto_crudo = primer_post.get("raw") or limpiar_texto(primer_post.get("cooked", ""))
                        
                        fecha_str = primer_post.get("updated_at") or tema.get("bumped_at")
                        fecha_dt = None
                        if fecha_str:
                            try:
                                fecha_dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
                            except Exception:
                                pass

                        with conn.cursor() as cur:
                            # A. Insertar categoría si no existe
                            if cat_id:
                                cur.execute("""
                                    INSERT INTO categorias (id, nombre) 
                                    VALUES (%s, %s)
                                    ON CONFLICT (id) DO NOTHING;
                                """, (cat_id, f"Categoría {cat_id}"))

                            # B. Insertar tags si no existen
                            tags_a_vincular = []
                            for t in tags_data:
                                if isinstance(t, dict):
                                    t_id = t.get("id")
                                    t_name = t.get("name", "")
                                    t_slug = t.get("slug", "")
                                elif isinstance(t, str):
                                    # En latest.json los tags a veces vienen como strings simples
                                    t_id = None
                                    t_name = t
                                    t_slug = generar_slug(t)
                                else:
                                    continue

                                if t_name:
                                    if t_id:
                                        cur.execute("""
                                            INSERT INTO tags (id, name, slug) 
                                            VALUES (%s, %s, %s)
                                            ON CONFLICT (id) DO NOTHING;
                                        """, (t_id, t_name, t_slug))
                                        tags_a_vincular.append(t_id)
                                    else:
                                        # Si el tag viene sin ID, buscamos o insertamos con secuencia
                                        cur.execute("SELECT id FROM tags WHERE slug = %s;", (t_slug,))
                                        tag_row = cur.fetchone()
                                        if tag_row:
                                            tags_a_vincular.append(tag_row[0])

                            # C. Sincronizar contenido crudo del artículo (sin tocar hashes ni embeddings)
                            cur.execute("""
                                INSERT INTO articulos (id, titulo, categoria_id, url, texto, actualizado)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO UPDATE SET
                                    titulo = EXCLUDED.titulo,
                                    categoria_id = EXCLUDED.categoria_id,
                                    url = EXCLUDED.url,
                                    texto = EXCLUDED.texto,
                                    actualizado = EXCLUDED.actualizado;
                            """, (tema_id, titulo, cat_id, url, texto_crudo, fecha_dt))

                            # D. Vincular artículo con sus tags
                            for tag_id in tags_a_vincular:
                                cur.execute("""
                                    INSERT INTO articulo_tags (articulo_id, tag_id)
                                    VALUES (%s, %s)
                                    ON CONFLICT (articulo_id, tag_id) DO NOTHING;
                                """, (tema_id, tag_id))

                        conn.commit()
                        ids_existentes.add(tema_id)
                        nuevos_insertados += 1
                        time.sleep(PAUSA_ENTRE_REQUESTS)

                    except Exception as e:
                        print(f"      ⚠️ Error al procesar tema {tema_id}: {e}")
                        conn.rollback()
                        continue

                # Si ya alcanzamos los temas antiguos en este lote, cortamos la paginación
                if consecutivos_existentes >= MAX_CONSECUTIVOS_EXISTENTES:
                    break

                if not topic_list.get("more_topics_url"):
                    break

                pagina += 1

        print("\n=== RESUMEN DE LA SINCRONIZACIÓN ===")
        if nuevos_insertados > 0:
            print(f"✅ Se insertaron {nuevos_insertados} artículos nuevos en '{DB_NAME}'.")
        else:
            print(f"✨ No se encontraron artículos nuevos. Tu base '{DB_NAME}' ya estaba 100% al día.")

    finally:
        conn.close()


if __name__ == "__main__":
    sincronizar_nuevos_articulos()
