"""Tests de las secciones estándar auto-generadas (Metodología, Fuentes)."""
from shared.products import ProductTier
from shared.products.contract import DataHealth, ValidationState
from shared.products.report_sections import (
    METHODOLOGY_KEY,
    SOURCES_KEY,
    standard_sections,
)


class _FakeProduct:
    sector_key = "x"

    def data_signals(self) -> DataHealth:
        return DataHealth(coverage=0.9, freshness_days=120, cadence="annual",
                          sources=("BCRD", "ONE"), detail="ITT 93.0 (Fuerte)")

    def validation_state(self) -> ValidationState:
        return ValidationState(approved=True, score=0.55, notes="Índice preliminar (sin backtest).")


def test_pulse_has_no_standard_sections():
    # Pulse queda lean (teaser); no se le inyecta metodología/fuentes.
    assert standard_sections(_FakeProduct(), ProductTier.pulse) == {}


def test_insight_has_methodology_not_sources():
    s = standard_sections(_FakeProduct(), ProductTier.insight)
    assert METHODOLOGY_KEY in s and SOURCES_KEY not in s
    md = s[METHODOLOGY_KEY]
    assert "BCRD" in md and "ONE" in md          # fuentes
    assert "90%" in md                            # cobertura
    assert "120 días" in md                       # frescura
    assert "preliminar" in md.lower()             # validación honesta


def test_deep_has_methodology_and_sources():
    s = standard_sections(_FakeProduct(), ProductTier.deep_dive)
    assert METHODOLOGY_KEY in s and SOURCES_KEY in s
    assert "- BCRD" in s[SOURCES_KEY] and "- ONE" in s[SOURCES_KEY]


def test_defensive_when_signals_raise():
    class _Bad:
        sector_key = "x"

        def data_signals(self):
            raise RuntimeError("no db")

        def validation_state(self):
            raise RuntimeError("no db")

    s = standard_sections(_Bad(), ProductTier.deep_dive)  # no debe propagar
    assert METHODOLOGY_KEY in s and SOURCES_KEY in s


# ─── Glosario automático (tier-gated igual que metodología) ────────────────────

def test_glossary_titles_registered():
    from shared.products.report_sections import GLOSSARY_KEY, STANDARD_SECTION_TITLES
    assert STANDARD_SECTION_TITLES[GLOSSARY_KEY] == "Glosario"


def test_glossary_section_pulse_is_lean():
    from shared.products.report_sections import glossary_section
    assert glossary_section("El ROA del sistema mejora.", ProductTier.pulse) == {}


def test_glossary_section_insight_detects_terms():
    from shared.products.report_sections import GLOSSARY_KEY, glossary_section
    out = glossary_section("El ROA mejora y el HHI baja.", ProductTier.insight)
    assert GLOSSARY_KEY in out
    assert "- **ROA**" in out[GLOSSARY_KEY] and "- **HHI**" in out[GLOSSARY_KEY]


def test_glossary_section_empty_when_no_terms():
    from shared.products.report_sections import glossary_section
    assert glossary_section("Texto sin jerga del catálogo.", ProductTier.deep_dive) == {}


# ─── Procedencia por variable en Metodología (generada, no escrita) ───


class _ProductWithSignals:
    """Producto mínimo con señal por-variable — lo único que la sección necesita."""

    sector_key = "sector_intel"

    def __init__(self, signals):
        self._signals = signals

    def product_manifest(self):  # pragma: no cover - no lo usa esta sección
        raise NotImplementedError

    def data_signals(self):
        from shared.products.contract import DataHealth
        return DataHealth(coverage=0.8, freshness_days=30, sources=("BCRD",))

    def validation_state(self):
        from shared.products.contract import ValidationState
        return ValidationState(approved=True, score=0.7)

    def variable_signals(self):
        return {"period": "2025", "signals": self._signals}


def test_methodology_includes_generated_provenance():
    from shared.registry.signals import NATIONAL, REAL, RUBRIC, VariableSignal

    product = _ProductWithSignals([
        VariableSignal(key="growth", label="crecimiento del sector", state=REAL, weight=0.6),
        VariableSignal(key="skills", label="nivel de competencias", state=REAL, weight=0.2,
                       scope=NATIONAL),
        VariableSignal(key="ease", label="facilidad de operar", state=RUBRIC, weight=0.2),
    ])
    out = standard_sections(product, ProductTier.insight)
    text = out[METHODOLOGY_KEY]
    assert "Procedencia por variable:" in text
    assert "facilidad de operar" in text        # la rúbrica se declara
    assert "nivel de competencias" in text      # el alcance nacional se declara


def test_product_without_variable_signals_gets_no_provenance_block():
    """Silencio honesto: sin señal por-variable no se afirma procedencia."""

    class Bare(_ProductWithSignals):
        def __init__(self):
            super().__init__([])

        variable_signals = None  # el atributo existe pero no es invocable

    out = standard_sections(Bare(), ProductTier.insight)
    assert "Procedencia por variable:" not in out[METHODOLOGY_KEY]


def test_provenance_failure_never_breaks_the_report():
    class Explosive(_ProductWithSignals):
        def __init__(self):
            super().__init__([])

        def variable_signals(self):
            raise RuntimeError("tabla ausente")

    out = standard_sections(Explosive(), ProductTier.insight)
    assert METHODOLOGY_KEY in out               # la sección sale igual, sin el bloque
