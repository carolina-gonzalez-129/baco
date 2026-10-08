import os
import sys
import json
from pathlib import Path
from baco.server.db.config import DB_NAME, get_conn
from baco.server.db.ingesta import normalizar_articulo, upsert_articulos

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUTA_JSON = Path(os.getenv("RUTA_ARTICULOS_JSON", PROJECT_ROOT / "data" / "articulos.json"))


DDL_SCHEMA = r"""
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE OR REPLACE FUNCTION normalizar_texto(t text)
RETURNS text AS $$
    SELECT NULLIF(
        trim(
            regexp_replace(
                regexp_replace(
                    lower(public.unaccent('public.unaccent', coalesce(t, ''))),
                    '[^\\w\\s]|_', ' ', 'g'
                ),
                '\\s+', ' ', 'g'
            )
        ),
        ''
    );
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

CREATE TABLE IF NOT EXISTS categorias (
    id INT PRIMARY KEY,
    nombre VARCHAR(150)
);

CREATE OR REPLACE FUNCTION public.titulo_base(t text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
SELECT btrim(regexp_replace(
        regexp_replace(t,
                       '\m(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\M|\d+',
                       '', 'g'),
        '\s+', ' ', 'g'));
$$;

CREATE OR REPLACE FUNCTION public.limpiar_headers(t text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
SELECT CASE
           WHEN t IS NULL OR t = '' THEN t
           ELSE btrim(
                   regexp_replace(
                           regexp_replace(
                                   regexp_replace(
                                           regexp_replace(
                                                   regexp_replace(t, '(?n)^\s*#{1,6}\s+.*$', '', 'g'),
                                                   '(?n)^\s*(\*\*)?(consulta|respuesta|pasos a seguir|requiere app\s*builder|antes de empezar|modo de uso|¿?para qu[eé] sirve\??)(\*\*)?\s*:?\s*$',
                                                   '', 'gi'
                                           ),
                                           '(?n)^\s*(\*\s*\*\s*\*|-{3,}|_{3,})\s*$', '', 'g'
                                   ),
                                   '!?\[image[^\]]*\]\([^\)]+\)', '', 'gi'
                           ),
                           '\n\s*\n+', E'\n\n', 'g'
                   )
                )
           END;
$$;

CREATE TABLE IF NOT EXISTS articulos (
    id INT PRIMARY KEY,
    titulo VARCHAR(500) NOT NULL,
    categoria_id INT,
    url TEXT NOT NULL,
    texto TEXT NOT NULL,
    titulo_normalizado text GENERATED ALWAYS AS (normalizar_texto(titulo)) STORED,
    texto_normalizado text GENERATED ALWAYS AS (normalizar_texto(texto)) STORED,
    base_titulo text GENERATED ALWAYS AS (titulo_base(normalizar_texto(titulo))) STORED,
    texto_sin_headers text GENERATED ALWAYS AS (limpiar_headers(texto)) STORED,
    hash_titulo text GENERATED ALWAYS AS (
        CASE 
            WHEN normalizar_texto(titulo) IS NOT NULL 
            THEN md5(normalizar_texto(titulo)) 
        END
    ) STORED,
    hash_texto text GENERATED ALWAYS AS (
        CASE 
            WHEN normalizar_texto(texto) IS NOT NULL 
            THEN md5(normalizar_texto(texto)) 
        END
    ) STORED,
    hash_texto_sin_headers text GENERATED ALWAYS AS (
        CASE
            WHEN ((texto IS NOT NULL) AND (btrim(texto) <> '')) 
            THEN md5(normalizar_texto(limpiar_headers(texto)))
        END
    ) STORED,
    embedding_titulo vector(384),
    embedding_texto vector(768),
    actualizado TIMESTAMPTZ,
    creado_en TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_categoria FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS articulo_tags (
    articulo_id INT REFERENCES articulos(id) ON DELETE CASCADE,
    tag_id INT REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (articulo_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_articulos_caperotegoria ON articulos(categoria_id);
CREATE INDEX IF NOT EXISTS idx_articulos_actualizado ON articulos(actualizado);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_titulo ON articulos(hash_titulo);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto ON articulos(hash_texto);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto_sin_headers ON articulos(hash_texto_sin_headers);
CREATE INDEX IF NOT EXISTS idx_articulos_base_titulo ON articulos(base_titulo);
CREATE INDEX IF NOT EXISTS idx_articulos_titulo_trgm ON articulos USING gin (titulo_normalizado gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_articulos_embedding_texto ON articulos USING hnsw (embedding_texto vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_articulos_embedding_titulo ON articulos USING hnsw (embedding_titulo vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_tags_slug ON tags(slug);
"""

def asegurar_base_de_datos():
    print(f" Verificando existencia de la base de datos '{DB_NAME}'...")
    with get_conn(dbname="postgres", autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (DB_NAME,))
            if not cur.fetchone():
                print(f"  Creando base de datos '{DB_NAME}'...")
                cur.execute(f'CREATE DATABASE "{DB_NAME}";')
                print(f" ¡Base de datos '{DB_NAME}' creada con éxito!")
            else:
                print(f"  La base de datos '{DB_NAME}' ya existe.")

def asegurar_tablas():
    print(f" Creando estructura de tablas en '{DB_NAME}'...")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(DDL_SCHEMA)
        conn.commit()
    print(" ¡Tablas e índices listos!")

def leer_articulos_json(ruta: Path = RUTA_JSON) -> list[dict]:
    """Lee el JSON de artículos y los devuelve normalizados (ver baco.server.db.ingesta)."""
    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [a for a in (normalizar_articulo(item) for item in data) if a]


def importar_articulos(dry_run: bool = False):
    if not RUTA_JSON.exists():
        print(f" No se encontró el archivo: {RUTA_JSON}")
        return

    print(f" Leyendo archivo JSON desde {RUTA_JSON.name}...")
    articulos = leer_articulos_json(RUTA_JSON)
    print(f" Cargados {len(articulos)} artículos en memoria. Preparando inserción...")

    with get_conn() as conn:
        resumen = upsert_articulos(conn, articulos)
        if dry_run:
            conn.rollback()
            print(f"\n [DRY-RUN] No se escribió nada. Resultado que tendría: {resumen}")
            return
        conn.commit()

    print(f" Resultado: {resumen}")
    if resumen.omitidos_por_antiguedad:
        print(f"  ⚠️ {resumen.omitidos_por_antiguedad} artículos del JSON son más viejos que los de la base "
              f"y no se pisaron (ej. IDs {resumen.ids_omitidos[:10]}).")
    print(f"\n ¡Proceso completado con éxito! Todos los artículos están guardados en '{DB_NAME}'.")

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if not dry_run:
        asegurar_base_de_datos()
        asegurar_tablas()
    importar_articulos(dry_run=dry_run)
