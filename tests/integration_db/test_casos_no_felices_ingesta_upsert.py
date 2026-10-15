import pytest
from datetime import datetime, timezone
from baco.server.db.ingesta import upsert_articulos


@pytest.mark.integration
def test_ingesta_idempotencia_no_duplica_filas_ni_genera_cambios(clean_db):
    """
    Regla: La ingesta debe ser estrictamente idempotente. Ejecutar el upsert dos veces
    con exactamente los mismos datos no debe duplicar registros ni reportar modificaciones.
    """
    articulo = {
        "id": 601,
        "titulo": "Alta de Clientes en Finnegans ERP",
        "categoria_id": 10,
        "url": "https://bc-dev.finneg.com/t/601",
        "texto": "Instructivo detallado para la creación de cuentas de clientes.",
        "actualizado": datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc),
        "tags": [{"id": 1, "name": "instructivo", "slug": "instructivo"}]
    }

    # Primera corrida: Inserción inicial
    resumen1 = upsert_articulos(clean_db, [articulo])
    clean_db.commit()
    assert resumen1.insertados == 1
    assert resumen1.actualizados == 0
    assert resumen1.sin_cambios == 0

    # Segunda corrida: Idempotencia estricta
    resumen2 = upsert_articulos(clean_db, [articulo])
    clean_db.commit()
    assert resumen2.insertados == 0
    assert resumen2.actualizados == 0
    assert resumen2.sin_cambios == 1

    # Verificación observable en la base de datos
    with clean_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM articulos WHERE id = 601;")
        assert cur.fetchone()[0] == 1


@pytest.mark.integration
def test_ingesta_fecha_anterior_no_pisa_articulo_mas_nuevo(clean_db):
    """
    Regla: La ingesta nunca debe sobrescribir un artículo si los datos entrantes
    tienen una fecha de actualización anterior a la ya registrada en la base.
    """
    fecha_nueva = datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    articulo_nuevo = {
        "id": 602,
        "titulo": "Versión Actualizada 2.0",
        "categoria_id": 10,
        "url": "https://bc-dev.finneg.com/t/602",
        "texto": "Contenido actualizado reciente.",
        "actualizado": fecha_nueva,
        "tags": []
    }
    upsert_articulos(clean_db, [articulo_nuevo])
    clean_db.commit()

    # Intentamos aplicar una versión desactualizada con fecha anterior
    fecha_vieja = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
    articulo_viejo = {
        "id": 602,
        "titulo": "Versión Antigua 1.0 (Sobreescritura no permitida)",
        "categoria_id": 10,
        "url": "https://bc-dev.finneg.com/t/602",
        "texto": "Contenido viejo.",
        "actualizado": fecha_vieja,
        "tags": []
    }
    resumen = upsert_articulos(clean_db, [articulo_viejo])
    clean_db.commit()

    assert resumen.omitidos_por_antiguedad == 1
    assert 602 in resumen.ids_omitidos

    # Verificación observable: la base conserva el título y fecha más nuevos
    with clean_db.cursor() as cur:
        cur.execute("SELECT titulo, actualizado FROM articulos WHERE id = 602;")
        tit_db, fecha_db = cur.fetchone()
        assert tit_db == "Versión Actualizada 2.0"
        assert fecha_db == fecha_nueva


@pytest.mark.integration
def test_ingesta_falla_a_mitad_de_lote_mantiene_atomicidad_transaccional(clean_db):
    """
    Regla: La ingesta de un lote debe ser atómica. Si un ítem falla a mitad del procesamiento
    y la transacción se cancela (rollback), ningún ítem de ese lote debe quedar persistido.
    """
    # 1. Insertamos un artículo previo para verificar que no se afecte
    art_previo = {
        "id": 603,
        "titulo": "Artículo Previo Estable",
        "categoria_id": 10,
        "url": "https://bc-dev.finneg.com/t/603",
        "texto": "Este artículo ya existía antes del lote fallido.",
        "actualizado": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "tags": []
    }
    upsert_articulos(clean_db, [art_previo])
    clean_db.commit()

    # 2. Lote con 2 artículos: el primero es válido, el segundo provocará un error de tipo en SQL
    art_valido = {
        "id": 604,
        "titulo": "Artículo Válido del Lote",
        "categoria_id": 10,
        "url": "https://bc-dev.finneg.com/t/604",
        "texto": "Texto válido.",
        "actualizado": datetime(2026, 2, 1, tzinfo=timezone.utc),
        "tags": []
    }
    art_corrupto = {
        "id": "NO_ES_UN_INT",  # Fallará al insertarse en columna INTEGER id
        "titulo": "Artículo Corrupto",
        "categoria_id": 10,
        "url": "https://bc-dev.finneg.com/t/error",
        "texto": "Texto.",
        "actualizado": datetime(2026, 2, 1, tzinfo=timezone.utc),
        "tags": []
    }

    try:
        upsert_articulos(clean_db, [art_valido, art_corrupto])
        clean_db.commit()
    except Exception:
        clean_db.rollback()

    # 3. Verificación observable: el artículo 604 NO debe existir en la base (rollback atómico)
    with clean_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM articulos WHERE id = 604;")
        assert cur.fetchone()[0] == 0, "El artículo válido del lote no debe haberse persistido tras el rollback"

        cur.execute("SELECT count(*) FROM articulos WHERE id = 603;")
        assert cur.fetchone()[0] == 1, "El artículo previo debe mantenerse intacto"


@pytest.mark.integration
def test_ingesta_texto_vacio_o_none_mantiene_embedding_texto_nulo(clean_db):
    """
    Regla: Artículos ingresados con texto vacío o None deben persistirse con
    embedding_texto = NULL y hash_texto = NULL, evitando generar vectores espurios.
    """
    articulo_vacio = {
        "id": 605,
        "titulo": "Artículo sin cuerpo de texto",
        "categoria_id": 10,
        "url": "https://bc-dev.finneg.com/t/605",
        "texto": "",
        "actualizado": datetime(2026, 3, 1, tzinfo=timezone.utc),
        "tags": []
    }

    upsert_articulos(clean_db, [articulo_vacio])
    clean_db.commit()

    with clean_db.cursor() as cur:
        cur.execute(
            """
            SELECT embedding_texto IS NULL, hash_texto IS NULL, embedding_titulo IS NOT NULL
            FROM articulos WHERE id = 605;
            """
        )
        emb_txt_null, hash_txt_null, emb_tit_not_null = cur.fetchone()
        assert emb_txt_null is True, "embedding_texto debe permanecer en NULL para textos vacíos"
        assert hash_txt_null is True, "hash_texto debe permanecer en NULL para textos vacíos"
