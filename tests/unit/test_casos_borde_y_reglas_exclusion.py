import pytest
from baco.server.db.ingesta import generar_slug, normalizar_articulo, tag_id_sintetico
from baco.server.services.embeddings import limpiar_suave, truncar_1000, FUNCIONES_LIMPIEZA_SUAVE
from baco.server.services.reglas_semanticas import (
    detectar_jurisdiccion,
    son_semanticas_divergentes,
)


# ===========================================================================
# 1. Casos borde de Normalización y Limpieza
# ===========================================================================

def test_limpiar_suave_acentos_mayusculas_y_simbolos():
    """Verifica que limpiar_suave preserve mayúsculas, tildes y puntuación estructural."""
    entrada = "  ¡ATENCIÓN! ¿Cómo configurar Facturación Electrónica (AFIP) en Finnegans?  "
    salida = limpiar_suave(entrada)
    assert salida == "¡ATENCIÓN! ¿Cómo configurar Facturación Electrónica (AFIP) en Finnegans?"


def test_limpiar_suave_texto_vacio_o_solo_espacios_retorna_vacio():
    """Textos vacíos o compuestos únicamente de espacios/tabs/saltos deben normalizarse a vacío."""
    assert limpiar_suave("") == ""
    assert limpiar_suave("   \t  \n  ") == ""
    assert limpiar_suave(None) == ""


def test_limpiar_suave_saltos_de_linea_invisibles_y_caracteres_especiales():
    """
    Caso real de discrepancia de hashes en Discourse:
    Saltos de línea múltiples (\r\n, \n\n\n) y espacios no rompibles (NBSP \u00a0 / zero-width).
    """
    entrada_con_invisibles = "Línea 1\r\n\r\n\r\n   Línea 2\u00a0con\u200bnbsp   \n\nLínea 3"
    salida = limpiar_suave(entrada_con_invisibles)
    # Debe colapsar los espacios repetidos a un solo espacio y quitar residuos
    assert "  " not in salida
    assert salida.startswith("Línea 1")
    assert salida.endswith("Línea 3")


def test_truncar_1000_casos_borde():
    """Comprueba el corte en 1000 caracteres respetando límites de palabras."""
    # Texto corto: intacto
    corto = "Texto de 50 caracteres para probar el truncado."
    assert truncar_1000(corto) == corto

    # Texto de exactamente 1000 caracteres
    exacto_1000 = "a" * 1000
    assert len(truncar_1000(exacto_1000)) == 1000

    # Texto largo: corta sin partir la última palabra
    largo = ("palabra " * 150).strip()  # > 1000 chars
    truncado = truncar_1000(largo)
    assert len(truncado) <= 1000
    assert not truncado.endswith(" ")
    # La última palabra debe estar completa ("palabra")
    assert truncado.split()[-1] == "palabra"


def test_generar_slug_casos_borde():
    """Verifica que el slug remueva acentos y caracteres especiales sin romper."""
    assert generar_slug("Gestión de Cobranzas & Pagos 2026!") == "gestion-de-cobranzas--pagos-2026"
    assert generar_slug("¿Cómo emitir comprobante?") == "como-emitir-comprobante"
    assert generar_slug("") == ""
    assert generar_slug(None) == ""


def test_tag_id_sintetico_es_negativo_y_consistente():
    """El ID sintético debe ser siempre negativo y estrictamente determinista para el mismo slug."""
    id1 = tag_id_sintetico("facturacion-electronica")
    id2 = tag_id_sintetico("facturacion-electronica")
    id3 = tag_id_sintetico("ventas")

    assert id1 < 0
    assert id1 == id2
    assert id1 != id3


# ===========================================================================
# 2. Reglas de Exclusión con Pares Reales de la Base
# ===========================================================================

def test_exclusion_peru_vs_mexico():
    """Par real: Retenciones y facturación SUNAT (PE) vs SAT (MX) deben ser divergentes."""
    cand = "configuracion de detracciones sunat ruc"
    cons = "configuracion de cfdi sat mexico"
    assert son_semanticas_divergentes(cand, cons) is True


def test_exclusion_compras_vs_ventas():
    """Par real: Circuitos opuestos compras/proveedores vs ventas/clientes deben ser divergentes."""
    cand = "alta y administracion de facturas de proveedores compras"
    cons = "alta y administracion de facturas de clientes ventas"
    assert son_semanticas_divergentes(cand, cons) is True


def test_exclusion_cobros_vs_pagos():
    """Par real: Circuito de cobranzas vs circuito de pagos deben ser divergentes."""
    cand = "circuito de ingreso y cobros de clientes"
    cons = "circuito de egreso y pagos a proveedores"
    assert son_semanticas_divergentes(cand, cons) is True


def test_exclusion_retenciones_vs_percepciones():
    """Par real: Régimen de retenciones vs percepciones deben ser divergentes."""
    cand = "calculo automatico de retenciones iibb arba"
    cons = "calculo automatico de percepciones iibb arba"
    assert son_semanticas_divergentes(cand, cons) is True


def test_exclusion_fases_proyecto():
    """Par real: Fases de implementación de Finnegans (diseño vs ejecución)."""
    cand = "implementacion erp - diseño"
    cons = "implementacion erp - ejecución"
    assert son_semanticas_divergentes(cand, cons) is True


def test_pares_equivalentes_no_divergen():
    """Comprueba que artículos de la misma jurisdicción y mismo circuito NO sean marcados como divergentes."""
    cand = "configuracion de factura electronica afip argentina"
    cons = "instructivo para facturacion electronica afip argentina"
    assert son_semanticas_divergentes(cand, cons) is False
