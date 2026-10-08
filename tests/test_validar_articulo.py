import pytest
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.services.validar_articulo import (
    validar_titulo_pre_duplicados,
    validar_texto_y_estructura_post_duplicados,
)


# ==============================================================================
# TESTS FASE 1: validar_titulo_pre_duplicados
# ==============================================================================

def test_titulo_valido():
    articulo = ArticuloSchema(id=1, titulo="Configurar facturación electrónica en AFIP")
    res = validar_titulo_pre_duplicados(articulo)
    assert res["apto_para_deduplicacion"] is True
    assert res["titulo_sanitizado"] == "Configurar facturación electrónica en AFIP"
    assert len(res["findings"]) == 0


def test_titulo_termina_con_punto_agrega_finding_y_sanitiza():
    """Un artículo NUNCA puede terminar con un punto. Debe registrarse el finding y eliminarse el punto."""
    articulo = ArticuloSchema(id=2, titulo="Emitir factura de crédito electrónica.")
    res = validar_titulo_pre_duplicados(articulo)
    assert res["titulo_sanitizado"] == "Emitir factura de crédito electrónica"
    assert any(
        f["field"] == "titulo" and "punto final" in f["description"].lower()
        for f in res["findings"]
    )


def test_titulo_vacio_o_sin_titulo_es_bloqueante():
    for caso in ["", "   ", "Sin título", "sin título"]:
        articulo = ArticuloSchema(id=3, titulo=caso)
        res = validar_titulo_pre_duplicados(articulo)
        assert res["apto_para_deduplicacion"] is False
        assert any(f["severity"] == "Bloqueante" for f in res["findings"])


def test_titulo_inicia_con_como_requiere_ajuste():
    articulo = ArticuloSchema(id=4, titulo="Cómo hacer para cancelar un recibo de cobranza")
    res = validar_titulo_pre_duplicados(articulo)
    assert res["apto_para_deduplicacion"] is True  # No es bloqueante, pero requiere ajuste
    assert any(
        f["severity"] == "Requiere ajuste" and "Cómo" in f["description"]
        for f in res["findings"]
    )


def test_titulo_con_error_sin_comillas_requiere_ajuste():
    articulo = ArticuloSchema(id=5, titulo="Corregir error de validación en asiento")
    res = validar_titulo_pre_duplicados(articulo)
    assert any(
        f["severity"] == "Requiere ajuste" and "Error" in f["description"]
        for f in res["findings"]
    )


def test_titulo_con_error_entre_comillas_es_valido():
    articulo = ArticuloSchema(id=6, titulo='Resolver mensaje: "Error de conexión con AFIP"')
    res = validar_titulo_pre_duplicados(articulo)
    assert not any("sin un mensaje literal" in f["description"] for f in res["findings"])


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
