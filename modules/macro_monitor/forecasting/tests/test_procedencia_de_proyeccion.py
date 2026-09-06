"""Del ledger a la señal, y de la señal a la pregunta. El cableado con corriente.

Todo el aguas-abajo del BLOQUE PP estaba construido y **dormido**: el pasaje del registro
propaga la meta, `Evidence` la toma, el orquestador escribe en la `SubQuestion`, el gate
decide y la prosa narra — y ningún producto emitía una señal `PROJECTED`. Un camino que
nadie recorrió es un camino que no funciona todavía.

Lo que este archivo fija:

* **La meta se DERIVA del ledger, no se guarda.** Dos copias del mismo pronóstico se
  desincronizan: bastaría una corrección que entre al ledger y no a la meta para que el
  informe cite un pronóstico viejo con el track record del nuevo.
* **Vigente = último `as_of`, revisión más alta.** Es la lectura que el `[Lock]` de
  `revision` hace posible: las correcciones conviven con el original y quién manda se
  resuelve al LEER, no pisando filas.
* **Una proyección sin filas puntuadas no se silencia: sale con `n_oos = 0`** y el gate la
  rechaza con su motivo. «No hay proyección» y «hay una sin backtest» son cosas distintas.
* **El peso 0 de la señal proyectada es el diseño, no un descuido.** Con peso > 0 entraría al
  denominador de `coverage_real` y la BAJARÍA. Hay test que lo compara con y sin.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import ledger as led
from shared.data import medida_de_pronostico as med
from modules.macro_monitor.forecasting import procedencia as proc
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base
from shared.registry.projection import MIN_OOS
from shared.registry.signals import PROJECTED, REAL, AxisRegistry, VariableSignal

MODELO = "bvar_minnesota.v1"
# El `series_code` OBSERVABLE. Decía `"pib_real"` —el nombre de la variable en el bloque—,
# que no es ninguna serie: esas filas quedaban `pending` para siempre.
SERIE = "bcrd.xls.pib_2018.serie_original_indice"
INTERVALOS = [[0.80, 2.1, 4.1], [0.90, 1.6, 4.6]]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _emitir(db, horizonte="2027-Q1", as_of="2026-09-01", revision=0, punto=3.1, h=1):
    return led.registrar(db, model_id=MODELO, target_series=SERIE, horizon=horizonte,
                         as_of=as_of, point=punto, intervals=INTERVALOS, revision=revision,
                         h=h, measure=med.DLOG_PCT)


def _puntuar(db, n, horizonte=None):
    """`n` pronósticos ya puntuados bajo el mismo `backtest_id`, para darle backtest.

    Cada uno apunta a un trimestre CALENDARIO distinto, porque así es como se acumula un
    track record: un trimestre se pronostica una sola vez a cada distancia. Lo que los hace
    un conjunto es el horizonte RELATIVO, que es el mismo para todos.
    """
    for i in range(n):
        objetivo = horizonte or f"{2020 + i // 4}-Q{(i % 4) + 1}"
        f = led.registrar(db, model_id=MODELO, target_series=SERIE, horizon=objetivo,
                          as_of=f"2020-{(i % 12) + 1:02d}-01", point=3.0,
                          intervals=INTERVALOS, h=1, measure=med.DLOG_PCT)
        f.status, f.realized, f.abs_error, f.sq_error = "scored", 3.2, 0.2, 0.04
        f.interval_hit_80, f.interval_hit_90 = True, True
        f.realized_period_end = date(2026, 3, 31)
    db.commit()


# ── la derivación ───────────────────────────────────────────────────────────────────


def test_la_meta_sale_del_ledger_campo_por_campo(db):
    fila = _emitir(db)
    m = proc.meta_de(db, fila)
    assert (m.model_id, m.target_series, m.horizon, m.as_of, m.revision) == (
        MODELO, SERIE, "2027-Q1", "2026-09-01", 0)
    assert m.point == pytest.approx(3.1)
    assert m.intervals == ((0.80, 2.1, 4.1), (0.90, 1.6, 4.6))
    # RELATIVO: el conjunto son los pronósticos a la misma distancia, no los de un
    # trimestre concreto — que sería uno solo y nunca alcanzaría el mínimo del gate.
    assert m.backtest_id == led.backtest_id(MODELO, SERIE, 1, med.DLOG_PCT)


def test_sin_filas_puntuadas_la_meta_sale_con_n_oos_cero_y_el_gate_la_rechaza(db):
    m = proc.meta_de(db, _emitir(db))
    assert m.n_oos == 0
    ok, motivo = proc.es_publicable(m)
    assert not ok
    assert "fuera de muestra" in motivo


def test_con_backtest_suficiente_la_proyeccion_es_admisible(db):
    _puntuar(db, MIN_OOS)
    m = proc.meta_de(db, _emitir(db))
    assert m.n_oos == MIN_OOS
    assert m.error_metric == "rmse"
    assert m.n_oos_overlapping is not None, "el solapamiento se declara, no se supone"
    assert m.interval_coverage, "la calibración empírica tiene que viajar con el error"
    ok, motivo = proc.es_publicable(m)
    assert ok, motivo


# ── qué fila es la vigente ──────────────────────────────────────────────────────────


def test_manda_la_revision_mas_alta_del_corte_mas_reciente(db):
    _emitir(db, as_of="2026-09-01", revision=0, punto=3.1)
    _emitir(db, as_of="2026-09-01", revision=1, punto=3.9)
    vig = proc.vigentes(db, hoy=date(2026, 9, 15))
    assert len(vig) == 1
    assert int(vig[0].revision) == 1 and float(vig[0].point) == pytest.approx(3.9)


def test_la_correccion_no_borra_el_original(db):
    """El `[Lock]` de `revision`: la revisión 0 sigue en la tabla para el track record."""
    _emitir(db, as_of="2026-09-01", revision=0)
    _emitir(db, as_of="2026-09-01", revision=1, punto=3.9)
    from modules.macro_monitor.forecasting.models import ForecastLog
    assert db.query(ForecastLog).count() == 2


def test_un_horizonte_ya_cerrado_no_se_publica_como_proyeccion(db):
    _emitir(db, horizonte="2020-Q1", as_of="2019-12-01")
    assert proc.vigentes(db, hoy=date(2026, 9, 15)) == []


def test_una_sola_proyeccion_por_serie_y_es_la_mas_cercana(db):
    _emitir(db, horizonte="2027-Q3", as_of="2026-09-01", punto=9.9)
    _emitir(db, horizonte="2027-Q1", as_of="2026-09-01", punto=3.1)
    por_serie = proc.proyeccion_por_serie(db, hoy=date(2026, 9, 15))
    assert set(por_serie) == {SERIE}
    assert por_serie[SERIE].horizon == "2027-Q1"


# ── el peso 0, que es el diseño ─────────────────────────────────────────────────────


def _eje(con_proyeccion: bool, peso_proyectada: float = 0.0):
    reales = [VariableSignal(key=f"f{i}", label=f"F{i}", state=REAL, weight=1.0)
              for i in range(7)]
    extra = []
    if con_proyeccion:
        extra = [VariableSignal(key="proy", label="Proy", state=PROJECTED,
                                weight=peso_proyectada)]
    return AxisRegistry(sector_key="macro", display_name="Macro", source="BCRD",
                        implemented=True, signals=tuple(reales + extra))


def test_la_proyeccion_con_peso_cero_no_mueve_la_cobertura_real():
    assert _eje(True).coverage_real == _eje(False).coverage_real


def test_con_peso_mayor_que_cero_la_bajaria_y_por_eso_va_en_cero():
    """La razón del peso 0, escrita como test: sin él la cobertura real CAE."""
    assert _eje(True, peso_proyectada=1.0).coverage_real < _eje(False).coverage_real


def test_la_señal_proyectada_llega_igual_al_pipeline(monkeypatch):
    """Peso 0 no es invisibilidad: el registro recorre TODAS las señales."""
    from shared.knowledge.ingest import registry_passages
    from shared.registry.signals import DataRegistry

    monkeypatch.setattr("shared.registry.service.build_data_registry",
                        lambda db: DataRegistry(generated_at="x", axes=(_eje(True),)))
    claves = {p.meta.get("variable") for p in registry_passages(db=object())}
    assert "proy" in claves
