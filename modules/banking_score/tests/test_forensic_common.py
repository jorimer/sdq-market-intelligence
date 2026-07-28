"""Tests de la lógica pura compartida del informe forense (PDF y Word)."""
from modules.banking_score.reports import forensic_common as fc


def _ctx(**kw):
    base = {"morosidad_maxima_pct": 51.0, "peor_fuga_depositos_pct": -23.0,
            "peor_fuga_fecha": "2002-07-01", "cluster_en_onset": ["salto_morosidad", "estres_liquidez"]}
    base.update(kw)
    return base


def _pkg(onset="2002-07-01", lead=11, exit_="2003-06-01", n_high=18):
    return {"meta": {"nombre": "X", "primer": "2001-01-01", "ultimo": "2003-06-01"},
            "series": [{"fecha": f"2002-{m:02d}-01"} for m in range(1, 13)],
            "backtest": {"onset_cluster": onset, "lead_months": lead, "exit_date": exit_,
                         "first_high_raw": "2002-01-01", "n_high_months": n_high}}


def test_humanize_month():
    assert fc.humanize_month("2002-07-01") == "jul 2002"
    assert fc.humanize_month("2002-07") == "jul 2002"
    assert fc.humanize_month("1994") == "1994"
    assert fc.humanize_month(None) == "—"


def test_stat_cards_valores():
    cards = fc.stat_cards(_pkg(), _ctx())
    assert cards[0]["value"] == "jul 2002"           # onset humanizado
    assert cards[1]["value"] == "11 meses"
    assert cards[2]["value"] == "51%"
    assert cards[3]["value"] == "-23%"


def test_timeline_con_onset_tiene_gatillo_sostenido_colapso():
    rows = fc.model_timeline(_pkg(), _ctx())
    flags = [r["flag"] for r in rows]
    assert flags == ["GATILLO", "SOSTENIDO", "COLAPSO"]
    # el gatillo nombra las señales convergentes legibles
    assert "salto de morosidad" in rows[0]["text"] and "fuga de depósitos" in rows[0]["text"]


def test_timeline_sin_onset_marca_punto_ciego():
    rows = fc.model_timeline(_pkg(onset=None, lead=None), _ctx(cluster_en_onset=[]))
    assert rows[0]["flag"] == "PUNTO CIEGO"
    assert "fraude" in rows[0]["text"]


def test_legibility_legible_vs_punto_ciego():
    leg = fc.legibility(_pkg(lead=11), _ctx())
    assert leg["legible"] is True and "vieron venir" in leg["title"]
    ciego = fc.legibility(_pkg(onset=None, lead=None), _ctx(cluster_en_onset=[]))
    assert ciego["legible"] is False and "ciego" in ciego["title"].lower()
    assert "Baninter" in ciego["text"]              # nombra el punto ciego del fraude
