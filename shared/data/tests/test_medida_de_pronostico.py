"""La medida del punto y cómo se realiza el observado.

Es el módulo que cierra la suposición que rompió el ledger: que `point` era directamente
comparable con el valor de `target_series`. No lo era — el punto es un Δlog en % (~0,4) y la
serie es el índice de volumen del PIB (~133).

Lo que se fija acá son las NEGATIVAS tanto como los aciertos: cada motivo por el que un
período no se puede realizar existe porque devolver 0,0 en su lugar produce un error
inventado del tamaño del pronóstico.
"""
import math

import pytest

from shared.data import medida_de_pronostico as med


# ── El vocabulario ──────────────────────────────────────────────────────────────────


def test_no_hay_medida_por_defecto():
    """Suponerle «nivel» a lo que no declaró nada es exactamente el defecto."""
    for invalida in (None, "", "porcentaje", "dlog"):
        with pytest.raises(ValueError, match="medida"):
            med.validar(invalida)


def test_las_declaradas_se_validan():
    assert [med.validar(m) for m in med.MEDIDAS] == list(med.MEDIDAS)


def test_toda_medida_declarada_tiene_etiqueta():
    """Una medida sin etiqueta no se puede nombrar en un texto, y el motivo de una negativa
    tiene que poder decirse."""
    assert set(med.ETIQUETAS) == set(med.MEDIDAS)


# ── Qué períodos hace falta leer ────────────────────────────────────────────────────


def test_un_nivel_necesita_UN_periodo_y_una_tasa_DOS():
    assert med.periodos_necesarios(med.LEVEL, "2026-Q3") == ("2026-Q3",)
    assert med.periodos_necesarios(med.DLOG_PCT, "2026-Q3") == ("2026-Q2", "2026-Q3")


def test_una_tasa_cruza_el_ano():
    assert med.periodos_necesarios(med.DLOG_PCT, "2026-Q1") == ("2025-Q4", "2026-Q1")


# ── La realización ──────────────────────────────────────────────────────────────────


def test_un_nivel_se_realiza_tal_cual():
    r = med.realizar(med.LEVEL, "2026-Q3", {"2026-Q3": 133.5})
    assert r.valor == 133.5 and r.motivo == ""


def test_una_tasa_se_realiza_como_la_VARIACION_contra_el_anterior():
    r = med.realizar(med.DLOG_PCT, "2026-Q3", {"2026-Q2": 133.0, "2026-Q3": 133.5})
    assert r.valor == pytest.approx((math.log(133.5) - math.log(133.0)) * 100)


def test_sin_el_periodo_del_horizonte_no_hay_valor_y_SE_DICE():
    r = med.realizar(med.DLOG_PCT, "2026-Q3", {"2026-Q2": 133.0})
    assert r.valor is None and "2026-Q3" in r.motivo


def test_sin_el_periodo_ANTERIOR_no_hay_valor_y_SE_DICE():
    r = med.realizar(med.DLOG_PCT, "2026-Q3", {"2026-Q3": 133.5})
    assert r.valor is None and "2026-Q2" in r.motivo


def test_el_anterior_es_el_DE_CALENDARIO_y_no_el_que_haya():
    """La distinción que evita rotular una variación de dos trimestres como si fuera de uno.
    Con «el anterior disponible» esto devolvería 1,13 % y nadie se enteraría."""
    con_hueco = {"2026-Q1": 132.0, "2026-Q3": 133.5}          # falta Q2
    r = med.realizar(med.DLOG_PCT, "2026-Q3", con_hueco)
    assert r.valor is None, (
        f"se computó {r.valor} saltando el trimestre que falta: eso es una variación de dos "
        "trimestres publicada como si fuera de uno")
    assert "2026-Q2" in r.motivo


def test_un_valor_nulo_es_lo_mismo_que_no_tenerlo():
    """«El período existe con valor nulo» no es «llegó el dato»."""
    r = med.realizar(med.DLOG_PCT, "2026-Q3", {"2026-Q2": None, "2026-Q3": 133.5})
    assert r.valor is None and "2026-Q2" in r.motivo


def test_un_horizonte_RELATIVO_no_se_puede_realizar_como_tasa():
    """`+4T` no resuelve a un período de calendario, y una variación necesita contra qué
    medirse."""
    r = med.realizar(med.DLOG_PCT, "+4T", {"+4T": 133.5})
    assert r.valor is None and "calendario" in r.motivo


@pytest.mark.parametrize("medida, base", [(med.DLOG_PCT, "2026-Q2"), (med.YOY_PCT, "2025-Q3")])
def test_un_valor_no_positivo_no_admite_una_variacion_proporcional(medida, base):
    r = med.realizar(medida, "2026-Q3", {base: 0.0, "2026-Q3": 133.5})
    assert r.valor is None and "no positivo" in r.motivo


def test_nunca_devuelve_CERO_en_lugar_de_None():
    """Un 0,0 acá se lee como «el PIB no se movió» y produce un error inventado del tamaño
    del pronóstico. La brecha se declara."""
    for observado in ({}, {"2026-Q3": None}, {"2026-Q3": 133.5}):
        assert med.realizar(med.DLOG_PCT, "2026-Q3", observado).valor is None


# ── La serie entera ─────────────────────────────────────────────────────────────────


def test_la_serie_realizada_no_rellena_lo_que_no_puede():
    """El primer período de una serie no tiene anterior, y un hueco corta dos: el de después
    tampoco se puede realizar. Ninguno de los tres aparece — no se inventa un valor."""
    observado = {"2025-Q1": 130.0, "2025-Q2": 131.0, "2025-Q4": 133.0}
    realizada = med.serie_realizada(med.DLOG_PCT, observado)
    assert set(realizada) == {"2025-Q2"}


def test_la_serie_realizada_en_NIVEL_es_la_misma_serie():
    observado = {"2025-Q1": 130.0, "2025-Q2": 131.0}
    assert med.serie_realizada(med.LEVEL, observado) == observado


# ── La variación INTERANUAL ─────────────────────────────────────────────────────────
#
# El PIB entra al bloque del BVAR así y no como variación trimestral: el índice que publica
# el BCRD es la serie ORIGINAL, sin desestacionalizar, y su variación trimestre a trimestre
# va de −1,13 % (Q3) a +4,67 % (Q4) por puro calendario. Las dos medidas conviven en el
# ledger sobre la MISMA serie —el nowcast emite una, el BVAR la otra— y por eso la fila
# tiene que declarar cuál es la suya.


def test_una_interanual_necesita_el_mismo_periodo_del_ANO_ANTERIOR():
    assert med.periodos_necesarios(med.YOY_PCT, "2026-Q3") == ("2025-Q3", "2026-Q3")


def test_la_interanual_se_realiza_contra_el_ano_anterior_y_NO_contra_el_trimestre_previo():
    observado = {"2025-Q3": 128.0, "2026-Q2": 133.0, "2026-Q3": 133.5}
    yoy = med.realizar(med.YOY_PCT, "2026-Q3", observado)
    dlog = med.realizar(med.DLOG_PCT, "2026-Q3", observado)
    assert yoy.valor == pytest.approx((133.5 / 128.0 - 1) * 100)
    assert dlog.valor == pytest.approx((math.log(133.5) - math.log(133.0)) * 100)
    assert abs(yoy.valor - dlog.valor) > 3.0, (
        "las dos medidas dieron casi lo mismo sobre esta serie: el caso no distingue nada")


def test_sin_el_trimestre_DEL_ANO_ANTERIOR_no_se_puntua_aunque_esté_el_previo():
    """Tener el trimestre anterior no alcanza para una interanual, y confundirlos publica una
    tasa trimestral rotulada de anual."""
    r = med.realizar(med.YOY_PCT, "2026-Q3", {"2026-Q2": 133.0, "2026-Q3": 133.5})
    assert r.valor is None and "2025-Q3" in r.motivo


def test_la_serie_realizada_interanual_descarta_el_PRIMER_ANO():
    """Los cuatro primeros trimestres no tienen homólogo. No aparecen — no se rellenan."""
    observado = {f"{a}-Q{q}": 100.0 + i
                 for i, (a, q) in enumerate([(2025, 1), (2025, 2), (2025, 3), (2025, 4),
                                             (2026, 1), (2026, 2)])}
    realizada = med.serie_realizada(med.YOY_PCT, observado)
    assert set(realizada) == {"2026-Q1", "2026-Q2"}


def test_toda_medida_declarada_tiene_sufijo_y_lectura():
    """Una medida nueva que entre al vocabulario sin cómo decirse se publica como un número
    pelado, que es el defecto entero."""
    assert set(med.COMO_SE_LEE) == set(med.MEDIDAS)
    assert set(med.SUFIJO) == set(med.MEDIDAS)
