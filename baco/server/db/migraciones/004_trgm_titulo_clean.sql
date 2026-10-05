-- 004_trgm_titulo_clean.sql
-- Migración para eliminar texto_1000 y habilitar índice GIN de trigramas sobre titulo_normalizado

BEGIN;

-- 1. Eliminar índice GIN y columna generada texto_1000 (pesada e innecesaria)
DROP INDEX IF EXISTS idx_texto1000_trgm;
ALTER TABLE articulos DROP COLUMN IF EXISTS texto_1000;

-- 2. Asegurar extensión pg_trgm
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 3. Crear índice GIN de trigramas sobre titulo_normalizado para detección rápida de typos y variantes
CREATE INDEX IF NOT EXISTS idx_articulos_titulo_trgm 
ON articulos USING gin (titulo_normalizado gin_trgm_ops);

COMMIT;
