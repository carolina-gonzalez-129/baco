-- 001_hashes_y_embeddings.sql
-- Migración idempotente para hashes y embeddings locales (MiniLM-L12-v2)

-- 1. Eliminar enfoque anterior de embeddings de Gemini
DROP INDEX IF EXISTS idx_articulos_embedding;
ALTER TABLE articulos DROP COLUMN IF EXISTS embedding;

-- 2. Agregar nuevas columnas de hashes (char(32)) y embeddings (vector(384))
ALTER TABLE articulos ADD COLUMN IF NOT EXISTS hash_titulo CHAR(32);
ALTER TABLE articulos ADD COLUMN IF NOT EXISTS hash_texto CHAR(32);
ALTER TABLE articulos ADD COLUMN IF NOT EXISTS embedding_titulo vector(384);
ALTER TABLE articulos ADD COLUMN IF NOT EXISTS embedding_texto vector(384);

-- 3. Índices B-tree comunes para los hashes (sin UNIQUE)
CREATE INDEX IF NOT EXISTS idx_articulos_hash_titulo ON articulos(hash_titulo);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto ON articulos(hash_texto);

-- 4. Tabla de metadatos del modelo de embeddings
CREATE TABLE IF NOT EXISTS embeddings_meta (
    model_name VARCHAR(150) PRIMARY KEY,
    dimension INT NOT NULL,
    creado_en TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Registrar el modelo oficial y dimension esperada
INSERT INTO embeddings_meta (model_name, dimension)
VALUES ('paraphrase-multilingual-MiniLM-L12-v2', 384)
ON CONFLICT (model_name) DO UPDATE 
SET dimension = EXCLUDED.dimension;
