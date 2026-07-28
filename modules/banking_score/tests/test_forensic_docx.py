"""Tests del informe forense en Word (.docx) — paridad con el PDF, editable."""
from modules.banking_score.reports import forensic_docx as fd


def _pkg():
    series = []
    for i in range(18):
        y, m = (2001 + i // 12), (i % 12) + 1
        series.append({
            "fecha": f"{y}-{m:02d}-01", "activos_totales": 1000.0,
            "morosidad_pct": (1.0 if i < 12 else 40.0),
            "peer_mora_pct": 3.0,
            "cobertura_pct": (200.0 if i < 12 else 20.0),
            "apalancamiento_pct": 10.0, "depositos": 600.0,
            "dep_mom_pct": (-23.0 if i == 12 else 1.0),
            "patrimonio": 100.0, "utilidad_neta": 5.0,
        })
    return {
        "meta": {"nombre": "Banco Quebrado", "tipo_entidad": "Bancos Múltiples", "sector": "Privado",
                 "primer": "2001-01-01", "ultimo": "2002-06-01", "n_periodos": 18,
                 "salio_del_sistema": True},
        "backtest": {"exit_date": "2002-06-01", "onset_cluster": "2002-01-01",
                     "first_high_raw": "2002-01-01", "lead_months": 5, "n_high_months": 6,
                     "n_flagged_months": 6,
                     "timeline": [{"period": "2002-01-01",
                                   "alerts": [{"code": "salto_morosidad", "severity": "alta",
                                               "value": 40.0}]}]},
        "series": series,
    }


def test_render_forensic_docx_is_docx():
    data = fd.render_forensic_docx(_pkg(), "## Lectura central\nEl **deterioro** empezó en 2002.")
    assert isinstance(data, bytes)
    assert data.startswith(b"PK")           # .docx es un ZIP (OOXML)
    assert len(data) > 3000                 # documento con gráficos embebidos, no vacío


def test_render_forensic_docx_degraded():
    """Sin narrativa (motor IA sin presupuesto) el Word igual se genera con datos + gráficos."""
    data = fd.render_forensic_docx(_pkg(), "", degraded=True)
    assert data.startswith(b"PK") and len(data) > 3000
