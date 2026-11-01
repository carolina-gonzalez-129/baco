import pytest

from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.services.validar_articulo import (
    sanitizar_borrador,
    validar_texto_y_estructura_post_duplicados,
)

TEXTO_VALIDO_LARGO = (
    "Para configurar el punto de venta de facturación electrónica en Finnegans, "
    "es necesario verificar que los parámetros de AFIP estén sincronizados. "
    "Primero ingresar al módulo de Ventas, luego seleccionar Configuración de Parámetros. "
    "Allí verificar el número de punto de venta asignado por el ente fiscal. "
    "Una vez confirmado, guardar los cambios y emitir un comprobante de prueba."
)


def _crear_articulo(titulo: str, texto: str = TEXTO_VALIDO_LARGO) -> ArticuloSchema:
    return ArticuloSchema(
        id=1,
        titulo=titulo,
        categoria_id=5,
        tags=[Tag(name="instructivo", slug="instructivo"), Tag(name="ventas", slug="ventas")],
        texto=texto,
    )


def test_titulo_como_emitir_factura_no_genera_hallazgo_formula_redundante():
    """Verifica que un título que comienza con 'Cómo emitir una factura' ya NO genere hallazgo de fórmula redundante."""
    articulo = _crear_articulo("Cómo emitir una factura")
    res = validar_texto_y_estructura_post_duplicados(articulo)

    hallazgos_titulo = [f for f in res["findings"] if f["field"] == "titulo"]
    assert not any("redundante" in f["description"].lower() or "cómo" in f["description"].lower() for f in hallazgos_titulo)
    assert not any(f["field"] == "titulo" for f in res["findings"])


def test_titulo_con_error_sin_comillas_no_genera_hallazgo():
    """Verifica que un título que contiene la palabra 'Error' sin comillas ya NO genere hallazgo de sugerencia."""
    articulo = _crear_articulo("Error 404 en sincronización AFIP de ventas")
    res = validar_texto_y_estructura_post_duplicados(articulo)

    hallazgos_error = [
        f for f in res["findings"]
        if f["field"] == "titulo" and "error" in f["description"].lower()
    ]
    assert len(hallazgos_error) == 0


def test_sanitizar_borrador_sigue_quitando_prefijo_como_del_titulo():
    """Verifica que sanitizar_borrador continúe eliminando el prefijo 'Cómo' del título de forma determinística."""
    res = sanitizar_borrador(texto=TEXTO_VALIDO_LARGO, titulo="Cómo emitir una factura")
    assert res["titulo_sanitizado"] == "Emitir una factura"
    assert not res["titulo_sanitizado"].lower().startswith("cómo")


def test_tickets_siguen_generando_hallazgos():
    """Verifica que referencias a tickets o incidentes internos sigan generando su hallazgo correspondiente."""
    texto_con_ticket = TEXTO_VALIDO_LARGO + " Ver seguimiento en Ticket #45892."
    articulo = _crear_articulo("Configuración de Parámetros AFIP", texto=texto_con_ticket)
    res = validar_texto_y_estructura_post_duplicados(articulo)

    assert any(
        f["field"] == "texto" and "tickets" in f["description"].lower()
        for f in res["findings"]
    )


def test_urls_internas_siguen_generando_hallazgos():
    """Verifica que URLs de entornos internos o pruebas sigan generando hallazgos bloqueantes."""
    texto_con_url = TEXTO_VALIDO_LARGO + " Probar en http://dev-erp.finneg.com/app antes de publicar."
    articulo = _crear_articulo("Configuración de Parámetros AFIP", texto=texto_con_url)
    res = validar_texto_y_estructura_post_duplicados(articulo)

    assert any(
        f["severity"] == "Bloqueante" and ("internos" in f["description"].lower() or "url" in f["description"].lower())
        for f in res["findings"]
    )


def test_ips_privadas_siguen_generando_hallazgos():
    """Verifica que IPs privadas en URLs sigan generando hallazgos bloqueantes."""
    texto_con_ip = TEXTO_VALIDO_LARGO + " Conectar al servidor en http://192.168.1.50:8080/erp directamente."
    articulo = _crear_articulo("Configuración de Parámetros AFIP", texto=texto_con_ip)
    res = validar_texto_y_estructura_post_duplicados(articulo)

    assert any(
        f["severity"] == "Bloqueante" and "ips privadas" in f["description"].lower()
        for f in res["findings"]
    )
