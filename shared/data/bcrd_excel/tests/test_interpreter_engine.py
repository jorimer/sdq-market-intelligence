"""Interpreter (Claude fallback) + engine orchestration / spec cache.

The interpreter is exercised with a fake Anthropic client so it runs offline and
deterministically; the live path differs only in where the client comes from.
"""
from pathlib import Path
from types import SimpleNamespace

from shared.data.bcrd_excel.engine import SpecCache, build_spec, ingest_excel
from shared.data.bcrd_excel.interpreter import interpret_spec, render_preview
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import load_workbook

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeClient:
    """Mimics anthropic.Anthropic: returns a forced tool_use spec."""

    def __init__(self, spec_input: dict):
        self._input = spec_input
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls += 1
        # the prompt must carry an indexed grid preview
        assert "r0:" in kwargs["messages"][0]["content"]
        block = SimpleNamespace(type="tool_use", name="emit_extraction_spec",
                                input=self._input)
        return SimpleNamespace(content=[block])


def test_render_preview_is_indexed():
    wb = load_workbook(FIXTURES / "imae.xlsx")
    preview = render_preview(wb.grid())
    assert "col idx:" in preview and "r0:" in preview and "[0]" in preview


def test_interpreter_emits_spec_from_tool_call():
    wb = load_workbook(FIXTURES / "ipc.xls")
    fake = _FakeClient({
        "orientation": "period_rows", "sheet": "IPCbase 99", "data_row_start": 10,
        "month_col": 2, "year_col": 1,
        "series": [{"code": "indice", "name": "IPC", "unit": "indice", "value_col": 3}],
    })
    spec = interpret_spec(wb, "ipc.xls", client=fake)
    assert fake.calls == 1
    assert spec.method == "claude" and spec.orientation == "period_rows"
    assert spec.series[0].value_col == 3
    assert spec.structure_hash == wb.structure_hash()  # cache key stamped


def test_build_spec_falls_back_to_claude_on_low_confidence():
    wb = load_workbook(FIXTURES / "ipc.xls")
    fake = _FakeClient({
        "orientation": "period_rows", "sheet": "IPCbase 99", "data_row_start": 10,
        "month_col": 2, "year_col": 1,
        "series": [{"code": "indice", "name": "IPC", "unit": "indice", "value_col": 3}],
    })
    # force the heuristic to look unconfident → must consult the interpreter
    spec = build_spec(wb, "ipc.xls", min_confidence=1.1, use_claude=True, client=fake)
    assert fake.calls == 1 and spec.method == "claude"


def test_spec_cache_roundtrip_and_reuse(tmp_path):
    cache = SpecCache(tmp_path / "specs.json")
    wb = load_workbook(FIXTURES / "imae.xlsx")
    spec = build_spec(wb, "imae.xlsx", cache=cache, use_claude=False)
    assert spec.method == "heuristic"
    # reloading from disk returns the same spec, now served as "cached"
    cache2 = SpecCache(tmp_path / "specs.json")
    hit = cache2.get(wb.structure_hash())
    assert hit is not None and hit.orientation == spec.orientation
    again = build_spec(wb, "imae.xlsx", cache=cache2, use_claude=True)
    assert again.method == "cached"  # never calls the model on a cache hit


def test_ingest_excel_end_to_end(tmp_path):
    res = ingest_excel(FIXTURES / "imae.xlsx", cache=SpecCache(tmp_path / "s.json"),
                       use_claude=False)
    assert res.spec.orientation == "period_rows"
    assert len(res.records) > 200
    idx = {r.period: r.value for r in res.records
           if r.series.endswith("serie_original_indice")}
    assert abs(idx["2007-01"] - 93.963) < 1e-2
    assert "validation" in res.summary()


def test_from_dict_ignores_unknown_keys():
    spec = ExtractionSpec.from_dict({
        "file": "x", "sheet": "s", "orientation": "period_rows", "data_row_start": 0,
        "bogus_future_field": 123,
    })
    assert spec.sheet == "s"
