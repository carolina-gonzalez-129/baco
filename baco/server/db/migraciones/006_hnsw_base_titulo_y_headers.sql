-- 006_hnsw_base_titulo_y_headers.sql
-- Migración para formalizar funciones auxiliares, columnas generadas e índices HNSW en pgvector.

BEGIN;

-- 1. Habilitar extensiones necesarias
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Función para limpiar headers y metadatos de formato en texto de artículos
CREATE OR REPLACE FUNCTION public.limpiar_headers(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE PARALLEL SAFE
AS $function$
SELECT CASE
           WHEN t IS NULL OR t = '' THEN t
           ELSE btrim(
                   regexp_replace(
                           regexp_replace(
                                   regexp_replace(
                                           regexp_replace(
                                               -- 1. Borra headers de Markdown (#, ##, ###) como en los INSTRUCTIVOS
                                                   regexp_replace(t, '(?n)^\s*#{1,6}\s+.*$', '', 'g'),

                                               -- 2. Borra etiquetas de sección con negritas (**) o texto plano como en SOLUCIONES
                                                   '(?n)^\s*(\*\*)?(consulta|respuesta|pasos a seguir|requiere app\s*builder|antes de empezar|modo de uso|¿?para qu[eé] sirve\??)(\*\*)?\s*:?\s*$',
                                                   '', 'gi'
                                           ),

                                       -- 3. Borra divisores de sección (* * *, ---, ___)
                                           '(?n)^\s*(\*\s*\*\s*\*|-{3,}|_{3,})\s*$', '', 'g'
                                   ),

                               -- 4. Borra TODAS las imágenes de Discourse (![image](url) o [image...](url))
                                   '!?\[image[^\]]*\]\([^\)]+\)', '', 'gi'
                           ),

                       -- 5. Colapsa saltos de línea sobrantes
                           '\n\s*\n+', E'\n\n', 'g'
                   )
                )
           END;
$function$;

-- 3. Función para extraer título base (remueve números de versión/año y meses para detectar series)
CREATE OR REPLACE FUNCTION public.titulo_base(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE PARALLEL SAFE
AS $function$
SELECT btrim(regexp_replace(
        regexp_replace(t,
                       '\m(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\M|\d+',
                       '', 'g'),
        '\s+', ' ', 'g'));
$function$;

-- 4. Agregar columnas generadas si no existen
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='articulos' AND column_name='texto_sin_headers'
    ) THEN
        ALTER TABLE articulos
        ADD COLUMN texto_sin_headers text GENERATED ALWAYS AS (limpiar_headers(texto)) STORED;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='articulos' AND column_name='base_titulo'
    ) THEN
        ALTER TABLE articulos
        ADD COLUMN base_titulo text GENERATED ALWAYS AS (titulo_base(normalizar_texto(titulo))) STORED;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='articulos' AND column_name='hash_texto_sin_headers'
    ) THEN
        ALTER TABLE articulos
        ADD COLUMN hash_texto_sin_headers text GENERATED ALWAYS AS (
            CASE
                WHEN ((texto IS NOT NULL) AND (btrim(texto) <> ''::text)) 
                THEN md5(normalizar_texto(limpiar_headers(texto)))
                ELSE NULL::text
            END
        ) STORED;
    END IF;
END $$;

-- 5. Crear índices de soporte B-Tree
CREATE INDEX IF NOT EXISTS idx_articulos_base_titulo ON articulos USING btree (base_titulo);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto_sin_headers ON articulos USING btree (hash_texto_sin_headers);

-- 6. Crear índices vectoriales HNSW para similitud coseno
CREATE INDEX IF NOT EXISTS idx_articulos_embedding_texto 
    ON articulos USING hnsw (embedding_texto vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_articulos_embedding_titulo 
    ON articulos USING hnsw (embedding_titulo vector_cosine_ops);

COMMIT;
