-- 005_normalizacion_y_hashes_automaticos.sql
-- Migración para automatizar la normalización de texto y hashes MD5 en PostgreSQL (Estrategia A)

BEGIN;

-- 1. Habilitar extensiones necesarias
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Crear función canónica e IMMUTABLE de normalización en PostgreSQL
-- Replica exactamente: lower(), strip diacríticos (unaccent), remover puntuación/símbolos y colapsar espacios.
CREATE OR REPLACE FUNCTION normalizar_texto(t text)
RETURNS text AS $$
    SELECT NULLIF(
        trim(
            regexp_replace(
                regexp_replace(
                    lower(public.unaccent('public.unaccent', coalesce(t, ''))),
                    '[^\w\s]|_', ' ', 'g'
                ),
                '\s+', ' ', 'g'
            )
        ),
        ''
    );
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

-- 3. Eliminar índices previos que dependen de las columnas a transformar
DROP INDEX IF EXISTS idx_articulos_titulo_trgm;
DROP INDEX IF EXISTS idx_articulos_hash_titulo;
DROP INDEX IF EXISTS idx_articulos_hash_texto;
DROP INDEX IF EXISTS idx_articulos_titulo_norm;

-- 4. Reemplazar columnas por columnas generadas STORED
ALTER TABLE articulos 
    DROP COLUMN IF EXISTS hash_titulo,
    DROP COLUMN IF EXISTS hash_texto,
    DROP COLUMN IF EXISTS titulo_normalizado,
    DROP COLUMN IF EXISTS texto_normalizado;

ALTER TABLE articulos
    ADD COLUMN titulo_normalizado text GENERATED ALWAYS AS (normalizar_texto(titulo)) STORED,
    ADD COLUMN texto_normalizado text GENERATED ALWAYS AS (normalizar_texto(texto)) STORED,
    ADD COLUMN hash_titulo text GENERATED ALWAYS AS (
        CASE 
            WHEN normalizar_texto(titulo) IS NOT NULL 
            THEN md5(normalizar_texto(titulo)) 

        END
    ) STORED,
    ADD COLUMN hash_texto text GENERATED ALWAYS AS (
        CASE 
            WHEN normalizar_texto(texto) IS NOT NULL 
            THEN md5(normalizar_texto(texto)) 

        END
    ) STORED;

-- 5. Recrear índices B-Tree y GIN sobre las columnas generadas
CREATE INDEX IF NOT EXISTS idx_articulos_hash_titulo ON articulos(hash_titulo);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto ON articulos(hash_texto);
CREATE INDEX IF NOT EXISTS idx_articulos_titulo_trgm ON articulos USING gin (titulo_normalizado gin_trgm_ops);

COMMIT;
