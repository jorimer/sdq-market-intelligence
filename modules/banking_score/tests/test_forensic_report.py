"""Tests del renderizador del informe forense (HTML branded) + helpers.

Cubre los gráficos SVG, el markdown mínimo y el documento completo — el módulo que bajó
la cobertura global bajo 80%."""
from modules.banking_score.reports import forensic_report as fr


def _pkg():
    series = []
    for i in range(18):
        y, m = (2001 + i // 12), (i % 12) + 1
        mora = 1.0 if i < 12 else 40.0
        cob = 200.0 if i < 12 else 20.0
        series.append({
            "fecha": f"{y}-{m:02d}-01", "activos_totales": 1000.0,
            "morosidad_pct": mora, "cobertura_pct": cob, "apalancamiento_pct": 10.0,
            "depositos": 600.0, "dep_mom_pct": (-23.0 if i == 12 else 1.0),
            "patrimonio": 100.0, "utilidad_neta": 5.0,
        })
    return {
        "meta": {"nombre": "Banco Quebrado", "tipo_entidad": "Bancos Múltiples",
                 "sector": "Privado", "primer": "2001-01-01", "ultimo": "2002-06-01",
                 "n_periodos": 18, "salio_del_sistema": True},
        "backtest": {"exit_date": "2002-06-01", "onset_cluster": "2002-01-01",
                     "first_high_raw": "2002-01-01", "lead_months": 5, "n_high_months": 6,
                     "n_flagged_months": 6,
                     "timeline": [{"period": "2002-01-01",
                                   "alerts": [{"code": "salto_morosidad", "severity": "alta", "value": 40.0},
                                              {"code": "brecha_provisiones", "severity": "alta", "value": 20.0}]}]},
        "series": series,
    }


def test_md_to_html():
    html = fr._md_to_html("## Título\nUn párrafo con **negrita**.\n\n---\nOtro.")
    assert "<h2>Título</h2>" in html
    assert "<strong>negrita</strong>" in html
    assert "<p>Otro.</p>" in html
    assert "---" not in html  # el separador no se renderiza


def test_line_and_bar_charts():
    pkg = _pkg()
    line = fr._line_chart(pkg["series"], [{"field": "morosidad_pct", "color": "#C8392E"}], ymax=100)
    assert line.startswith("<svg") and "polyline" in line
    bar = fr._bar_chart(pkg["series"], "dep_mom_pct")
    assert bar.startswith("<svg") and "<rect" in bar
    # < 2 puntos → cadena vacía (no rompe)
    assert fr._line_chart([{"fecha": "2001-01-01", "morosidad_pct": 1.0}],
                          [{"field": "morosidad_pct", "color": "#000"}], ymax=10) == ""
    assert fr._bar_chart([], "dep_mom_pct") == ""


def test_render_forensic_html_full():
    doc = fr.render_forensic_html(_pkg(), "## Lectura central\nEl **deterioro** empezó en 2002.")
    assert doc.startswith("<!doctype html>")
    for needle in ("Banco Quebrado", "SDQ·MIP", "FORENSE", "Resumen forense",
                   "Riesgo de crédito", "Fuga de depósitos", "Lectura forense",
                   "Metodología", "<svg", "<strong>deterioro</strong>",
                   "2002-01-01", "Basilea"):
        assert needle in doc, needle


def test_render_degraded_no_narrative():
    doc = fr.render_forensic_html(_pkg(), "", degraded=True)
    assert "motor IA sin presupuesto" in doc
    assert doc.startswith("<!doctype html>")


def test_fnum():
    assert fr._fnum(None) == "—"
    assert fr._fnum(47.234) == "47.2"
    assert fr._fnum(1234.5, 0) == "1,234"
