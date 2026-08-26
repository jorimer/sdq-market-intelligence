"""Solidez pondera por FAMILIA: un hecho, un voto.

**El defecto.** Los cinco indicadores de Solidez no son cinco hechos. `solvencia`,
`tier1_ratio` y `leverage` miden todos capital sobre ACTIVOS PONDERADOS POR RIESGO —cambian el
numerador entre patrimonio técnico y capital primario, y poco más—, así que el promedio simple
le daba a ese único hecho el **60 % de la dimensión**. Y cuando la entidad no tiene capital
secundario, dos de ellos son EXACTAMENTE el mismo número: 9 de 43 entidades al corte 2026-03.

Un lector razonable los leía como tres evidencias independientes de solidez.

**Lo que NO cambia**: los cinco indicadores se siguen calculando y publicando. Cambia cuántas
veces votan. Registrado en `shared/doctrine/changelog.yaml` con su impacto medido.
"""
import pytest

from modules.banking_score.scoring.engine import calculate_sub_components
from modules.banking_score.scoring.weights import SOLIDEZ_FAMILIAS, SOLIDEZ_INDICATORS


def _ind(**kw):
    return {k: {"score": v, "available": True} for k, v in kw.items()}


#: El caso REAL: Asociación Bonao al 2025-03-31, con los tres de capital altos y casi iguales.
_BONAO = _ind(solvencia=89.5, tier1_ratio=91.9, leverage=93.8,
              cobertura_provisiones=69.1, patrimonio_activos=67.3)


def test_el_capital_ponderado_deja_de_pesar_el_60_por_ciento():
    """Con el promedio simple, Bonao daba 82.32 — tres cuartas partes de eso eran capital."""
    simple = sum([89.5, 91.9, 93.8, 69.1, 67.3]) / 5
    assert round(simple, 2) == 82.32, "la línea base es el número publicado en el informe"
    nuevo = calculate_sub_components(_BONAO)["solidez"]
    assert nuevo < simple
    # (89.5+91.9+93.8)/3 = 91.73 · 69.1 · 67.3  →  promedio de las tres familias
    assert nuevo == pytest.approx((91.73 + 69.1 + 67.3) / 3, abs=0.02)


def test_los_TRES_de_capital_aportan_UN_voto():
    """La prueba directa: mover uno de los tres mueve menos que mover la cobertura."""
    base = calculate_sub_components(_BONAO)["solidez"]
    sube_capital = calculate_sub_components(
        dict(_BONAO, solvencia={"score": 99.5, "available": True}))["solidez"]
    sube_cobertura = calculate_sub_components(
        dict(_BONAO, cobertura_provisiones={"score": 79.1, "available": True}))["solidez"]
    assert (sube_capital - base) < (sube_cobertura - base), (
        "+10 en un ratio de capital no puede mover más que +10 en la cobertura: el capital "
        "es una familia de tres y la cobertura es una de una")


def test_una_familia_SIN_dato_se_omite_y_no_cuenta_cero():
    """Misma regla que entre sub-componentes: renormalizar sobre lo medido, nunca acreditar
    dato ausente. Contar cero convertiría un hueco en una penalización."""
    sin_cobertura = _ind(solvencia=80.0, tier1_ratio=80.0, leverage=80.0,
                         patrimonio_activos=60.0)
    assert calculate_sub_components(sin_cobertura)["solidez"] == 70.0


def test_solo_una_familia_disponible_devuelve_su_promedio():
    assert calculate_sub_components(
        _ind(solvencia=50.0, tier1_ratio=60.0, leverage=70.0))["solidez"] == 60.0


def test_sin_ningun_indicador_es_None_y_no_cero():
    assert calculate_sub_components({})["solidez"] is None


def test_un_indicador_NO_DISPONIBLE_no_arrastra_a_su_familia():
    inds = dict(_BONAO, leverage={"score": 0.0, "available": False})
    # La familia de capital pasa a ser el promedio de dos, no de tres con un cero.
    esperado = ((89.5 + 91.9) / 2 + 69.1 + 67.3) / 3
    assert calculate_sub_components(inds)["solidez"] == pytest.approx(esperado, abs=0.02)


# ── Que el mapa no se desincronice ─────────────────────────────────────

def test_toda_familia_cubre_indicadores_que_EXISTEN_en_solidez():
    de_familias = {k for _, keys in SOLIDEZ_FAMILIAS for k in keys}
    assert de_familias == set(SOLIDEZ_INDICATORS), (
        "el mapa de familias y la lista de indicadores de Solidez divergieron: "
        f"solo en familias={de_familias - set(SOLIDEZ_INDICATORS)}, "
        f"solo en la lista={set(SOLIDEZ_INDICATORS) - de_familias}")


def test_ninguna_familia_esta_vacia():
    """Una familia vacía sería un voto fantasma que nunca se emite."""
    vacias = [nombre for nombre, keys in SOLIDEZ_FAMILIAS if not keys]
    assert not vacias, f"familias sin indicadores: {vacias}"


def test_el_cambio_esta_en_el_CHANGELOG_de_metodologia():
    """Un cambio de vara que no se puede auditar no es un cambio anunciado: es una sorpresa
    en el próximo informe del cliente."""
    from shared.doctrine.changelog import cambios
    ids = {c["id"] for c in cambios("banking")}
    assert "2026-08-26-solidez-un-hecho-un-voto" in ids
