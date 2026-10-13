-- 007_actualizar_titulo_base_series.sql
-- Refina la función public.titulo_base para capturar EXCLUSIVAMENTE series cronológicas/editoriales reales:
-- 1. Notas de versión periódicas (Novedades ERP, HCM, Agro, etc., meses, años, parches).
-- 2. Eventos / capacitaciones periódicas numeradas (1° Encuentro, 2° Encuentro).
-- 3. Versiones técnicas normativas decimales (PLE 3.3, PLE 3.5, PLE 3.11).
--
-- NOTA CRÍTICA DE DISEÑO:
-- NO limpia atajos de teclado (F3) ni variantes de motor (Antiguo Motor / Motor 2024).
-- Esos son duplicados o deprecaciones que deben pasar al buscador de duplicados/trigramas.

CREATE OR REPLACE FUNCTION public.titulo_base(t text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE PARALLEL SAFE
AS $$
DECLARE
    s text;
BEGIN
    IF t IS NULL OR trim(t) = '' THEN
        RETURN t;
    END IF;
    
    s := lower(t);
    
    -- 1. Fechas numéricas completas dd mm yyyy (ej: 28 03 2024)
    s := regexp_replace(s, '\m\d{1,2}\s+\d{1,2}\s+\d{2,4}\M', '', 'g');
    
    -- 2. Meses del año (incluye variantes comunes como 'agostos' y 'setiembre')
    s := regexp_replace(s, '\m(enero|febrero|marzo|abril|mayo|junio|julio|agosto|agostos|septiembre|setiembre|octubre|noviembre|diciembre)\M', '', 'g');
    
    -- 3. Años de 4 dígitos (20xx)
    s := regexp_replace(s, '\m20\d{2}\M', '', 'g');
    
    -- 4. Ordinales en eventos periódicos: "1 encuentro", "2 encuentro" -> "encuentro"
    s := regexp_replace(s, '\m\d+\s*(encuentro|jornada|evento|reunion|edicion)\M', '\1', 'g');
    
    -- 5. Notas de versión periódicas (Novedades)
    IF s ~ '\mnovedades\M' THEN
        s := regexp_replace(s, '\m(del|desde)\M.*', '', 'g');
        s := regexp_replace(s, '\m(teamplace|teampleace)\M.*', '', 'g');
        s := regexp_replace(s, '\mversion\s+erp\M.*', 'version erp', 'g');
        s := regexp_replace(s, '\mversion\s+agrolive\M.*', 'version agrolive', 'g');
        s := regexp_replace(s, '\m\d+\M', '', 'g');
    END IF;
    
    -- 6. Versiones técnicas normativas en PLE (ej: 3.3, 3.5, 3.11)
    IF s ~ '\mple\M' AND (s ~ '\minventario\M' OR s ~ '\mbalance\M') THEN
        s := regexp_replace(s, '\mple\s+libro\M', 'ple', 'g');
        s := regexp_replace(s, '\m\d+\M', '', 'g');
    END IF;
    
    -- Limpieza de espacios múltiples y trim
    s := btrim(regexp_replace(s, '\s+', ' ', 'g'));
    
    RETURN NULLIF(s, '');
END;
$$;

-- Recalcular base_titulo en todos los artículos existentes
UPDATE articulos SET titulo = titulo;
