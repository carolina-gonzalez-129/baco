import pytest
from baco.server.db.ingesta import upsert_articulos, ResumenIngesta

SQL_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION fn_invalidar_embeddings_articulos()
RETURNS TRIGGER AS $$
BEGIN
    -- 1. Si cambió el título
    IF NEW.titulo IS DISTINCT FROM OLD.titulo THEN
        IF NEW.embedding_titulo IS NOT DISTINCT FROM OLD.embedding_titulo THEN
            NEW.embedding_titulo := NULL;
        END IF;
    END IF;

    -- 2. Si cambió el texto
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
"""

DUMMY_VEC_384 = "[" + ",".join(["0.01"] * 384) + "]"
DUMMY_VEC_768 = "[" + ",".join(["0.02"] * 768) + "]"
NUEVO_VEC_384 = "[" + ",".join(["0.09"] * 384) + "]"


@pytest.fixture
def db_con_trigger(db_conn):
    """Instala el trigger de invalidación de embeddings en la base de datos de test."""
    with db_conn.cursor() as cur:
        cur.execute(SQL_TRIGGER_FUNCTION)
    yield db_conn
    # Limpieza posterior
    with db_conn.cursor() as cur:
        cur.execute("DROP TRIGGER IF EXISTS trg_articulos_invalida_embeddings ON articulos;")


def test_trigger_invalida_solo_titulo_al_editar_titulo(db_con_trigger):
    """Verifica que al cambiar solo el título, embedding_titulo se ponga en NULL y embedding_texto quede intacto."""
    with db_con_trigger.cursor() as cur:
        # Insertar artículo con ambos embeddings calculados
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto, embedding_titulo, embedding_texto)
            VALUES (2001, 'Título Original', 'https://test/2001', 'Texto que no cambia', %s, %s);
            """,
            (DUMMY_VEC_384, DUMMY_VEC_768)
        )

        # Modificar solo el título mediante UPDATE directo
        cur.execute(
            "UPDATE articulos SET titulo = 'Título Modificado' WHERE id = 2001;"
        )

        cur.execute(
            "SELECT embedding_titulo, embedding_texto FROM articulos WHERE id = 2001;"
        )
        row = cur.fetchone()
        emb_tit, emb_txt = row

        # El embedding del título DEBE ser NULL porque el título cambió
        assert emb_tit is None
        # El embedding del texto NO debe ser tocado porque el texto sigue igual
        assert emb_txt is not None


def test_trigger_invalida_solo_texto_al_editar_texto(db_con_trigger):
    """Verifica que al cambiar solo el texto, embedding_texto se ponga en NULL y embedding_titulo quede intacto."""
    with db_con_trigger.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto, embedding_titulo, embedding_texto)
            VALUES (2002, 'Título Fijo', 'https://test/2002', 'Texto Original', %s, %s);
            """,
            (DUMMY_VEC_384, DUMMY_VEC_768)
        )

        # Modificar solo el texto
        cur.execute(
            "UPDATE articulos SET texto = 'Texto Modificado Completamente' WHERE id = 2002;"
        )

        cur.execute(
            "SELECT embedding_titulo, embedding_texto FROM articulos WHERE id = 2002;"
        )
        emb_tit, emb_txt = cur.fetchone()

        # El título no cambió -> permanece
        assert emb_tit is not None
        # El texto cambió -> se invalida a NULL
        assert emb_txt is None


def test_trigger_no_invalida_al_editar_otros_campos(db_con_trigger):
    """Verifica que modificar url o categoria_id NO invalide los embeddings."""
    with db_con_trigger.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto, embedding_titulo, embedding_texto)
            VALUES (2003, 'Título Estable', 'https://test/old-url', 'Texto Estable', %s, %s);
            """,
            (DUMMY_VEC_384, DUMMY_VEC_768)
        )

        cur.execute(
            "UPDATE articulos SET url = 'https://test/new-url' WHERE id = 2003;"
        )

        cur.execute(
            "SELECT embedding_titulo, embedding_texto FROM articulos WHERE id = 2003;"
        )
        emb_tit, emb_txt = cur.fetchone()
        assert emb_tit is not None
        assert emb_txt is not None


def test_coexistencia_cuando_python_guarda_embeddings(db_con_trigger):
    """Verifica que la actualización de embeddings que hace common.py / embeddings.py se aplique sin ser anulada."""
    with db_con_trigger.cursor() as cur:
        # Inicia sin embeddings (NULL)
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto)
            VALUES (2004, 'Título Pendiente', 'https://test/2004', 'Texto Pendiente');
            """
        )

        # Python calcula y guarda los embeddings (simulado como hace actualizar_embeddings_articulo)
        cur.execute(
            """
            UPDATE articulos 
            SET embedding_titulo = %s, embedding_texto = %s 
            WHERE id = 2004;
            """,
            (DUMMY_VEC_384, DUMMY_VEC_768)
        )

        cur.execute(
            "SELECT embedding_titulo, embedding_texto FROM articulos WHERE id = 2004;"
        )
        emb_tit, emb_txt = cur.fetchone()
        assert emb_tit is not None
        assert emb_txt is not None


def test_coexistencia_con_upsert_articulos_discourse(db_con_trigger):
    """Verifica que el pipeline de ingesta existente (upsert_articulos) siga funcionando exactamente igual."""
    articulo_item = {
        "id": 2005,
        "titulo": "Título Ingesta 1",
        "url": "https://test/2005",
        "texto": "Cuerpo Ingesta 1",
        "categoria_id": None,
        "actualizado": None,
        "tags": None
    }

    # 1. Primera inserción con upsert_articulos
    resumen = upsert_articulos(db_con_trigger, [articulo_item])
    assert resumen.insertados == 1

    # Asignamos embeddings manualmente (como haría el pipeline después)
    with db_con_trigger.cursor() as cur:
        cur.execute(
            "UPDATE articulos SET embedding_titulo = %s, embedding_texto = %s WHERE id = 2005;",
            (DUMMY_VEC_384, DUMMY_VEC_768)
        )

    # 2. Re-ingesta SIN cambios -> los embeddings deben seguir intactos
    resumen2 = upsert_articulos(db_con_trigger, [articulo_item])
    assert resumen2.sin_cambios == 1

    with db_con_trigger.cursor() as cur:
        cur.execute("SELECT embedding_titulo, embedding_texto FROM articulos WHERE id = 2005;")
        emb_tit, emb_txt = cur.fetchone()
        assert emb_tit is not None
        assert emb_txt is not None

    # 3. Re-ingesta CON nuevo título -> el trigger y el upsert colaboran y dejan embedding_titulo en NULL
    articulo_editado = dict(articulo_item)
    articulo_editado["titulo"] = "Título Ingesta Editado"
    resumen3 = upsert_articulos(db_con_trigger, [articulo_editado])
    assert resumen3.actualizados == 1

    with db_con_trigger.cursor() as cur:
        cur.execute("SELECT embedding_titulo, embedding_texto FROM articulos WHERE id = 2005;")
        emb_tit, emb_txt = cur.fetchone()
        assert emb_tit is None  # Debe estar en NULL listo para recalcular
        assert emb_txt is not None  # Texto no cambió, se conserva
