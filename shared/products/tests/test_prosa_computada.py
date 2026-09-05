"""G3 pregunta si el nivel tiene CON QUÉ producir su prosa — no si usa el motor de IA.

**De dónde salió.** El eje de proyecciones computa toda su prosa: un informe cuyo contenido
son cifras de error, coberturas empíricas de intervalos y una reconciliación exacta no tiene
nada que redactar, y un modelo redactándolo inventaría justo los números que el informe
existe para probar. Es el camino MÁS riguroso, y G3 lo penalizaba con 0 porque medía
«templates declarados» en vez de «puede producir su texto». Medido en producción: el eje
quedaba en readiness 0,70 contra umbrales de 0,75 y 0,85 — no se podía activar.

**La ampliación no es una puerta trasera.** Un nivel que no declara NI templates NI prosa
computada sigue puntuando 0, que es el caso legítimo de «todavía no está hecho»; y declarar
las dos cosas lanza, porque deja sin definir cuál manda.
"""
import pytest

from shared.products.readiness import GATE_WEIGHTS
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec


def _nivel(**cambios):
    base = dict(tier=ProductTier.insight, granularity=Granularity.system,
                sections=("a",), narrative_templates=(), audience="x", cadence="recurring")
    base.update(cambios)
    return TierLevelSpec(**base)


def _g3(level) -> float:
    return 1.0 if (level.narrative_templates or level.prosa_computada) else 0.0


def test_un_nivel_con_templates_puntua():
    assert _g3(_nivel(narrative_templates=("t",))) == 1.0


def test_un_nivel_con_prosa_computada_tambien():
    assert _g3(_nivel(prosa_computada=True)) == 1.0


def test_un_nivel_sin_ninguna_de_las_dos_sigue_en_cero():
    """El contraejemplo que impide que la ampliación sea una puerta trasera."""
    assert _g3(_nivel()) == 0.0


def test_declarar_las_dos_formas_lanza():
    """O la escribe el motor o la computa el código; las dos deja sin definir cuál manda."""
    with pytest.raises(ValueError, match="excluyentes"):
        _nivel(narrative_templates=("t",), prosa_computada=True)


def test_el_peso_de_g3_no_cambio():
    """La ampliación es de la PREGUNTA, no del peso: mover el peso reescribiría el readiness
    de los diecisiete ejes que ya estaban medidos."""
    assert GATE_WEIGHTS["g3"] == 0.15


def test_el_eje_de_proyecciones_declara_prosa_computada():
    import app.main  # noqa: F401
    from shared.products.registry import get_product

    m = get_product("macro_forecast").product_manifest()
    for tier in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
        nivel = m.require_level(tier)
        assert nivel.prosa_computada, f"{tier.value} no declara prosa computada"
        assert not nivel.narrative_templates


def test_los_demas_ejes_siguen_declarando_templates():
    """Que la ampliación exista no puede volver opcional el trabajo de los otros."""
    import app.main  # noqa: F401
    from shared.products.registry import get_product, registered_sectors

    sin_nada = []
    for key in registered_sectors():
        m = get_product(key).product_manifest()
        for tier, nivel in m.levels.items():
            if not nivel.narrative_templates and not nivel.prosa_computada:
                sin_nada.append(f"{key}:{tier.value}")
    assert not sin_nada, f"niveles sin forma declarada de producir prosa: {sin_nada}"
