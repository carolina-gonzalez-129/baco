-- 003_pg_trgm_texto_1000.sql
-- Migración para búsqueda por similitud de texto con pg_trgm sobre los primeros 1000 caracteres normalizados

BEGIN;

-- 1. Habilitar extensión pg_trgm
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Limpiar restos de pruebas anteriores
DROP INDEX IF EXISTS idx_texto500_trgm;
ALTER TABLE articulos DROP COLUMN IF EXISTS texto_500;

-- 3. Como texto_normalizado es una columna COMÚN (TEXT), se agrega la columna generada texto_1000
--    y su correspondiente índice GIN con la clase de operadores gin_trgm_ops
ALTER TABLE articulos
    ADD COLUMN IF NOT EXISTS texto_1000 text GENERATED ALWAYS AS (left(texto_normalizado, 1000)) STORED;

CREATE INDEX IF NOT EXISTS idx_texto1000_trgm ON articulos USING gin (texto_1000 gin_trgm_ops);

COMMIT;
