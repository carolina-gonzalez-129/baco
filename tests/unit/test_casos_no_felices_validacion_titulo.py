import pytest
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.services.validar_articulo import validar_texto_y_estructura_post_duplicados

TEXTO_VALIDO = (
    "Para configurar el punto de venta de facturación electrónica en Finnegans, "
    "es necesario verificar que los parámetros de AFIP estén sincronizados. "
    "Primero ingresar al módulo de Ventas, luego seleccionar Configuración de Parámetros. "
    "Allí verificar el número de punto de venta asignado por el ente fiscal. "
    "Una vez confirmado, guardar los cambios y emitir un comprobante de prueba."
)


@pytest.mark.xfail(
    reason="Regla de negocio: un artículo no puede publicarse con título vacío. El validador actual no audita el campo título.",
    strict=True
)
def test_titulo_vacio_debe_generar_hallazgo_bloqueante():
    """Regla: Todo artículo debe tener un título con contenido significativo; un título vacío es inválido."""
    articulo = ArticuloSchema(
        id=1,
        titulo="",
        categoria_id=5,
        tags=[Tag(name="instructivo"), Tag(name="ventas")],
        texto=TEXTO_VALIDO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)

    assert res["status"] == "Pendiente"
    assert any(
        f["severity"] == "Bloqueante" and f["field"] == "titulo"
        for f in res["findings"]
    ), "Debe registrarse un hallazgo bloqueante sobre el campo título"


@pytest.mark.xfail(
    reason="Regla de negocio: un título compuesto solo por espacios en blanco no es válido.",
    strict=True
)
def test_titulo_solo_espacios_debe_generar_hallazgo_bloqueante():
    """Regla: Un título compuesto exclusivamente de espacios o tabulaciones debe rechazarse."""
    articulo = ArticuloSchema(
        id=2,
        titulo="     \t  \n ",
        categoria_id=5,
        tags=[Tag(name="instructivo"), Tag(name="ventas")],
        texto=TEXTO_VALIDO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)

    assert res["status"] == "Pendiente"
    assert any(
        f["severity"] == "Bloqueante" and f["field"] == "titulo"
        for f in res["findings"]
    )


@pytest.mark.xfail(
    reason="Regla editorial Finnegans: los títulos no deben llevar punto final.",
    strict=True
)
def test_titulo_que_termina_en_punto_debe_requerir_ajuste_editorial():
    """Regla de estilo: Los títulos de la Base de Conocimiento no deben terminar con punto."""
    articulo = ArticuloSchema(
        id=3,
        titulo="Configuración de Parámetros de Facturación AFIP.",
        categoria_id=5,
        tags=[Tag(name="instructivo"), Tag(name="ventas")],
        texto=TEXTO_VALIDO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)

    assert any(
        f["field"] == "titulo" and "punto" in f["description"].lower()
        for f in res["findings"]
    ), "Debe sugerirse remover el punto final del título"


def test_titulo_con_acentos_mayusculas_y_emojis_es_admitido():
    """Regla: Títulos con mayúsculas, acentuación y símbolos técnicos válidos deben procesarse normalmente."""
    articulo = ArticuloSchema(
        id=4,
        titulo="¿Cómo CONFIGURAR Liquidación de Sueldos & Jornales (AFIP)? 🚀",
        categoria_id=5,
        tags=[Tag(name="instructivo"), Tag(name="sueldos")],
        texto=TEXTO_VALIDO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)

    assert res["status"] == "Listo"
    assert res["titulo"] == "¿Cómo CONFIGURAR Liquidación de Sueldos & Jornales (AFIP)? 🚀"


@pytest.mark.xfail(
    reason="Regla de negocio: títulos con más de 255 caracteres exceden el límite admisible.",
    strict=True
)
def test_titulo_excesivamente_largo_debe_generar_hallazgo():
    """Regla: Títulos que exceden los 255 caracteres deben ser señalados para síntesis editorial."""
    titulo_largo = "Configuración de " + ("parámetros adicionales y comprobantes fiscales de " * 8)
    assert len(titulo_largo) > 255

    articulo = ArticuloSchema(
        id=5,
        titulo=titulo_largo,
        categoria_id=5,
        tags=[Tag(name="instructivo"), Tag(name="ventas")],
        texto=TEXTO_VALIDO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)

    assert any(
        f["field"] == "titulo" and ("largo" in f["description"].lower() or "longitud" in f["description"].lower())
        for f in res["findings"]
    )
