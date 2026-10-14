import pytest
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.services.validar_articulo import (
    validar_texto_y_estructura_post_duplicados,
)


# ==============================================================================
# TESTS FASE 2: validar_texto_y_estructura_post_duplicados
# ==============================================================================

TEXTO_VALIDO_LARGO = (
    "Para configurar el punto de venta de facturación electrónica en Finnegans, "
    "es necesario verificar que los parámetros de AFIP estén sincronizados. "
    "Primero ingresar al módulo de Ventas, luego seleccionar Configuración de Parámetros. "
    "Allí verificar el número de punto de venta asignado por el ente fiscal. "
    "Una vez confirmado, guardar los cambios y emitir un comprobante de prueba."
)  # >= 300 caracteres


def test_estructura_valida_completa():
    articulo = ArticuloSchema(
        id=10,
        titulo="Configuración de Punto de Venta",
        categoria_id=5,
        tags=[Tag(name="instructivo", slug="instructivo"), Tag(name="ventas", slug="ventas")],
        texto=TEXTO_VALIDO_LARGO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)
    assert res["status"] == "Listo"
    assert len(res["findings"]) == 0
    assert res["longitud_texto"] >= 300
    assert res["tags_count"] == 2


def test_texto_demasiado_corto_es_bloqueante():
    articulo = ArticuloSchema(
        id=11,
        titulo="Configuración",
        categoria_id=5,
        tags=[Tag(name="instructivo"), Tag(name="ventas")],
        texto="Texto muy breve con menos de trescientos caracteres."
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)
    assert res["status"] == "Pendiente"
    assert any(
        f["severity"] == "Bloqueante" and f["field"] == "texto" and "300" in f["description"]
        for f in res["findings"]
    )


def test_texto_con_marcador_indicar_es_bloqueante():
    texto_con_marcador = TEXTO_VALIDO_LARGO + " [Indicar ruta de acceso a la pantalla]"
    articulo = ArticuloSchema(
        id=12,
        titulo="Configuración de Parámetros",
        categoria_id=5,
        tags=[Tag(name="instructivo"), Tag(name="ventas")],
        texto=texto_con_marcador
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)
    assert res["status"] == "Pendiente"
    assert any(
        f["severity"] == "Bloqueante" and "[Indicar" in f["description"]
        for f in res["findings"]
    )


def test_falta_categoria_es_bloqueante():
    articulo = ArticuloSchema(
        id=13,
        titulo="Configuración de Parámetros",
        categoria_id=None,
        tags=[Tag(name="instructivo"), Tag(name="ventas")],
        texto=TEXTO_VALIDO_LARGO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)
    assert res["status"] == "Pendiente"
    assert any(
        f["severity"] == "Bloqueante" and f["field"] == "categoria_id"
        for f in res["findings"]
    )


def test_menos_de_dos_tags_es_bloqueante():
    articulo = ArticuloSchema(
        id=14,
        titulo="Configuración de Parámetros",
        categoria_id=5,
        tags=[Tag(name="instructivo")],
        texto=TEXTO_VALIDO_LARGO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)
    assert res["status"] == "Pendiente"
    assert any(
        f["severity"] == "Bloqueante" and f["field"] == "tags" and "al menos 2 tags" in f["description"].lower()
        for f in res["findings"]
    )


def test_falta_tag_de_plantilla_es_bloqueante():
    articulo = ArticuloSchema(
        id=15,
        titulo="Configuración de Parámetros",
        categoria_id=5,
        tags=[Tag(name="ventas"), Tag(name="facturacion")],
        texto=TEXTO_VALIDO_LARGO
    )
    res = validar_texto_y_estructura_post_duplicados(articulo)
    assert res["status"] == "Pendiente"
    assert any(
        f["severity"] == "Bloqueante" and "plantilla" in f["description"].lower()
        for f in res["findings"]
    )




