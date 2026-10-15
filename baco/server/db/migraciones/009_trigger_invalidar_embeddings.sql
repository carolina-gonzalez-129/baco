-- 009_trigger_invalidar_embeddings.sql
-- Invalida automáticamente embeddings a NULL cuando el título o texto cambian manualmente o por ingestión.
-- Las columnas calculadas STORED (normalizados y hashes MD5) son regeneradas automáticamente por Postgres.

CREATE OR REPLACE FUNCTION fn_invalidar_embeddings_articulos()
RETURNS TRIGGER AS $$
BEGIN
    -- 1. Si cambió el título y no se pasó un nuevo embedding_titulo en este UPDATE:
    IF NEW.titulo IS DISTINCT FROM OLD.titulo THEN
        IF NEW.embedding_titulo IS NOT DISTINCT FROM OLD.embedding_titulo THEN
            NEW.embedding_titulo := NULL;
        END IF;
    END IF;

    -- 2. Si cambió el texto y no se pasó un nuevo embedding_texto en este UPDATE:
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
