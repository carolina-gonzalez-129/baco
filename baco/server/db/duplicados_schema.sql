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
SET search_path = public, duplicados, pg_temp
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
    SET search_path = public, duplicados, pg_temp
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
SET search_path = public, duplicados, pg_temp
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
SET search_path = public, duplicados, pg_temp
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
SET search_path = public, duplicados, pg_temp
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
SET search_path = public, duplicados, pg_temp
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
DROP FUNCTION IF EXISTS duplicados.similares_trigramas(character varying, double precision, integer);

CREATE OR REPLACE FUNCTION duplicados.similares_trigramas(
    p_titulo character varying,
    p_umbral double precision DEFAULT 0.90,
    p_limit integer DEFAULT 3
) RETURNS TABLE(
    id_articulo integer,
    titulo_articulo character varying,
    url_articulo text,
    score real
)
LANGUAGE plpgsql
SET search_path = public, duplicados, pg_temp
AS $$
DECLARE
    p_titulo_normalizado TEXT := public.normalizar_texto(p_titulo);
BEGIN
    RETURN QUERY
    SELECT a.id, a.titulo, a.url,
           public.similarity(a.titulo_normalizado, p_titulo_normalizado)::real AS score
    FROM public.articulos as a
    WHERE a.titulo_normalizado OPERATOR(public.%) p_titulo_normalizado
      AND public.similarity(a.titulo_normalizado, p_titulo_normalizado) >= p_umbral
    ORDER BY score DESC, a.id
    LIMIT p_limit;
END;
$$;
ALTER FUNCTION duplicados.similares_trigramas(character varying, double precision, integer) OWNER TO postgres;

CREATE OR REPLACE FUNCTION duplicados.son_iguales_titulo(
    p_dato character varying
) RETURNS boolean
LANGUAGE plpgsql
SET search_path = public, duplicados, pg_temp
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
