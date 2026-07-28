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


# ── Clasificación de la naturaleza de la salida ──────────────────────────────────

def _exit_pkg(nombre, tipo, mora, cob, onset=None):
    """pkg con 6 meses finales a (mora, cob) — para ejercitar classify_exit."""
    series = [{"fecha": f"2021-{m:02d}-01", "morosidad_pct": mora, "cobertura_pct": cob,
               "dep_mom_pct": 2.0, "peer_mora_pct": 2.0} for m in range(1, 13)]
    return {"meta": {"nombre": nombre, "tipo_entidad": tipo, "primer": "2021-01-01",
                     "ultimo": "2021-12-01"},
            "series": series,
            "backtest": {"onset_cluster": onset, "lead_months": (11 if onset else None),
                         "exit_date": "2021-12-01", "first_high_raw": None, "n_high_months": 0}}


def test_classify_no_quiebra_salida_sana():
    # banco múltiple que sale con mora 1.5% (< piso 5) y cobertura 300% → fusión/renombre
    pkg = _exit_pkg("Banco Vivo", "Bancos Múltiples", 1.5, 300.0)
    assert fc.classify_exit(pkg, _ctx()) == fc.NO_QUIEBRA


def test_classify_quiebra_por_distress_o_roster():
    # sale enfermo (mora 20% > piso) → quiebra
    assert fc.classify_exit(_exit_pkg("Chico", "Bancos Múltiples", 20.0, 40.0), _ctx()) == fc.QUIEBRA
    # en el roster curado → quiebra aunque los ratios finales se vean bien
    roster = _exit_pkg("Banco Global", "Bancos Múltiples", 1.0, 300.0)
    assert fc.classify_exit(roster, _ctx()) == fc.QUIEBRA


def test_classify_umbral_relativo_al_tipo():
    # 10% de mora: sobre el piso del múltiple (quiebra) pero normal para corporación (no)
    assert fc.classify_exit(_exit_pkg("M", "Bancos Múltiples", 10.0, 200.0), _ctx()) == fc.QUIEBRA
    corp = fc.classify_exit(_exit_pkg("C", "Corporaciones de Crédito", 10.0, 200.0), _ctx())
    assert corp == fc.NO_QUIEBRA


def test_reframe_no_quiebra_dice_otras_causas():
    pkg = _exit_pkg("Banco Vivo", "Bancos Múltiples", 1.5, 300.0)
    kind = fc.classify_exit(pkg, _ctx())
    h = fc.headings(pkg, _ctx(), kind)
    assert "no quebró" in h["verdict"] and "otras causas" in h["verdict"]
    tl = fc.model_timeline(pkg, _ctx(), kind)
    assert tl[0]["flag"] == "SIN ALERTA"
    leg = fc.legibility(pkg, _ctx(), kind)
    assert "no fue una quiebra" in leg["title"].lower()
    cards = fc.stat_cards(pkg, _ctx(), kind)
    assert cards[3]["value"] == "No fue quiebra"


def test_verdict_lead_cero_no_dice_cero_meses():
    h = fc.headings(_pkg(onset="2003-09-01", lead=0), _ctx(), fc.QUIEBRA)
    assert "0 meses" not in h["verdict"] and "señal tardía" in h["verdict"]
