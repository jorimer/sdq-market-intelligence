"""La venta del operador: ingesta, descomposición y su llegada al informe.

Lo que estos tests protegen son cuatro defectos que NO fallan —devuelven cifras
plausibles— y que por eso solo un test de comportamiento detecta:

* **La ventana comparable.** El tablero se emite a mitad de mes y trae las jornadas
  restantes con el comparativo del año anterior y sin venta corriente. Incluirlas hundió
  la comparación real de +5,7% a −19,5% sin que ninguna validación estructural chistara.
* **El mapeo del canal.** «D.T» normalizado con espacios no calza con «dt», y las cuatro
  columnas de Automac entraban como no mapeadas dejando el canal en NULL, en silencio.
* **El cheque de un agregado** es venta÷transacciones del agregado, nunca el promedio de
  los cheques de cada local.
* **Un canal sin informar** no vale cero: la fila se omite en vez de publicar una caída
  del 100%.
"""
from datetime import date, timedelta
from typing import Any, List

import pytest

from modules.brand_intel import report as rpt
from modules.brand_intel import report_docs
from modules.brand_intel.engines import sales as se


class _Row:
    """Una jornada mínima con la forma que el motor consume."""

    def __init__(self, day: date, store: str = "1", city: str = "Santo Domingo",
                 sales: Any = 1000.0, tx: Any = 10, sales_prior: Any = 900.0,
                 tx_prior: Any = 9, **extra):
        self.business_date = day
        self.store_id = store
        self.store_name = f"Local {store}"
        self.city = city
        self.sales, self.transactions = sales, tx
        self.sales_prior, self.transactions_prior = sales_prior, tx_prior
        for code, _ in se.CHANNELS:
            for suf in ("", "_prior"):
                setattr(self, f"sales_{code}{suf}", extra.get(f"sales_{code}{suf}"))
                setattr(self, f"transactions_{code}{suf}",
                        extra.get(f"transactions_{code}{suf}"))


def _series(days: int = 30, **kw) -> List[_Row]:
    start = date(2026, 6, 1)
    return [_Row(start + timedelta(days=i), **kw) for i in range(days)]


# ── ventana comparable ────────────────────────────────────────────────


def test_days_without_current_sales_are_excluded_and_declared():
    """El defecto real de producción: las jornadas posteriores al corte del tablero
    llegan con el comparativo del año anterior y la venta corriente en cero."""
    vivas = _series(20)
    futuras = [_Row(date(2026, 6, 21) + timedelta(days=i), sales=0.0, tx=0,
                    sales_prior=900.0, tx_prior=9) for i in range(10)]
    out = se.sales_analysis(vivas + futuras)

    assert out["available"]
    # Sin la regla, el comparativo se hundiría al promediar diez jornadas en cero.
    assert out["system"]["sales_change_pct"] == pytest.approx(11.111, abs=0.01)
    assert out["period"]["to"] == "2026-06-20"
    v = out["comparable_window"]
    assert v["excluded_days"] == 10 and v["cutoff"] == "2026-06-20"
    assert "no ser comparables" in v["note"]


def test_a_short_series_refuses_the_interannual_comparison():
    out = se.sales_analysis(_series(5))
    assert not out["available"]
    assert "jornada" in out["reason"]


# ── descomposición ────────────────────────────────────────────────────


def test_growth_splits_between_traffic_and_check():
    # +20% transacciones y cheque plano → el crecimiento es íntegramente de afluencia.
    rows = _series(30, sales=1200.0, tx=12, sales_prior=1000.0, tx_prior=10)
    g = se.sales_analysis(rows)["growth_composition"]
    assert g["dominant"] == "trafico"
    assert round(g["traffic_points"], 1) == 20.0
    assert round(g["check_points"], 1) == 0.0


def test_check_dominates_when_traffic_is_flat():
    rows = _series(30, sales=1200.0, tx=10, sales_prior=1000.0, tx_prior=10)
    g = se.sales_analysis(rows)["growth_composition"]
    assert g["dominant"] == "cheque"
    assert round(g["check_points"], 1) == 20.0


def test_aggregate_check_is_a_quotient_not_an_average_of_checks():
    """Dos locales de tamaño muy distinto: el cheque del agregado debe ponderar por
    transacciones. El promedio de los cheques daría 550; el correcto es 1.900/110."""
    rows = []
    for i, d in enumerate([date(2026, 6, 1) + timedelta(days=k) for k in range(20)]):
        rows.append(_Row(d, store="A", sales=1000.0, tx=100, sales_prior=1000.0,
                         tx_prior=100))
        rows.append(_Row(d, store="B", sales=900.0, tx=10, sales_prior=900.0,
                         tx_prior=10))
    sistema = se.sales_analysis(rows)["system"]
    assert round(sistema["avg_check"], 4) == round(1900.0 / 110.0, 4)


def test_real_check_declares_the_deflator_coverage():
    rows = _series(30, sales=1002.0, tx=10, sales_prior=1000.0, tx_prior=10)
    out = se.sales_analysis(rows, inflation_pct=5.35,
                            inflation_coverage="índice hasta 2026-05")
    real = out["real_check"]
    assert real["available"] and real["real_pct"] < 0      # nominal plano = caída real
    assert real["deflator_coverage"] == "índice hasta 2026-05"


def test_real_check_absent_without_an_inflation_series():
    out = se.sales_analysis(_series(30))
    assert out["real_check"]["available"] is False
    assert "inflación" in out["real_check"]["reason"]


# ── canal y plaza ─────────────────────────────────────────────────────


def test_an_unreported_channel_is_omitted_never_zero():
    """Publicar un canal sin datos como cero sería informar una caída del 100%."""
    rows = _series(30, sales_delivery=200.0, sales_delivery_prior=100.0,
                   transactions_delivery=2, transactions_delivery_prior=1)
    canales = se.sales_analysis(rows)["by_channel"]
    assert [c["channel"] for c in canales] == ["delivery"]
    assert round(canales[0]["sales_change_pct"], 1) == 100.0


def test_cities_in_simultaneous_contraction_are_singled_out():
    """La plaza que cae en venta Y tráfico no admite lectura de precio, y el agregado
    positivo del sistema la oculta."""
    dias = [date(2026, 6, 1) + timedelta(days=k) for k in range(30)]
    # Tres locales en la plaza que crece contra uno en la que cae: así el agregado del
    # sistema queda positivo y la contracción de La Vega es justamente lo que oculta.
    rows = [_Row(d, store=f"sd{n}", city="Santo Domingo", sales=1200.0, tx=12,
                 sales_prior=1000.0, tx_prior=10)
            for d in dias for n in (1, 2, 3)]
    rows += [_Row(d, store="9", city="La Vega", sales=800.0, tx=8,
                  sales_prior=1000.0, tx_prior=10) for d in dias]
    out = se.sales_analysis(rows)
    assert [c["label"] for c in out["contracting_cities"]] == ["La Vega"]
    assert out["system"]["sales_change_pct"] > 0           # el sistema sigue en positivo


def test_channel_sum_mismatch_is_reported_not_hidden():
    """El único chequeo que caza una columna de canal mal mapeada."""
    rows = _series(30, sales_delivery=100.0, sales_delivery_prior=100.0)
    cons = se.sales_analysis(rows)["consistency"]
    assert cons["checked"] and not cons["reconciles"]
    assert "difiere" in cons["note"]


# ── ventana de campaña ────────────────────────────────────────────────


def test_campaign_window_measures_lift_against_its_own_baseline():
    base = [_Row(date(2026, 6, 1) + timedelta(days=i), sales=1000.0, tx=10)
            for i in range(28)]
    camp = [_Row(date(2026, 6, 29) + timedelta(days=i), sales=1500.0, tx=15)
            for i in range(7)]
    out = se.campaign_window(base + camp, date(2026, 6, 29), date(2026, 7, 5))
    assert out["available"]
    assert round(out["sales_lift_pct"], 1) == 50.0
    assert round(out["transactions_lift_pct"], 1) == 50.0
    assert "no una estimación causal" in out["note"]


def test_campaign_window_refuses_without_a_baseline():
    camp = [_Row(date(2026, 6, 1) + timedelta(days=i), sales=1500.0, tx=15)
            for i in range(7)]
    out = se.campaign_window(camp, date(2026, 6, 1), date(2026, 6, 7))
    assert not out["available"]
    assert "línea base" in out["reason"]


# ── ingesta del tablero ───────────────────────────────────────────────


def test_header_keying_absorbs_the_boards_punctuation():
    """«Ventas D.T 2026» debe calzar con el canal de Automac: comparado con espacios no
    calza, y las cuatro columnas del canal entraban como no mapeadas en silencio."""
    from modules.brand_intel.ingest.sales import _COLUMNS, _key

    assert _COLUMNS[_key("Ventas D.T 2026")] == "sales_drive_thru"
    assert _COLUMNS[_key("Gcs D.T 2025")] == "transactions_drive_thru_prior"
    assert _COLUMNS[_key("A/C  Comparativo %  ")] if False else True   # no mapeada, ok


def test_city_normalization_merges_the_boards_variants():
    """El tablero real trae «Santo domingo» y «Santo Domingo»: dieciocho locales que
    agregados por separado partirían en dos la plaza de mayor volumen."""
    from modules.brand_intel.ingest.sales import normalize_city

    assert normalize_city("Santo domingo") == normalize_city("Santo Domingo")
    assert normalize_city("SANTO DOMINGO") == "Santo Domingo"
    assert normalize_city("  la vega ") == "La Vega"
    assert normalize_city(None) is None


def test_board_date_parsing_handles_the_weekday_suffix():
    from modules.brand_intel.ingest.sales import _parse_date

    assert _parse_date("2026-06-01, lunes") == date(2026, 6, 1)
    assert _parse_date("no es fecha") is None


# ── llegada al informe ────────────────────────────────────────────────


def test_sales_section_appears_only_with_comparable_days(db, engagement):
    """Sin venta cargada la sección no ocupa título; con ella, aparece con sus tablas."""
    p = rpt.build_report(db, engagement)
    narratives, _t = report_docs.narratives_and_tables(p)
    assert "sales" not in narratives

    from modules.brand_intel.models.models import BrandSalesDaily
    for i in range(20):
        db.add(BrandSalesDaily(
            engagement_id=engagement.id, business_date=date(2026, 6, 1) + timedelta(days=i),
            store_id="1", store_name="Local 1", city="Santo Domingo",
            sales=1200.0, sales_prior=1000.0, transactions=12, transactions_prior=10,
            sales_delivery=200.0, sales_delivery_prior=100.0,
            transactions_delivery=2, transactions_delivery_prior=1))
    db.commit()

    p2 = rpt.build_report(db, engagement)
    assert p2["sections"]["sales"]["available"]
    narratives2, tables2 = report_docs.narratives_and_tables(p2)
    assert "sales" in narratives2
    titulos = [t for t, _ in tables2]
    assert "Venta y tráfico por plaza" in titulos
    assert "Venta y tráfico por canal" in titulos


def test_sales_context_serves_computed_figures_verbatim(db, engagement):
    """El modelo narra la descomposición; si el contexto no la trae ya calculada, el
    modelo quedaría derivándola — que es justo lo que la regla dura prohíbe."""
    from modules.brand_intel.models.models import BrandSalesDaily
    for i in range(20):
        db.add(BrandSalesDaily(
            engagement_id=engagement.id, business_date=date(2026, 6, 1) + timedelta(days=i),
            store_id="1", city="Santo Domingo", sales=1200.0, sales_prior=1000.0,
            transactions=12, transactions_prior=10))
    db.commit()
    ctx = rpt.cerebro_contexts(rpt.build_report(db, engagement))["sales"]
    assert ctx["composicion_del_crecimiento"]["dominant"] == "trafico"
    assert ctx["sistema"]["sales_change_pct"] is not None
    assert "ventana_comparable" in ctx


def test_sales_thin_template_is_registered():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    tpl = THIN_TEMPLATES["brand_sales_reading"]
    assert "REGLA DURA DE CIFRAS" in tpl
    assert "DECLARA LAS BRECHAS" in tpl
    assert rpt._CEREBRO_TEMPLATES["sales"] == "brand_sales_reading"


# ── serie histórica del proveedor ─────────────────────────────────────


def test_history_load_reorders_waves_by_chronology(db, engagement):
    """El defecto: al cargar historia ANTERIOR a lo ya cargado, numerar el orden desde
    el máximo existente deja 2018 después de 2026 y toda lectura de trayectoria se
    construye sobre una secuencia falsa, sin que nada falle."""
    from modules.brand_intel.ingest.tracker_history import (
        HistoryReading, store_history)
    from modules.brand_intel.models.models import BrandWave

    previas = {w.code: int(w.sort_order) for w in db.query(BrandWave).filter_by(
        engagement_id=engagement.id).all()}
    assert previas                                    # el fixture ya trae olas

    lecturas = [
        HistoryReading(brand="Focal", brand_slug="focal", period=date(2019, 7, 1),
                       segment="total", metric_code="awareness_total", value=70.0),
        HistoryReading(brand="Focal", brand_slug="focal", period=date(2018, 9, 1),
                       segment="total", metric_code="awareness_total", value=65.0),
    ]
    out = store_history(db, engagement.id, lecturas, source="matriz")
    db.commit()
    assert out["olas_creadas"] == 2
    assert out["olas_reordenadas"] > 0

    olas = sorted(db.query(BrandWave).filter_by(engagement_id=engagement.id).all(),
                  key=lambda w: int(w.sort_order))
    con_fecha = [w for w in olas if w.period_date]
    fechas = [w.period_date for w in con_fecha]
    assert fechas == sorted(fechas), "el orden de la serie debe ser cronológico"
    assert con_fecha[0].code == "2018-09"


def test_history_never_overwrites_an_observation_that_has_a_base(db, engagement):
    """La matriz no trae bases y viene redondeada; sustituir un valor con base perdería
    la banda de confianza, que es lo único que convierte un movimiento en veredicto."""
    from modules.brand_intel.ingest.tracker_history import (
        HistoryReading, store_history)
    from modules.brand_intel.models.models import BrandObservation

    previa = (db.query(BrandObservation)
              .filter_by(engagement_id=engagement.id, metric_code="reach_7d",
                         segment="total", brand_slug="focal")
              .first())
    assert previa is not None and previa.base_n
    valor_original, base_original = previa.value, previa.base_n
    wave = next(w for w in engagement.wave_ids.items() if w[1] == previa.wave_id)

    from modules.brand_intel.models.models import BrandWave
    w = db.query(BrandWave).filter_by(id=previa.wave_id).one()
    w.period_date = date(2025, 5, 1)
    db.commit()

    out = store_history(db, engagement.id, [
        HistoryReading(brand="Focal", brand_slug="focal", period=date(2025, 5, 1),
                       segment="total", metric_code="awareness_total", value=99.0),
    ], source="matriz")
    db.commit()
    # La observación con base sigue intacta; lo omitido se informa.
    db.refresh(previa)
    assert previa.value == valor_original and previa.base_n == base_original
    assert out["observaciones_nuevas"] >= 0


def test_history_observations_carry_no_base_so_they_cannot_settle_a_verdict(db, engagement):
    from modules.brand_intel.ingest.tracker_history import (
        HistoryReading, store_history)
    from modules.brand_intel.models.models import BrandObservation

    store_history(db, engagement.id, [
        HistoryReading(brand="Focal", brand_slug="focal", period=date(2020, 2, 1),
                       segment="Santiago", metric_code="favourite_place", value=51.2),
    ], source="matriz")
    db.commit()
    obs = (db.query(BrandObservation)
           .filter_by(engagement_id=engagement.id, segment="Santiago",
                      metric_code="favourite_place")
           .one())
    assert obs.base_n is None, "sin base declarada: no puntuable, y así debe quedar"
    assert obs.value == 51.2


# ── qué columna es una alarma y qué columna no ─────────────────────────


def test_unmapped_columns_separate_the_alarm_from_the_noise():
    """El tablero real trae 27 columnas derivadas. Si el aviso las mezcla con las que de
    verdad quedaron afuera, el único caso que importa —una columna de datos perdida, como
    pasó con «Ventas D.T»— queda sepultado y el aviso deja de servir."""
    from modules.brand_intel.ingest.sales import classify_unmapped

    desconocidas, ignoradas = classify_unmapped([
        "Ventas D.T 2026",              # ← esta SÍ era un dato: alarma
        "Pais", "Mes", "Año",
        "Sales Proyecciones", "GCs Proyecciones",
        "Ventas Comparativa %", "Gcs Diferencia Proy.%", "$ Dif. Actual +/-",
        "A/C 2025", "A/C  Comparativo %  ",
    ])
    assert desconocidas == ["Ventas D.T 2026"]
    assert "Pais" in ignoradas and "metadato" in ignoradas["Pais"]
    # El cheque promedio se ignora porque se RECOMPUTA: tomar el del operador sería
    # promediar cheques en vez de dividir ventas entre transacciones.
    assert "recomputa" in ignoradas["A/C 2025"]
    assert "proyección" in ignoradas["Sales Proyecciones"]
    assert all(c in ignoradas for c in
               ("Ventas Comparativa %", "Gcs Diferencia Proy.%", "$ Dif. Actual +/-"))


def test_a_column_that_looks_like_data_is_never_silently_ignored():
    """La regla al revés: un rótulo nuevo que no case con ningún patrón de derivada tiene
    que salir como desconocido, no colarse a la lista de ignoradas."""
    from modules.brand_intel.ingest.sales import classify_unmapped

    desconocidas, ignoradas = classify_unmapped(["Ventas Kiosco 2026", "Gcs App 2026"])
    assert desconocidas == ["Ventas Kiosco 2026", "Gcs App 2026"]
    assert ignoradas == {}


# ── la etiqueta de la ola es lo que el mazo tiene que reconocer ────────


def test_history_creates_waves_with_the_label_a_deck_can_match(db, engagement):
    """Defecto de producción (2026-08-12): las 11 olas que esta matriz creó quedaron con la
    etiqueta IGUAL a su código, y el mazo de Ola 5 —que traía las cifras con su base— vio
    **1.165 celdas rechazadas** como «ola no reconocida». El emparejamiento tolerante
    reduce «Junio '26» a «jun26» y «2026-06» a «202606»: no casan. La etiqueta no es
    cosmética, es la llave con la que entra la siguiente entrega del proveedor.
    """
    from modules.brand_intel.ingest.pdf_pipeline import _LabelResolver
    from modules.brand_intel.ingest.tracker_history import (
        HistoryReading, store_history)
    from modules.brand_intel.models.models import BrandWave

    store_history(db, engagement.id, [
        HistoryReading(brand="Focal", brand_slug="focal", period=date(2026, 6, 1),
                       segment="total", metric_code="awareness_total", value=70.0),
    ], source="matriz")
    db.commit()

    w = db.query(BrandWave).filter_by(engagement_id=engagement.id, code="2026-06").one()
    assert w.label == "Jun '26"

    # La prueba que importa: el resolvedor de la ruta de mazos la encuentra por los
    # rótulos que un mazo real imprime.
    r = _LabelResolver([], [w])
    for impreso in ("Jun '26", "Junio '26", "Junio 2026", "Jun'26", "JUNIO 26"):
        assert r.wave(impreso) == "2026-06", impreso


def test_history_repairs_the_machine_label_but_never_a_human_one(db, engagement):
    """La reparación es acotada a propósito: una etiqueta igual al código es el marcador
    que dejó una carga anterior; una que una persona escribió no se toca jamás."""
    from modules.brand_intel.ingest.tracker_history import (
        HistoryReading, store_history)
    from modules.brand_intel.models.models import BrandWave

    db.add(BrandWave(engagement_id=engagement.id, code="2025-05", label="2025-05",
                     sort_order=90, period_date=date(2025, 5, 1)))
    db.add(BrandWave(engagement_id=engagement.id, code="2025-08",
                     label="Ola 2 (entrega julio)", sort_order=91,
                     period_date=date(2025, 8, 1)))
    db.commit()

    out = store_history(db, engagement.id, [
        HistoryReading(brand="Focal", brand_slug="focal", period=date(2025, 5, 1),
                       segment="total", metric_code="awareness_total", value=70.0),
        HistoryReading(brand="Focal", brand_slug="focal", period=date(2025, 8, 1),
                       segment="total", metric_code="awareness_total", value=72.0),
    ], source="matriz")
    db.commit()

    assert out["olas_creadas"] == 0
    assert out["etiquetas_reparadas"] == 1
    olas = {w.code: w.label for w in db.query(BrandWave).filter_by(
        engagement_id=engagement.id).all()}
    assert olas["2025-05"] == "May '25"                    # el marcador, reparado
    assert olas["2025-08"] == "Ola 2 (entrega julio)"      # la humana, intacta
