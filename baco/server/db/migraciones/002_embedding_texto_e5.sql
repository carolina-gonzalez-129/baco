BEGIN;

-- 1. Recrear la columna embedding_texto con dimensión 768.
-- Al eliminarla y recrearla, los registros de texto quedan en NULL para regenerarse
-- con intfloat/multilingual-e5-base, sin dejar vectores residuales de 384 dim.
-- La columna embedding_titulo (384) NO se toca ni se invalida.
ALTER TABLE articulos DROP COLUMN IF EXISTS embedding_texto;
ALTER TABLE articulos ADD COLUMN IF NOT EXISTS embedding_texto vector(768);

-- 2. Rediseñar embeddings_meta para soportar configuración independiente por columna
DROP TABLE IF EXISTS embeddings_meta;

CREATE TABLE IF NOT EXISTS embeddings_meta (
    columna VARCHAR(20) PRIMARY KEY, -- 'titulo' | 'texto'
    model_name VARCHAR(150) NOT NULL,
    dimension INT NOT NULL,
    creado_en TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Sembrar los metadatos oficiales para cada columna
INSERT INTO embeddings_meta (columna, model_name, dimension)
VALUES 
    ('titulo', 'paraphrase-multilingual-MiniLM-L12-v2', 384),
    ('texto', 'intfloat/multilingual-e5-base', 768)
ON CONFLICT (columna) DO UPDATE
SET model_name = EXCLUDED.model_name,
    dimension = EXCLUDED.dimension;

COMMIT;
