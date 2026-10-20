CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE OR REPLACE FUNCTION public.normalizar_texto(t text)
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

CREATE OR REPLACE FUNCTION public.titulo_base(t text)
RETURNS text LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
    s text;
BEGIN
    IF t IS NULL OR trim(t) = '' THEN
        RETURN t;
    END IF;
    s := lower(t);
    s := regexp_replace(s, '\m\d{1,2}\s+\d{1,2}\s+\d{2,4}\M', '', 'g');
    s := regexp_replace(s, '\m(enero|febrero|marzo|abril|mayo|junio|julio|agosto|agostos|septiembre|setiembre|octubre|noviembre|diciembre)\M', '', 'g');
    s := regexp_replace(s, '\m20\d{2}\M', '', 'g');
    s := regexp_replace(s, '\m\d+\s*(encuentro|jornada|evento|reunion|edicion)\M', '\1', 'g');
    IF s ~ '\mnovedades\M' THEN
        s := regexp_replace(s, '\m(del|desde)\M.*', '', 'g');
        s := regexp_replace(s, '\m(teamplace|teampleace)\M.*', '', 'g');
        s := regexp_replace(s, '\mversion\s+erp\M.*', 'version erp', 'g');
        s := regexp_replace(s, '\mversion\s+agrolive\M.*', 'version agrolive', 'g');
        s := regexp_replace(s, '\m\d+\M', '', 'g');
    END IF;
    IF s ~ '\mple\M' AND (s ~ '\minventario\M' OR s ~ '\mbalance\M') THEN
        s := regexp_replace(s, '\mple\s+libro\M', 'ple', 'g');
        s := regexp_replace(s, '\m\d+\M', '', 'g');
    END IF;
    s := btrim(regexp_replace(s, '\s+', ' ', 'g'));
    RETURN NULLIF(s, '');
END;
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

CREATE TABLE IF NOT EXISTS categorias (
    id INT PRIMARY KEY,
    nombre VARCHAR(150)
);

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

CREATE OR REPLACE FUNCTION fn_invalidar_embeddings_articulos()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.titulo IS DISTINCT FROM OLD.titulo THEN
        IF NEW.embedding_titulo IS NOT DISTINCT FROM OLD.embedding_titulo THEN
            NEW.embedding_titulo := NULL;
        END IF;
    END IF;

    IF NEW.texto IS DISTINCT FROM OLD.texto THEN
        IF NEW.embedding_texto IS NOT DISTINCT FROM OLD.embedding_texto THEN
            NEW.embedding_texto := NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_articulos_invalida_embeddings ON articulos;

CREATE TRIGGER trg_articulos_invalida_embeddings
BEFORE UPDATE OF titulo, texto ON articulos
FOR EACH ROW
EXECUTE FUNCTION fn_invalidar_embeddings_articulos();

CREATE INDEX IF NOT EXISTS idx_articulos_categoria ON articulos(categoria_id);
CREATE INDEX IF NOT EXISTS idx_articulos_actualizado ON articulos(actualizado);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_titulo ON articulos(hash_titulo);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto ON articulos(hash_texto);
CREATE INDEX IF NOT EXISTS idx_articulos_hash_texto_sin_headers ON articulos(hash_texto_sin_headers);
CREATE INDEX IF NOT EXISTS idx_articulos_base_titulo ON articulos(base_titulo);
CREATE INDEX IF NOT EXISTS idx_articulos_titulo_trgm ON articulos USING gin (titulo_normalizado gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_articulos_embedding_titulo ON articulos USING hnsw (embedding_titulo vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_articulos_embedding_texto ON articulos USING hnsw (embedding_texto vector_cosine_ops);

DO $$
    DECLARE
        ro_pwd text := nullif(current_setting('baco.ro_password', true), '');
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'baco_readonly') THEN
            IF ro_pwd IS NULL THEN
                RAISE EXCEPTION 'Para crear baco_readonly se requiere definir la variable de entorno DB_RO_PASSWORD';
            END IF;
            EXECUTE format('CREATE ROLE baco_readonly WITH LOGIN PASSWORD %L', ro_pwd);
        END IF;

        ALTER ROLE baco_readonly SET default_transaction_read_only = on;
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO baco_readonly', current_database());
    END
$$;

GRANT USAGE ON SCHEMA public TO baco_readonly;
GRANT SELECT ON TABLE articulos, tags, articulo_tags TO baco_readonly;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO baco_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO baco_readonly;
