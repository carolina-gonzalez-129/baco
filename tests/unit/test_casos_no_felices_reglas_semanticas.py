import pytest
from baco.server.services.reglas_semanticas import son_semanticas_divergentes


def test_jurisdicciones_distintas_ar_uy_pe_no_son_duplicados():
    """
    Regla: Artículos con temas idénticos pero aplicables a países/jurisdicciones distintas
    (AR / UY / PE / CO / etc.) son semánticamente divergentes y NO deben tratarse como duplicados.
    """
    # Argentina (AFIP) vs Uruguay (DGI)
    assert son_semanticas_divergentes(
        cand_normalizado="facturacion electronica afip argentina",
        cons_normalizada="facturacion electronica dgi uruguay"
    ) is True, "AR vs UY deben ser divergentes"

    # Argentina (ARBA / IIBB) vs Perú (SUNAT / Detracciones)
    assert son_semanticas_divergentes(
        cand_normalizado="calculo de retenciones iibb arba",
        cons_normalizada="calculo de detracciones sunat peru"
    ) is True, "AR vs PE deben ser divergentes"

    # Uruguay (DGI) vs Perú (SUNAT)
    assert son_semanticas_divergentes(
        cand_normalizado="comprobantes fiscales dgi uruguay",
        cons_normalizada="comprobantes fiscales sunat peru"
    ) is True, "UY vs PE deben ser divergentes"


@pytest.mark.xfail(
    reason="Regla de negocio: 'Nivel 1' vs 'Nivel 2' representan etapas o profundidades distintas. "
           "La función son_semanticas_divergentes exige len(palabras_cand & palabras_cons) >= 3, "
           "por lo que falla para títulos breves como 'Capacitación Nivel 1' vs 'Capacitación Nivel 2'.",
    strict=True
)
def test_titulos_que_difieren_en_nivel_1_vs_nivel_2_no_son_duplicados():
    """
    Regla: Artículos que difieren en nivel de capacitación (Nivel 1 vs Nivel 2) o versión de release
    tratan contenidos distintos y deben ser marcados como divergentes (no duplicados).
    """
    # Título breve donde únicamente cambia el nivel formativo
    cand = "capacitacion nivel 1"
    cons = "capacitacion nivel 2"

    assert son_semanticas_divergentes(
        cand_normalizado=cand,
        cons_normalizada=cons
    ) is True, "Nivel 1 y Nivel 2 no son duplicados"


def test_fases_proyecto_diseno_vs_ejecucion_no_son_duplicados():
    """
    Regla: Fases distintas del ciclo de vida de un proyecto ERP (Diseño vs Ejecución vs Cierre)
    son semánticamente divergentes y no deben colisionar como duplicados.
    """
    cand_tit = "implementacion erp finnegans - diseño"
    cons_tit = "implementacion erp finnegans - ejecución"

    assert son_semanticas_divergentes(
        cand_normalizado="implementacion erp finnegans diseno",
        cons_normalizada="implementacion erp finnegans ejecucion",
        cand_raw=cand_tit,
        cons_raw=cons_tit
    ) is True, "Fases de proyecto Diseño vs Ejecución deben ser divergentes"


def test_falso_positivo_nivel_1_en_texto_no_relacionado_no_debe_divergir_por_regla_de_numeros():
    """
    Regla: La regla de números/niveles únicamente debe aplicar cuando los títulos son casi idénticos
    y solo difieren en el número. Textos totalmente no relacionados NO deben considerarse divergentes
    por el mecanismo de niveles sino descartarse por las demás capas de similitud.
    """
    cand = "modulo de facturacion electronica afip nivel 1"
    cons = "liquidacion de haberes docentes convenios colectivos"

    # No son divergentes por la regla de números/niveles porque no comparten la estructura de palabras base
    assert son_semanticas_divergentes(
        cand_normalizado=cand,
        cons_normalizada=cons
    ) is False
