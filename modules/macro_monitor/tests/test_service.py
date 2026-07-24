"""Tests for macro_monitor ingestion, snapshot persistence and events."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
import shared.settings.models  # noqa: F401 — register sector_api_config table before create_all
from shared.events.event_bus import event_bus
from modules.macro_monitor.events import MACRO_UPDATED
from modules.macro_monitor.models.models import (  # noqa: F401 — register tables
    MacroSeries,
    MacroSnapshot,
)
from modules.macro_monitor.service import (
    build_snapshot,
    delete_series,
    get_indicators,
    get_snapshot,
    ingest_series,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_bus():
    event_bus.clear()
    yield
    event_bus.clear()


def test_ingest_populates_series(db):
    n = ingest_series(db)
    assert n > 0
    # gdp_growth fixture has a null Q2 — preserved, not interpolated
    gdp = db.query(MacroSeries).filter_by(series_code="gdp_growth", period="2025-Q2").one()
    assert gdp.value is None
    assert gdp.source == "BCRD"


def test_build_snapshot_persists_and_publishes(db):
    received = []
    event_bus.subscribe(MACRO_UPDATED, lambda p: received.append(p))

    ingest_series(db)
    result = build_snapshot(db)

    # persisted
    snap = db.query(MacroSnapshot).one()
    assert snap.period == "2025-Q2"
    assert "gdp_growth" in snap.momentum
    # El fixture trimestral dispara debt_overhang (62.4). Ya NO dispara sudden_stop:
    # esa señal se migró a leer el `flow_panel` de series canónicas VIVAS (remesas_6,
    # bpagos_6…) por variación interanual — ausentes de este fixture — en vez de la caída
    # trimestre-a-trimestre de `remittances` (2710→2180), que era un falso positivo
    # estacional. El camino feliz del sudden_stop se cubre en test_signals.py (unidad) y en
    # `test_sudden_stop_fires_from_canonical_flow_panel` abajo (end-to-end).
    kinds = {s["signal"] for s in snap.signals}
    assert "debt_overhang" in kinds
    assert "sudden_stop" not in kinds

    # published
    assert len(received) == 1
    assert received[0]["period"] == "2025-Q2"
    assert received[0]["signal_count"] == len(snap.signals)
    assert result["snapshot_id"] == snap.id


def test_sudden_stop_fires_from_canonical_flow_panel(db):
    """End-to-end: build_snapshot debe emitir `sudden_stop` cuando una serie canónica del
    `flow_panel` (remesas_6) cae fuerte INTERANUAL, citando serie y etiqueta. Se siembra la
    serie viva directo en la DB (dos obs a 12 meses) para ejercitar `_flow_pct_panel` →
    `detect_signals`, no la caída trimestre-a-trimestre del fixture (que era falso positivo)."""
    db.add(MacroSeries(series_code="bcrd.xls.remesas_6.valor", period="2025-05",
                       value=700.0, nature="flow"))
    db.add(MacroSeries(series_code="bcrd.xls.remesas_6.valor", period="2026-05",
                       value=500.0, nature="flow"))  # −28.6% interanual → sudden stop
    db.commit()

    build_snapshot(db)
    snap = db.query(MacroSnapshot).one()

    stops = [s for s in snap.signals if s["signal"] == "sudden_stop"]
    assert len(stops) == 1
    sig = stops[0]
    assert sig["series"] == "remittances"
    assert sig["series_code"] == "bcrd.xls.remesas_6.valor"
    assert sig["label"] == "Remesas familiares"
    assert sig["basis"] == "yoy"
    assert sig["pct_change"] < -15


def test_build_snapshot_idempotent_per_period(db):
    ingest_series(db)
    build_snapshot(db)
    build_snapshot(db)
    assert db.query(MacroSnapshot).count() == 1


def test_build_without_ingest_raises(db):
    with pytest.raises(ValueError):
        build_snapshot(db)


def test_delete_series_removes_only_that_code(db):
    ingest_series(db)
    # seed an orphan code of the old schema alongside the real series
    db.add(MacroSeries(series_code="bcrd.x.cuentas_corrientes.2023", period="2026-06", value=1.0))
    db.commit()
    before = db.query(MacroSeries).filter_by(series_code="gdp_growth").count()

    deleted = delete_series(db, "bcrd.x.cuentas_corrientes.2023")

    assert deleted == 1
    assert db.query(MacroSeries).filter_by(series_code="bcrd.x.cuentas_corrientes.2023").count() == 0
    # untouched series survive
    assert db.query(MacroSeries).filter_by(series_code="gdp_growth").count() == before


def test_delete_series_idempotent_for_absent_code(db):
    ingest_series(db)
    assert delete_series(db, "no.such.code") == 0


def test_get_indicators_and_snapshot(db):
    ingest_series(db)
    build_snapshot(db)

    indicators = get_indicators(db)
    codes = {i["series_code"] for i in indicators}
    assert {"gdp_growth", "inflation_yoy", "remittances", "public_debt_gdp"} <= codes

    # each indicator carries a human label + unit for the UI
    by_code = {i["series_code"]: i for i in indicators}
    assert by_code["gdp_growth"]["label"] == "Crecimiento del PIB"
    assert by_code["gdp_growth"]["unit"] == "%"
    assert all("label" in i and "unit" in i for i in indicators)
    # n_obs lets the UI default the trajectory chart to a series with depth
    assert all("n_obs" in i and i["n_obs"] >= 1 for i in indicators)

    latest = get_snapshot(db)
    assert latest is not None
    assert latest.period == "2025-Q2"


def test_nature_honors_declared_codes_even_with_null_column(db):
    """Un código PROPIO (`public_debt_gdp`) tiene naturaleza determinística: la definimos
    nosotros. No pasa por la ingesta de Excel, así que su columna `nature` queda nula —
    y aun así `_nature_by_code` debe devolver `rate`, no `unknown`. Esta era la causa de
    que la señal `sudden_stop` perdiera su insumo: leía `unknown` y no computaba %."""
    from modules.macro_monitor.service import _nature_by_code

    db.add(MacroSeries(series_code="public_debt_gdp", period="2025", value=62.4, nature=None))
    db.add(MacroSeries(series_code="remittances", period="2025", value=2180.0, nature=None))
    db.commit()

    nats = _nature_by_code(db)
    assert nats["public_debt_gdp"] == "rate"   # % del PIB → variación en puntos
    assert nats["remittances"] == "flow"       # flujo → admite variación porcentual


def test_nature_reads_persisted_value_for_excel_series(db):
    """Para las series de planilla se lee lo que persistió el ingestor, sin re-inferir."""
    from modules.macro_monitor.service import _nature_by_code

    db.add(MacroSeries(series_code="bcrd.xls.foo.bar", period="2025", value=1.0, nature="stock"))
    db.commit()
    assert _nature_by_code(db)["bcrd.xls.foo.bar"] == "stock"


def test_nature_falls_back_to_the_persisted_unit_when_column_is_null(db):
    """Conectores fuera de la ingesta de Excel (fiscal, inflación, IPC) nunca escriben la
    columna `nature`, pero SÍ persisten la unidad. Inferir de esa unidad da el mismo
    resultado que la ingesta habría dado — cierra el hueco sin adivinar. Era la causa de
    que 25 series con unidad real (`RD$ millones`, `%`, `índice`) quedaran en `unknown`."""
    from modules.macro_monitor.service import _nature_by_code

    db.add(MacroSeries(series_code="fiscal_eo.gastos", period="2025",
                       value=1.0, unit="RD$ millones", nature=None))
    db.add(MacroSeries(series_code="bcrd.inflacion.interanual", period="2025",
                       value=1.0, unit="%", nature=None))
    db.add(MacroSeries(series_code="bcrd.ipc.indice", period="2025",
                       value=1.0, unit="índice", nature=None))
    db.commit()

    nats = _nature_by_code(db)
    assert nats["fiscal_eo.gastos"] == "flow"      # dinero → flujo
    assert nats["bcrd.inflacion.interanual"] == "rate"  # % → variación en puntos
    assert nats["bcrd.ipc.indice"] == "index"
