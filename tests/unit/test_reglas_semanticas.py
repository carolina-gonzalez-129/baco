from unittest.mock import MagicMock

from baco.server.services.reglas_semanticas import (
    detectar_jurisdiccion,
    normalizar_con_postgres,
    son_semanticas_divergentes,
)


def test_detectar_jurisdiccion_acepta_texto_y_tokens():
    assert detectar_jurisdiccion("Configurar comprobantes para AFIP") == "AR"
    assert detectar_jurisdiccion({"sunat", "facturación"}) == "PE"
    assert detectar_jurisdiccion("procedimiento general") is None


def test_normalizar_con_postgres_devuelve_valor_de_tupla_y_dict():
    cur = MagicMock()
    cur.fetchone.side_effect = [("texto normalizado",), {"normalizar_texto": "texto desde dict"}]

    assert normalizar_con_postgres(cur, "Texto") == "texto normalizado"
    assert normalizar_con_postgres(cur, "Otro texto") == "texto desde dict"
    assert normalizar_con_postgres(cur, "") == ""
    assert cur.execute.call_count == 2


def test_normalizar_con_postgres_devuelve_vacio_si_no_hay_fila():
    cur = MagicMock()
    cur.fetchone.return_value = None

    assert normalizar_con_postgres(cur, "Texto") == ""


def test_son_semanticas_divergentes_detecta_jurisdicciones_distintas():
    assert son_semanticas_divergentes(
        "configurar facturacion argentina",
        "configurar facturacion uruguay",
    )
    assert not son_semanticas_divergentes(
        "configurar facturacion argentina",
        "configurar facturacion argentina",
    )


def test_son_semanticas_divergentes_detecta_circuitos_opuestos():
    assert son_semanticas_divergentes(
        "alta de proveedores",
        "alta de clientes ventas",
    )
    assert not son_semanticas_divergentes("", "contenido")


def test_son_semanticas_divergentes_detecta_versiones_y_fases():
    assert son_semanticas_divergentes(
        "configurar retenciones nivel 1",
        "configurar retenciones nivel 2",
    )
    assert son_semanticas_divergentes(
        "facturacion - diseño",
        "facturacion - ejecución",
    )

def test_siglas_ambiguas_sin_set_solo_en_mayusculas():
    # "sin"/"set" como palabras comunes no son jurisdicción
    assert detectar_jurisdiccion("facturas sin cae pendientes") == "AR"  # por "cae"
    assert detectar_jurisdiccion("remitos sin stock") is None
    assert detectar_jurisdiccion("set de datos de prueba") is None
    # Como siglas en el texto original (mayúsculas) sí cuentan
    assert detectar_jurisdiccion("libro de ventas", "Libro de ventas SIN") == "BO"
    assert detectar_jurisdiccion("declaracion jurada", "Declaración jurada SET") == "PY"
    assert detectar_jurisdiccion("remitos sin stock", "Remitos sin stock") is None


def test_sin_en_texto_no_descarta_duplicado_real():
    # Antes: "sin" en el texto del candidato lo marcaba BO y se descartaba contra AFIP (AR)
    assert son_semanticas_divergentes(
        "configurar comprobantes electronicos",
        "configurar comprobantes electronicos afip",
        cand_texto="pasos para emitir sin errores",
        cons_texto="Pasos para emitir comprobantes",
    ) is False


def test_sigla_sin_en_titulo_raw_sigue_separando_paises():
    assert son_semanticas_divergentes(
        "libro de ventas sin", "libro de ventas sunat",
        cand_raw="Libro de ventas SIN", cons_raw="Libro de ventas SUNAT",
    ) is True
