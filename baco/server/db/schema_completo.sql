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
GRANT SELECT ON ALL TABLES IN SCHEMA public TO baco_readonly;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO baco_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO baco_readonly;

--
-- Schema duplicados y funciones de detección
--

CREATE SCHEMA IF NOT EXISTS duplicados;
ALTER SCHEMA duplicados OWNER TO postgres;

CREATE OR REPLACE FUNCTION duplicados.buscar_exacto(
    p_dato character varying,
    p_campo character varying DEFAULT 'titulo'::character varying,
    p_limit integer DEFAULT 3
) RETURNS TABLE(
    id_articulo integer,
    titulo_articulo character varying,
    url_articulo text,
    texto_articulo text
)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_dato_normalizado TEXT := public.normalizar_texto(p_dato);
    v_hash_dato        TEXT := md5(v_dato_normalizado);
BEGIN
    IF p_campo = 'texto' THEN
        RETURN QUERY
        SELECT 
            a.id, 
            a.titulo, 
            a.url, 
            a.texto
        FROM public.articulos a
        WHERE a.hash_texto = v_hash_dato
        ORDER BY a.id
        LIMIT p_limit;
    ELSIF p_campo = 'titulo' THEN
        RETURN QUERY
        SELECT 
            a.id, 
            a.titulo, 
            a.url, 
            a.texto
        FROM public.articulos a
        WHERE a.hash_titulo = v_hash_dato
        ORDER BY a.id
        LIMIT p_limit;
    ELSE
        RETURN;
    END IF;
END;
$$;
ALTER FUNCTION duplicados.buscar_exacto(character varying, character varying, integer) OWNER TO postgres;

DROP FUNCTION IF EXISTS duplicados.obtener_articulo(integer);
CREATE OR REPLACE FUNCTION duplicados.obtener_articulo(
    p_id_articulo integer
) RETURNS TABLE(
    id_articulo integer,
    titulo_articulo character varying,
    url_articulo text,
    texto_articulo text,
    categoria_id integer,
    tags text[]
)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.id,
        a.titulo,
        a.url,
        a.texto,
        a.categoria_id,
        COALESCE(
            (SELECT array_agg(t.name::text ORDER BY t.name)
             FROM public.articulo_tags at
             JOIN public.tags t ON t.id = at.tag_id
             WHERE at.articulo_id = a.id),
            ARRAY[]::text[]
        ) AS tags
    FROM public.articulos a 
    WHERE a.id = p_id_articulo;
END;
$$;
ALTER FUNCTION duplicados.obtener_articulo(integer) OWNER TO postgres;

DROP FUNCTION IF EXISTS duplicados.similares_embeddings_con_titulo(public.vector, public.vector, character varying, real, integer);
DROP FUNCTION IF EXISTS duplicados.similares_embeddings_con_titulo(public.vector, public.vector, character varying, numeric, integer);

CREATE OR REPLACE FUNCTION duplicados.similares_embeddings_con_titulo(
    p_embedding_texto public.vector,
    p_embedding_titulo public.vector,
    p_consulta_texto character varying,
    p_umbral_total numeric DEFAULT 0.85,
    p_limit integer DEFAULT 3
) RETURNS TABLE(
    id_articulo integer,
    titulo_articulo character varying,
    url_articulo text,
    titulo_normalizado text,
    consulta_normalizada text,
    texto_norm_1000 text,
    sim_texto numeric,
    sim_titulo numeric,
    score_total numeric
)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RETURN QUERY
    WITH candidatos AS (
        (
            SELECT a_t.id 
            FROM public.articulos a_t 
            WHERE a_t.embedding_texto IS NOT NULL 
            ORDER BY a_t.embedding_texto <=> p_embedding_texto 
            LIMIT GREATEST(p_limit * 5, 25)
        )
        UNION
        (
            SELECT a_tit.id 
            FROM public.articulos a_tit 
            WHERE a_tit.embedding_titulo IS NOT NULL 
            ORDER BY a_tit.embedding_titulo <=> p_embedding_titulo 
            LIMIT GREATEST(p_limit * 5, 25)
        )
    ),
    puntuados AS (
        SELECT 
            a.id, 
            a.titulo, 
            a.url, 
            a.titulo_normalizado,
            public.normalizar_texto(p_consulta_texto) AS consulta_normalizada,
            LEFT(COALESCE(a.texto_normalizado, ''), 1000) AS texto_norm_1000,
            ROUND((1 - (a.embedding_texto <=> p_embedding_texto))::NUMERIC, 3) AS sim_texto,
            ROUND((1 - (a.embedding_titulo <=> p_embedding_titulo))::NUMERIC, 3) AS sim_titulo
        FROM public.articulos a 
        JOIN candidatos c ON a.id = c.id
    )
    SELECT 
        p.id, 
        p.titulo, 
        p.url, 
        p.titulo_normalizado, 
        p.consulta_normalizada,
        p.texto_norm_1000, 
        p.sim_texto, 
        p.sim_titulo,
        ROUND((0.8 * p.sim_texto + 0.2 * p.sim_titulo)::NUMERIC, 3) AS score_total
    FROM puntuados p
    WHERE 
        (
            (0.8 * p.sim_texto + 0.2 * p.sim_titulo) >= p_umbral_total 
            AND p.sim_texto >= 0.80
            AND p.sim_titulo >= 0.50
        )
        OR (p.sim_texto >= 0.90)
    ORDER BY 
        score_total DESC, 
        p.id
    LIMIT p_limit;
END;
$$;
ALTER FUNCTION duplicados.similares_embeddings_con_titulo(public.vector, public.vector, character varying, numeric, integer) OWNER TO postgres;

DROP FUNCTION IF EXISTS duplicados.similares_embeddings_solo_texto(public.vector, character varying, real, integer);
DROP FUNCTION IF EXISTS duplicados.similares_embeddings_solo_texto(public.vector, character varying, numeric, integer);

CREATE OR REPLACE FUNCTION duplicados.similares_embeddings_solo_texto(
    p_embedding_texto public.vector,
    p_consulta_texto character varying,
    p_umbral numeric DEFAULT 0.85,
    p_limit integer DEFAULT 3
) RETURNS TABLE(
    id_articulo integer,
    titulo_articulo character varying,
    url_articulo text,
    titulo_normalizado text,
    consulta_normalizada text,
    texto_norm_1000 text,
    sim_texto numeric,
    sim_titulo numeric,
    score_total numeric
)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RETURN QUERY
    WITH candidatos AS (
        SELECT a_c.id 
        FROM public.articulos a_c
        WHERE a_c.embedding_texto IS NOT NULL 
        ORDER BY a_c.embedding_texto <=> p_embedding_texto 
        LIMIT p_limit * 2
    ),
    puntuados AS (
        SELECT 
            a.id, 
            a.titulo, 
            a.url, 
            a.titulo_normalizado,
            public.normalizar_texto(p_consulta_texto) AS consulta_normalizada,
            LEFT(COALESCE(a.texto_normalizado, ''), 1000) AS texto_norm_1000,
            ROUND((1 - (a.embedding_texto <=> p_embedding_texto))::NUMERIC, 3) AS sim_texto,
            0.0::NUMERIC AS sim_titulo
        FROM public.articulos a 
        JOIN candidatos c ON a.id = c.id
    )
    SELECT 
        p.id, 
        p.titulo, 
        p.url, 
        p.titulo_normalizado, 
        p.consulta_normalizada,
        p.texto_norm_1000, 
        p.sim_texto, 
        p.sim_titulo,
        p.sim_texto AS score_total
    FROM puntuados p
    WHERE p.sim_texto >= p_umbral
    ORDER BY score_total DESC
    LIMIT p_limit;
END;
$$;
ALTER FUNCTION duplicados.similares_embeddings_solo_texto(public.vector, character varying, numeric, integer) OWNER TO postgres;

DROP FUNCTION IF EXISTS duplicados.similares_embeddings_titulo(public.vector, real, integer);
DROP FUNCTION IF EXISTS duplicados.similares_embeddings_titulo(public.vector, numeric, integer);

CREATE OR REPLACE FUNCTION duplicados.similares_embeddings_titulo(
    p_embedding_titulo public.vector,
    p_umbral numeric DEFAULT 0.65,
    p_limit integer DEFAULT 3
) RETURNS TABLE(
    id_articulo integer,
    titulo_articulo character varying,
    url_articulo text,
    sim_titulo numeric
)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.id,
        a.titulo,
        a.url,
        ROUND((1 - (a.embedding_titulo <=> p_embedding_titulo))::NUMERIC, 3) AS sim_titulo
    FROM public.articulos a
    WHERE 
        a.embedding_titulo IS NOT NULL
        AND (1 - (a.embedding_titulo <=> p_embedding_titulo)) >= p_umbral
    ORDER BY 
        a.embedding_titulo <=> p_embedding_titulo ASC,
        a.id
    LIMIT p_limit;
END;
$$;
ALTER FUNCTION duplicados.similares_embeddings_titulo(public.vector, numeric, integer) OWNER TO postgres;


CREATE OR REPLACE FUNCTION duplicados.similares_series(
    p_titulo character varying,
    p_limit integer DEFAULT 3
) RETURNS TABLE(
    id_articulo integer,
    titulo_articulo character varying,
    url_articulo text,
    base_titulo text
)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_base_titulo TEXT := public.titulo_base(public.normalizar_texto(p_titulo));
BEGIN
    RETURN QUERY
    SELECT a.id, a.titulo, a.url, a.base_titulo
    FROM public.articulos as a
    WHERE a.base_titulo = v_base_titulo
    AND a.base_titulo <> ''
    AND v_base_titulo <> public.normalizar_texto(p_titulo)
    AND a.titulo <> p_titulo
    ORDER BY a.id DESC
    LIMIT p_limit;
END;
$$;
ALTER FUNCTION duplicados.similares_series(character varying, integer) OWNER TO postgres;

DROP FUNCTION IF EXISTS duplicados.similares_trigramas(character varying, real, integer);
DROP FUNCTION IF EXISTS duplicados.similares_trigramas(character varying, numeric, integer);

CREATE OR REPLACE FUNCTION duplicados.similares_trigramas(
    p_titulo character varying,
    p_umbral numeric DEFAULT 0.90,
    p_limit integer DEFAULT 3
) RETURNS TABLE(
    id_articulo integer,
    titulo_articulo character varying,
    url_articulo text,
    score real
)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    p_titulo_normalizado TEXT := public.normalizar_texto(p_titulo);
BEGIN
    RETURN QUERY
    SELECT a.id, a.titulo, a.url,
           public.similarity(a.titulo_normalizado, p_titulo_normalizado) AS score
    FROM public.articulos as a
    WHERE a.titulo_normalizado % p_titulo_normalizado
      AND public.similarity(a.titulo_normalizado, p_titulo_normalizado) >= p_umbral
    ORDER BY score DESC, a.id
    LIMIT p_limit;
END;
$$;
ALTER FUNCTION duplicados.similares_trigramas(character varying, numeric, integer) OWNER TO postgres;

CREATE OR REPLACE FUNCTION duplicados.son_iguales_titulo(
    p_dato character varying
) RETURNS boolean
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_dato_normalizado TEXT := public.normalizar_texto(p_dato);
    v_hash_dato        TEXT := md5(v_dato_normalizado);
BEGIN
    RETURN EXISTS (
        SELECT 1 
        FROM public.articulos 
        WHERE hash_titulo = v_hash_dato
    );
END;
$$;
ALTER FUNCTION duplicados.son_iguales_titulo(character varying) OWNER TO postgres;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'baco_readonly') THEN
        GRANT USAGE ON SCHEMA duplicados TO baco_readonly;
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA duplicados TO baco_readonly;
        GRANT SELECT ON ALL TABLES IN SCHEMA duplicados TO baco_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA duplicados GRANT SELECT ON TABLES TO baco_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA duplicados GRANT EXECUTE ON FUNCTIONS TO baco_readonly;
    END IF;
END $$;
