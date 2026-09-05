"""Una proyección lleva su MEDIDA, o el número se lee como lo que no es.

El ledger ya declara en qué medida está el punto que guarda (`ForecastLog.measure`), porque
puntuar una tasa contra un nivel daba un error del tamaño del índice. Pero la declaración
moría en la puerta del ledger: `ProjectionMeta` no la transportaba, y todo lo que lee una
proyección volvía a adivinar la unidad.

Lo que se publicaba: la señal proyectada del eje macro decía
«bcrd.xls.pib_2018.serie_original_indice · proyección 2026-Q3» con valor **0,38** — el valor
es una VARIACIÓN en % y la etiqueta nombra una serie que es un ÍNDICE DE VOLUMEN (~133). Y la
frase de procedencia decía «con intervalo de 80 % entre 3.1 y 4.7», dos números sin unidad.

Es «el SUJETO viaja con el número» aplicado a la unidad: quien recibe 0,38 no tiene cómo
saber que no es un nivel.
"""
import pytest

from shared.data import medida_de_pronostico as med
from shared.registry.projection import projection_is_admissible
from shared.registry.provenance import projection_sentence
from shared.registry.signals import PROJECTED, AxisRegistry, ProjectionMeta, VariableSignal

SERIE = "bcrd.xls.pib_2018.serie_original_indice"


def _meta(**cambios):
    base = dict(
        model_id="bridge_imae_pib.m2.v1", target_series=SERIE, horizon="2026-Q4",
        as_of="2026-09-30", revision=0, point=3.9, measure=med.DLOG_PCT,
        intervals=((0.80, 3.1, 4.7),), backtest_id="b", oos_error=0.6, error_metric="rmse",
        n_oos=34, n_oos_overlapping=True, interval_coverage=((0.80, 0.76, 34),))
    base.update(cambios)
    return ProjectionMeta(**base)


# ── El tipo la transporta ───────────────────────────────────────────────────────────


def test_la_meta_tiene_donde_declarar_la_medida():
    assert _meta().measure == med.DLOG_PCT


def test_la_medida_NO_tiene_valor_por_defecto():
    """Sin default, por la misma razón que en `ledger.registrar`: un default reintroduce la
    suposición, y el que se equivoca nunca es el que la escribe a mano."""
    faltante = {k: v for k, v in dict(
        model_id="m", target_series=SERIE, horizon="2026-Q4", as_of="2026-09-30",
        revision=0, point=3.9, intervals=((0.80, 3.1, 4.7),), backtest_id="b",
        oos_error=0.6, error_metric="rmse", n_oos=34, n_oos_overlapping=True).items()}
    with pytest.raises(TypeError, match="measure"):
        ProjectionMeta(**faltante)


# ── El gate la exige ────────────────────────────────────────────────────────────────


def test_una_proyeccion_SIN_medida_no_ancla():
    """Igual que el solapamiento: se declara, no se supone. Un punto cuya unidad nadie
    declaró no puede sostener una afirmación."""
    ok, motivo = projection_is_admissible(_meta(measure=""))
    assert not ok and "medida" in motivo.lower(), motivo


def test_una_medida_INVENTADA_no_ancla():
    ok, motivo = projection_is_admissible(_meta(measure="porcentaje"))
    assert not ok and "porcentaje" in motivo, motivo


def test_con_la_medida_declarada_SI_ancla():
    """El contraejemplo. Sin él, un gate que rechazara todo pasaría los dos de arriba."""
    ok, motivo = projection_is_admissible(_meta())
    assert ok, motivo


# ── La prosa compartida la dice ─────────────────────────────────────────────────────


def _eje(**cambios):
    return AxisRegistry(
        sector_key="macro", display_name="Macro", source="BCRD", implemented=True,
        signals=(VariableSignal(key="pib", label="PIB real", state=PROJECTED, weight=1.0,
                                projection=_meta(**cambios)),))


def test_la_frase_de_procedencia_dice_en_QUE_UNIDAD_esta_la_banda():
    """«entre 3.1 y 4.7» sin unidad se lee como el nivel del índice."""
    frase = projection_sentence(_eje())
    assert med.COMO_SE_LEE[med.DLOG_PCT] in frase, (
        f"la frase publica la banda sin decir en qué unidad está: {frase}")


def test_la_frase_de_procedencia_tambien_trae_EL_PUNTO():
    """Publicaba la banda y no la estimación central. Quien lee «entre 3,1 y 4,7» tiene que
    deducir el punto, y el punto es la cifra que después se cita."""
    assert "3.9" in projection_sentence(_eje())


def test_un_NIVEL_se_lee_distinto_de_una_TASA():
    """Si las dos medidas produjeran el mismo texto, el campo no estaría haciendo nada."""
    tasa = projection_sentence(_eje())
    nivel = projection_sentence(_eje(measure=med.LEVEL))
    assert tasa != nivel
    assert med.COMO_SE_LEE[med.LEVEL] in nivel
