"""Tests del Readiness Audit (shared/products/audit) — diagnóstico + markdown."""
from types import SimpleNamespace

from shared.products.audit import (
    _gate_diagnosis,
    build_audit,
    render_audit_markdown,
)
from shared.products.registry import PRODUCT_CATALOG


def _data(coverage=1.0, freshness_days=10, cadence="quarterly", sources=("X",), detail="d"):
    return SimpleNamespace(coverage=coverage, freshness_days=freshness_days,
                           cadence=cadence, sources=sources, detail=detail)


def _val(approved=True, score=0.5, notes="parcial"):
    return SimpleNamespace(approved=approved, score=score, notes=notes)


def test_g1_diagnosis_coverage_bound():
    """Cobertura por debajo de la frescura → el faltante nombra la cobertura."""
    d = _gate_diagnosis("tourism", "g1", 0.40, _data(coverage=0.40, freshness_days=10), _val())
    assert "Cobertura" in d["falta"] and "40%" in d["falta"]
    assert "rúbrica" in d["accion"]  # overlay curado del sector


def test_g1_diagnosis_freshness_bound():
    """Frescura por debajo de la cobertura → el faltante nombra la frescura."""
    d = _gate_diagnosis("telecom", "g1", 0.0, _data(coverage=1.0, freshness_days=1553), _val())
    assert "Frescura" in d["falta"]
    assert "INDOTEL" in d["accion"]


def test_g5_diagnosis_uses_validation_notes():
    d = _gate_diagnosis("pension", "g5", 0.50, _data(), _val(approved=True, score=0.5,
                                                            notes="sin backtest de quiebras"))
    assert "parcial" in d["falta"] and "backtest" in d["falta"]
    assert "ESTRUCTURAL" in d["accion"]


def test_g2_diagnosis_generic_when_no_overlay():
    d = _gate_diagnosis("banking", "g2", 0.0, _data(), _val())
    assert "Motor" in d["falta"] and d["accion"]


def test_render_markdown_has_structure():
    audit = {
        "generated_at": "2026-06-28T00:00:00+00:00",
        "thresholds": {"pulse": 0.75, "insight": 0.85, "deep_dive": 0.85},
        "summary": {"full": ["banking"], "pulse_only": ["tourism"], "blocked": ["telecom"],
                    "pending": []},
        "sectors": [
            {"sector_key": "banking", "display_name": "Banking", "implemented": True,
             "readiness": {"pulse": 1.0, "insight": 1.0, "deep_dive": 1.0},
             "levels": [{"tier": "pulse", "can_publish": True}], "gaps": [],
             "headline": "Listo (full)."},
            {"sector_key": "tourism", "display_name": "Turismo", "implemented": True,
             "readiness": {"pulse": 0.835, "insight": 0.835, "deep_dive": 0.835},
             "levels": [{"tier": "pulse", "can_publish": True},
                        {"tier": "insight", "can_publish": False}],
             "gaps": [{"gate": "g1", "label": "Datos", "value": 0.70, "weight": 0.30,
                       "points_lost": 0.09, "lineage": "cobertura...", "falta": "Cobertura 70%",
                       "accion": "subir 3 variables"}],
             "headline": "Palanca: Datos (70%). subir 3 variables"},
        ],
    }
    md = render_audit_markdown(audit)
    assert "# SDQ·MIP — Readiness Audit" in md
    assert "## Resumen" in md
    assert "Banking" in md and "Turismo" in md
    assert "| Gate |" in md and "Datos (G1)" in md
    # Orden por readiness Pulse desc: Banking (1.0) antes que Turismo (0.835).
    assert md.index("## Banking") < md.index("## Turismo")


def test_build_audit_covers_full_catalog():
    """build_audit (sin DB cableada) no rompe: degrada por sector y cubre el catálogo."""
    audit = build_audit(db=None)  # type: ignore[arg-type]
    assert set(s["sector_key"] for s in audit["sectors"]) == {e.sector_key for e in PRODUCT_CATALOG}
    assert "# SDQ·MIP — Readiness Audit" in audit["markdown"]
    # Cada sector cae en exactamente un bucket del resumen.
    buckets = audit["summary"]
    total = sum(len(v) for v in buckets.values())
    assert total == len(PRODUCT_CATALOG)
