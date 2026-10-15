import pytest
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.embeddings import embedding_titulo, embedding_texto


@pytest.mark.integration
def test_mismo_titulo_con_distinta_capitalizacion_o_acentos_es_duplicado_exacto(clean_db):
    """
    Regla: La búsqueda exacta por hash de título es agnóstica a mayúsculas, minúsculas y tildes.
    Si se consulta con distinta capitalización o sin tildes, debe reconocerse como duplicado exacto.
    """
    with clean_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto)
            VALUES (%s, %s, %s, %s);
            """,
            (
                501,
                "Configuración de Facturación Electrónica en AFIP",
                "https://bc-dev.finneg.com/t/501",
                "Guía paso a paso para configurar los parámetros de facturación electrónica."
            )
        )
        clean_db.commit()

        buscador = BuscadorDuplicados(cur)
        # Búsqueda con minúsculas y sin tildes
        resultado = buscador.evaluar_coincidencias("configuracion de facturacion electronica en afip")

        assert resultado["encontrado"] is True
        assert resultado["link"] == "https://bc-dev.finneg.com/t/501"
        assert "exactamente este título" in resultado["mensaje"]

        # Pausa para inspeccionar en Docker Desktop
        import time
        import os
        segundos = int(os.getenv("PAUSA_DOCKER", "45"))
        if segundos > 0:
            print("\n\n" + "=" * 70)
            print(f" [PAUSA DOCKER DESKTOP] Contenedor activo durante {segundos} segundos.")
            print(" -> Abrí Docker Desktop -> pestaña 'Containers'")
            print(" -> Hacé clic sobre el contenedor de pgvector para ver Logs o abrir Exec.")
            print("=" * 70 + "\n", flush=True)
            time.sleep(segundos)


@pytest.mark.integration
def test_titulo_de_serie_novedades_mayo_vs_junio_no_es_duplicado_exacto(clean_db):
    """
    Regla: Artículos periódicos o secuenciales (ej. 'Novedades Mayo 2026' vs 'Novedades Junio 2026')
    comparten base de serie pero NO son duplicados exactos; deben alertar como nueva edición de serie.
    """
    with clean_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto)
            VALUES (%s, %s, %s, %s);
            """,
            (
                502,
                "Novedades de la Versión - Mayo 2026",
                "https://bc-dev.finneg.com/t/502",
                "Resumen de mejoras implementadas durante el mes de mayo de 2026."
            )
        )
        clean_db.commit()

        buscador = BuscadorDuplicados(cur)
        resultado = buscador.evaluar_coincidencias("Novedades de la Versión - Junio 2026")

        assert resultado["encontrado"] is True
        assert "nueva edición de la serie" in resultado["mensaje"]
        assert resultado["link"] == "https://bc-dev.finneg.com/t/502"


@pytest.mark.integration
def test_titulo_trigrama_justo_por_debajo_de_umbral_70_no_coincide(clean_db):
    """
    Regla: Si la similitud trigramática entre dos títulos es inferior al umbral 0.70,
    no debe considerarse coincidencia por trigramas.
    """
    with clean_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto)
            VALUES (%s, %s, %s, %s);
            """,
            (
                503,
                "Facturación Electrónica de Exportación AFIP",
                "https://bc-dev.finneg.com/t/503",
                "Procedimiento detallado de comprobantes de exportación."
            )
        )
        clean_db.commit()

        # "Facturación AFIP" comparte algunas palabras pero su similitud real es ~0.43 (menor a 0.70)
        buscador = BuscadorDuplicados(cur)
        coincidencias = buscador.buscar_por_titulo_trigrama("Facturación AFIP", threshold=0.70)

        assert len(coincidencias) == 0, "No debe devolver coincidencias por trigrama si el score < 0.70"


@pytest.mark.integration
def test_mismo_texto_con_y_sin_headers_de_plantilla_es_duplicado(clean_db):
    """
    Regla: Dos artículos que contienen el mismo texto sustancial pero uno tiene encabezados
    de plantilla Markdown (# Consulta / # Pasos a seguir) y el otro no, deben detectarse como duplicados.
    """
    texto_con_headers = (
        "# Consulta\n"
        "¿Cómo configurar el punto de venta de facturación electrónica en Finnegans ERP?\n\n"
        "# Pasos a seguir\n"
        "1. Ingresar a Parámetros de Facturación.\n"
        "2. Asignar el nuevo número de punto de venta AFIP.\n"
        "3. Guardar los cambios realizados."
    )

    texto_sin_headers = (
        "¿Cómo configurar el punto de venta de facturación electrónica en Finnegans ERP?\n\n"
        "1. Ingresar a Parámetros de Facturación.\n"
        "2. Asignar el nuevo número de punto de venta AFIP.\n"
        "3. Guardar los cambios realizados."
    )

    with clean_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto)
            VALUES (%s, %s, %s, %s);
            """,
            (
                504,
                "Configurar Punto de Venta",
                "https://bc-dev.finneg.com/t/504",
                texto_con_headers
            )
        )
        clean_db.commit()

        buscador = BuscadorDuplicados(cur)
        # Evaluamos el texto sin headers contra el artículo existente que tenía headers
        resultado = buscador.evaluar_nuevo_articulo_sin_headers(
            titulo="Otro título no relacionado",
            texto=texto_sin_headers
        )

        assert resultado["encontrado"] is True
        assert resultado["link"] == "https://bc-dev.finneg.com/t/504"
        assert "exactamente la misma descripción" in resultado["mensaje"]


@pytest.mark.integration
def test_titulo_sin_relacion_con_similitud_baja_no_debe_aparecer_como_coincidencia(clean_db):
    """
    Regla: Consultas sobre temas completamente ajenos a los existentes en la base
    no deben arrojar ninguna coincidencia en ninguna de las capas.
    """
    with clean_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto)
            VALUES (%s, %s, %s, %s);
            """,
            (
                505,
                "Liquidación de Cargas Sociales y Sueldos",
                "https://bc-dev.finneg.com/t/505",
                "Detalle de liquidación mensual de convenios colectivos."
            )
        )
        clean_db.commit()

        buscador = BuscadorDuplicados(cur)
        resultado = buscador.evaluar_coincidencias(
            titulo="Receta tradicional de empanadas de carne",
            headers=True,
            texto="Preparar la masa con harina y grasa vacuna, rellenar con carne picada a cuchillo."
        )

        assert resultado["encontrado"] is False
        assert "No se encontraron duplicados" in resultado["mensaje"]


@pytest.mark.integration
def test_umbral_combinado_embeddings_80_justo_arriba_y_justo_abajo(clean_db):
    """
    Regla: En la búsqueda semántica vectorial, el score total se calcula como
    (0.8 * sim_texto + 0.2 * sim_titulo). Si el score supera o empata el umbral requerido
    debe incluirse en los resultados, pero si queda por debajo debe excluirse.
    """
    texto_base = "Procedimiento para autorizar comprobantes de retención en Finnegans ERP mediante AFIP."
    titulo_base = "Autorización de Retenciones AFIP"

    # Generamos vectores reales con los modelos ONNX
    vec_tit = embedding_titulo(titulo_base)
    vec_txt = embedding_texto(texto_base)
    str_vec_tit = "[" + ",".join(str(f) for f in vec_tit) + "]"
    str_vec_txt = "[" + ",".join(str(f) for f in vec_txt) + "]"

    with clean_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articulos (id, titulo, url, texto, embedding_titulo, embedding_texto)
            VALUES (%s, %s, %s, %s, %s::vector, %s::vector);
            """,
            (
                506,
                titulo_base,
                "https://bc-dev.finneg.com/t/506",
                texto_base,
                str_vec_tit,
                str_vec_txt
            )
        )
        clean_db.commit()

        buscador = BuscadorDuplicados(cur)

        # 1. Búsqueda con el mismo texto y título: score_total ~ 1.0 (justo por encima de 0.80)
        coincidencias_arriba = buscador.buscar_en_embeddings(
            texto=texto_base,
            titulo=titulo_base,
            umbral=0.80
        )
        assert len(coincidencias_arriba) == 1
        art_id = coincidencias_arriba[0]["id"] if isinstance(coincidencias_arriba[0], dict) else coincidencias_arriba[0][0]
        assert art_id == 506

        # 2. Búsqueda con texto completamente disonante: similitud semántica baja (< 0.80)
        coincidencias_abajo = buscador.buscar_en_embeddings(
            texto="Instalación de cables de fibra óptica submarinos en el océano Pacífico.",
            titulo="Infraestructura de telecomunicaciones submarinas",
            umbral=0.80
        )
        assert len(coincidencias_abajo) == 0
