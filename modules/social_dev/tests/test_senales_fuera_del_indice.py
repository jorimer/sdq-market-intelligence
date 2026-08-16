"""Un tema ingerido que el índice no usa se publica igual — con peso 0 y solo si hay dato."""
import pytest

from modules.social_dev.products import SocialDevProduct
from shared.registry.signals import REAL, AxisRegistry, VariableSignal


def _idm(n=8, w=0.125):
    return [VariableSignal(key=f"v{i}", label=f"v{i}", state=REAL, weight=w,
                           real_fraction=1.0, value=1.0) for i in range(n)]


def test_una_señal_sin_peso_no_mueve_la_cobertura_del_eje():
    """La razón por la que se puede exponer sin dañar el gate de honestidad: la cobertura
    ponderada se computa sobre el peso, y un peso 0 no entra ni al numerador ni al
    denominador."""
    base = AxisRegistry(sector_key="social_dev", display_name="s", source="x", implemented=True,
                        signals=tuple(_idm()))
    extra = VariableSignal(key="poverty_extreme", label="Pobreza monetaria extrema", state=REAL,
                           weight=0.0, real_fraction=1.0, value=2.2)
    con = AxisRegistry(sector_key="social_dev", display_name="s", source="x", implemented=True,
                       signals=tuple(_idm()) + (extra,))
    assert con.coverage_real == base.coverage_real
    # Pero SÍ aparece en el conteo: es una variable real más que el eje publica.
    assert con.state_counts[REAL] == base.state_counts[REAL] + 1


def test_el_tema_esta_declarado_con_su_nota():
    label, dim, nota = SocialDevProduct._FUERA_DEL_INDICE["poverty_extreme"]
    assert "extrema" in label.lower()
    assert "No alimenta el índice" in nota, "el consumidor tiene que saber que no pondera"


def test_sin_dato_no_se_publica_la_señal():
    """Publicar la señal de un tema sin filas afirmaría que el eje mide algo que no mide."""
    assert SocialDevProduct(None).variable_signals()["signals"] == []
