"""Un texto cortado por presupuesto no puede viajar como si estuviera terminado.

El PDF de Perspectiva Sectorial se entregó cortado a mitad de oración —"cobertura de 152,1%
y eficiencia operativa sustancialmente"— y saltó al disclaimer. No era azar: la plantilla
pide hasta 800 palabras y la sección corría con 1024 tokens, que en español no alcanzan.
Un documento truncado sin señal es peor que un error visible: parece el final.
"""
from shared.narrative.claude_engine import NarrativeEngine
from modules.banking_score.reports.narrative import _DEEP_SECTIONS, _section_mode


class _Resp:
    def __init__(self, text, stop_reason):
        self.content = [type("C", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 1024})()
        self.stop_reason = stop_reason


def test_se_marca_el_corte_por_presupuesto(monkeypatch):
    import shared.narrative.claude_engine as ce
    monkeypatch.setattr(ce.settings, "ANTHROPIC_MODEL", "test-model", raising=False)
    r = NarrativeEngine()._build_result(_Resp("texto cortado a mitad de", "max_tokens"))
    assert r.truncated is True


def test_un_final_normal_no_se_marca(monkeypatch):
    import shared.narrative.claude_engine as ce
    monkeypatch.setattr(ce.settings, "ANTHROPIC_MODEL", "test-model", raising=False)
    assert NarrativeEngine()._build_result(_Resp("texto completo.", "end_turn")).truncated is False


def test_sector_outlook_tiene_presupuesto_suficiente():
    """La causa raíz: pedía 800 palabras con 1024 tokens."""
    assert "sector_outlook" in _DEEP_SECTIONS
    assert _section_mode("sector_outlook", "standard") == "deep"
