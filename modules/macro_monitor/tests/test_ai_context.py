"""Unit tests for the macro_monitor AI context builders (compact, pure)."""
from modules.macro_monitor.ai_context import series_ai_context, snapshot_ai_context


def test_series_context_is_compact_and_keeps_recent_only():
    obs = [{"period": f"2025-{m:02d}", "value": float(m)} for m in range(1, 13)]
    detail = {"series_code": "bcrd.x", "observations": obs, "momentum": {"latest_value": 12.0}}
    meta = {"label": "IPC", "unit": "%", "trend": "acelerando", "acceleration": 0.4,
            "pct_change": 1.2, "latest_value": 12.0, "latest_period": "2025-12"}
    ctx = series_ai_context(detail, meta)
    assert ctx["series_code"] == "bcrd.x"
    assert ctx["label"] == "IPC" and ctx["unit"] == "%"
    assert ctx["trend"] == "acelerando"
    assert ctx["n_obs"] == 12
    assert len(ctx["recent_observations"]) == 6  # only the tail, not all 12
    assert ctx["recent_observations"][-1]["period"] == "2025-12"


def test_series_context_without_meta_falls_back_to_momentum():
    detail = {"series_code": "bcrd.y", "observations": [{"period": "2025-01", "value": 5.0}],
              "momentum": {"latest_value": 5.0, "change": 1.0}}
    ctx = series_ai_context(detail)
    assert ctx["latest_value"] == 5.0
    assert ctx["change"] == 1.0
    assert ctx["label"] is None  # no meta provided


def test_snapshot_context_ranks_top_movers_by_abs_acceleration():
    snap = {"period": "2026-Q1", "series_count": 3, "signal_count": 1,
            "signals": [{"type": "reinhart_rogoff", "severity": "alta"}]}
    indicators = [
        {"label": "A", "series_code": "a", "acceleration": 0.1, "latest_value": 1, "trend": "estable"},
        {"label": "B", "series_code": "b", "acceleration": -0.9, "latest_value": 2, "trend": "desacelerando"},
        {"label": "C", "series_code": "c", "acceleration": 0.5, "latest_value": 3, "trend": "acelerando"},
        {"label": "D", "series_code": "d", "acceleration": None},  # excluded
    ]
    ctx = snapshot_ai_context(snap, indicators)
    assert ctx["period"] == "2026-Q1"
    assert ctx["signal_count"] == 1
    codes = [m["series_code"] for m in ctx["top_movers"]]
    assert codes == ["b", "c", "a"]  # |0.9| > |0.5| > |0.1|; None excluded
    assert all(m["acceleration"] is not None for m in ctx["top_movers"])
