CREATE TABLE IF NOT EXISTS embeddings_meta (
    columna    varchar PRIMARY KEY,
    model_name varchar NOT NULL,
    dimension  integer NOT NULL,
    creado_en  timestamptz DEFAULT NOW()
);

INSERT INTO embeddings_meta (columna, model_name, dimension) VALUES
    ('titulo', 'paraphrase-multilingual-MiniLM-L12-v2', 384),
    ('texto', 'intfloat/multilingual-e5-base', 768)
ON CONFLICT (columna) DO NOTHING;
