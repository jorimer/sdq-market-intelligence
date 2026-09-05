"""El test del falso positivo: una proyección sin backtest NO ancla.

El modo de falla más probable de este diseño no es que rechace de más — es que **acepte
todo**. `projection_is_admissible` devuelve `Tuple[bool, str]`, y una tupla no vacía es
siempre truthy: escribir

    return projection_is_admissible(self.projection)     # ← MAL

hace que toda señal proyectada quede anclada, con backtest o sin él, que es exactamente lo
contrario de lo que este bloque existe para lograr. Y no falla ruidosamente: falla dejando
pasar.

Por eso las aserciones son `is False` y no `not anchored`: `not` también sería verdadero para
un `0` o un `""`, y lo que se está fijando es que la propiedad devuelva un booleano de verdad
después de desempaquetar.
"""
import pytest

from shared.registry.projection import MIN_OOS
from shared.registry.signals import PROJECTED, REAL, RUBRIC, GAP, ProjectionMeta
from shared.research.models import SubQuestion
from shared.data.medida_de_pronostico import DLOG_PCT


def _meta(**cambios):
    base = dict(
        model_id="bridge_imae_pib.m2.v1", target_series="s", horizon="2026-Q4",
        as_of="2026-08-31", revision=0, point=3.9,
        intervals=((0.80, 3.1, 4.7), (0.90, 2.6, 5.2)),
        measure=DLOG_PCT,
        backtest_id="bridge_imae_pib.m2.v1|s|2026-Q4", oos_error=0.62, error_metric="rmse",
        n_oos=16, n_oos_overlapping=True,
        interval_coverage=((0.80, 0.78, 16), (0.90, 0.88, 16)),
    )
    base.update(cambios)
    return ProjectionMeta(**base)


@pytest.mark.parametrize("proyeccion,por_que", [
    (None, "sin metadato de proyección"),
    (_meta(backtest_id=""), "sin backtest_id"),
    (_meta(n_oos=MIN_OOS - 1), "con menos observaciones fuera de muestra que el mínimo"),
])
def test_una_proyeccion_que_no_pasa_el_gate_no_ancla(proyeccion, por_que):
    sq = SubQuestion(text="¿Cuánto crecerá el PIB en 2026-Q4?", state=PROJECTED,
                     projection=proyeccion)
    assert sq.anchored is False, (
        f"una proyección {por_que} quedó anclada: casi seguro se retornó la tupla de "
        "`projection_is_admissible` sin desempaquetar")


def test_una_proyeccion_con_backtest_si_ancla():
    sq = SubQuestion(text="¿Cuánto crecerá el PIB?", state=PROJECTED, projection=_meta())
    assert sq.anchored is True


@pytest.mark.parametrize("estado,esperado", [(REAL, True), (RUBRIC, True), (GAP, False)])
def test_los_tres_estados_de_siempre_no_cambian(estado, esperado):
    """Sumar un cuarto estado no puede mover a los otros tres."""
    assert SubQuestion(text="x", state=estado).anchored is esperado


def test_una_subpregunta_proyectada_sin_el_campo_no_revienta():
    """`projection` es opcional en el tipo: una `SubQuestion` construida sin él y marcada
    proyectada tiene que dar `False`, no `AttributeError`."""
    sq = SubQuestion(text="x", state=PROJECTED)
    assert sq.anchored is False
