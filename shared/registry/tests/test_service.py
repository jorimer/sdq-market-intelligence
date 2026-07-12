"""Tests del agregador resiliente ``build_data_registry`` (con productos simulados)."""
from dataclasses import dataclass
from typing import Tuple

import shared.registry.service as service
from shared.registry.signals import GAP, REAL, VariableSignal


@dataclass
class _Entry:
    sector_key: str
    display_name: str
    source: str


@dataclass(frozen=True)
class _DataHealth:
    coverage: float
    sources: Tuple[str, ...] = ()
    cadence: str = "annual"
    detail: str = ""
    freshness_days: int = None


class _RichProduct:
    """Producto que SÍ expone variable_signals."""
    def variable_signals(self):
        return {"period": "2025", "signals": [
            VariableSignal(key="a", label="A", state=REAL, weight=1.0, source="BCRD"),
        ]}


class _PoorProduct:
    """Producto sin variable_signals → debe degradar a data_signals."""
    def data_signals(self):
        return _DataHealth(coverage=0.7, sources=("BCRD",), detail="algo")


class _BrokenProduct:
    """Producto cuya lectura revienta → debe degradar sin tumbar el registro."""
    def variable_signals(self):
        raise RuntimeError("tabla ausente")


def _patch_catalog(monkeypatch, mapping):
    """mapping: sector_key -> product|None (None = no implementado)."""
    entries = [_Entry(k, k.title(), "FuenteX") for k in mapping]
    monkeypatch.setattr(service, "PRODUCT_CATALOG", entries)
    monkeypatch.setattr(service, "is_implemented", lambda sk: mapping.get(sk) is not None)
    monkeypatch.setattr(service, "get_product", lambda sk, db=None: mapping.get(sk))


def test_rich_product_surfaces_variable_signals(monkeypatch):
    _patch_catalog(monkeypatch, {"rich": _RichProduct()})
    reg = service.build_data_registry(db=None)
    axis = reg.axes[0]
    assert axis.implemented and not axis.degraded
    assert axis.period == "2025"
    assert axis.signals[0].key == "a"
    assert axis.coverage_real == 1.0


def test_poor_product_degrades_honestly(monkeypatch):
    _patch_catalog(monkeypatch, {"poor": _PoorProduct()})
    reg = service.build_data_registry(db=None)
    axis = reg.axes[0]
    assert axis.implemented and axis.degraded
    # cobertura anclada al coverage real de la fuente (0.7), no inventada.
    assert axis.coverage_real == 0.7
    assert "no expuesta" in axis.signals[0].note


def test_unimplemented_axis_is_declared_not_fabricated(monkeypatch):
    _patch_catalog(monkeypatch, {"missing": None})
    reg = service.build_data_registry(db=None)
    axis = reg.axes[0]
    assert not axis.implemented
    assert axis.signals == ()
    assert axis.coverage_real == 0.0


def test_broken_product_does_not_sink_registry(monkeypatch):
    _patch_catalog(monkeypatch, {"broken": _BrokenProduct(), "rich": _RichProduct()})
    reg = service.build_data_registry(db=None)
    by_key = {a.sector_key: a for a in reg.axes}
    assert by_key["broken"].degraded  # degradó solo ese eje
    assert by_key["rich"].coverage_real == 1.0  # el otro sobrevive
