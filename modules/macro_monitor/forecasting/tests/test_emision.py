"""La emisión al ledger: qué se congela, qué se cuenta y qué NO se escribe.

Lo que este archivo fija, y todo salió de una corrida end-to-end real — no de imaginar casos:

* **Un horizonte que ya cerró al corte NO entra al ledger.** Es el hallazgo caro. El gate de
  admisión ya rechaza esas metas al PUBLICAR, pero rechazar al publicar llega tarde: la fila
  quedó escrita y `puntuar_pendientes` **no consulta el gate**. La puntuación la evaluaría
  contra un observado que ya existía cuando se escribió, y el track record se infla con
  retrospectiva — la contaminación que toda la disciplina point-in-time existe para impedir,
  entrando por la puerta de atrás. La regla va al ESCRIBIR.
* **Los escenarios se cuentan y no se escriben.** Darles una fila de historial sería
  fabricarles uno.
* **Idempotente por la clave de cinco campos**, no por un `if` propio: dos definiciones de
  «ya está» se contradicen, y la que vale es la de la base.
* **Una emisión vacía no es un fallo, y se explica.** En la ventana entre el rezago del IMAE
  y el del PIB la cifra del trimestre está DETERMINADA por identidad; reportar eso como «sin
  estimación» haría parecer que falló un modelo que en realidad está de más.
* **No se escribe lo que no se va a poder puntuar.** Los dobles de este archivo decían
  ``target_series="pib_real"``, que es el nombre de la variable en el bloque y no una serie
  —y así se escribió en producción—: esas filas quedan `pending` para siempre y la sección
  de desempeño lo publica como que el trimestre no cerró. La comprobación va al ESCRIBIR,
  igual que la del horizonte vencido, porque es el único momento en que todavía se puede
  decir por qué.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import emision
from shared.data import medida_de_pronostico as med
from modules.macro_monitor.forecasting.models import ForecastLog
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base

#: El `series_code` OBSERVABLE del PIB — el que `bloque` resuelve para `pib_real`.
SERIE = "bcrd.xls.pib_2018.serie_original_indice"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    # La serie objetivo tiene que EXISTIR: sin una sola observación, la emisión se niega a
    # escribir contra ella —y con razón—, y los tests de esta sección medirían esa negativa
    # en vez de lo que quieren medir.
    s.add(MacroSeries(series_code=SERIE, period="2025-Q4", value=132.0))
    s.commit()
    yield s
    s.close()


# ── la regla que salió de la corrida end-to-end ─────────────────────────────────────


def test_un_horizonte_ya_cerrado_no_es_hacia_adelante():
    corte = date(2026, 8, 20)
    assert not emision._es_hacia_adelante("2026-Q1", corte)
    assert not emision._es_hacia_adelante("2026-Q2", corte)   # cerró el 30-jun
    assert emision._es_hacia_adelante("2026-Q3", corte)


def test_un_horizonte_relativo_no_se_descarta():
    """`+4T` no resuelve a un período absoluto: no se puede verificar, y lo que no se puede
    verificar no se inventa — se deja pasar."""
    assert emision._es_hacia_adelante("+4T", date(2026, 8, 20))


def test_el_horizonte_vencido_no_llega_al_ledger(db, monkeypatch):
    """La prueba que importa: no basta con que el gate lo rechace después."""
    class _Proy:
        def pronosticos(self):
            return [type("P", (), {"h": 1, "horizonte": "2026-Q1", "punto": 3.0,
                                   "intervalos": [[0.80, 2.0, 4.0]],
                                   "model_id": "bvar.v1", "target_series": SERIE,
                                   "measure": med.DLOG_PCT})()]

        def escenarios(self):
            return []

    monkeypatch.setattr(emision.nowcast, "estimar", lambda *a, **k: None)
    monkeypatch.setattr(emision.bloque, "armar",
                        lambda db_: type("B", (), {"Y": ((1.0,),), "nombres": ("pib_real",),
                                                   "trimestres": ("2025-Q4",)})())
    monkeypatch.setattr(emision.bvar, "proyectar_bloque", lambda *a, **k: _Proy())

    em = emision.emitir(db, as_of=date(2026, 8, 20))
    assert em.escritos == 0
    assert em.omitidos_por_vencidos == 1
    assert db.query(ForecastLog).count() == 0, (
        "un pronóstico de un período ya cerrado quedó en el ledger: la puntuación lo va a "
        "evaluar contra un observado que ya existía y el track record se infla")
    assert any("ya había cerrado" in m for m in em.motivos)


def test_el_horizonte_abierto_si_llega_al_ledger(db, monkeypatch):
    """El contraejemplo. Sin él, un `emitir` que no escribe NADA pasaría los dos tests."""
    class _Proy:
        def pronosticos(self):
            return [type("P", (), {"h": 1, "horizonte": "2027-Q1", "punto": 3.0,
                                   "intervalos": [[0.80, 2.0, 4.0]],
                                   "model_id": "bvar.v1", "target_series": SERIE,
                                   "measure": med.DLOG_PCT})()]

        def escenarios(self):
            return []

    monkeypatch.setattr(emision.nowcast, "estimar", lambda *a, **k: None)
    monkeypatch.setattr(emision.bloque, "armar",
                        lambda db_: type("B", (), {"Y": ((1.0,),), "nombres": ("pib_real",),
                                                   "trimestres": ("2026-Q3",)})())
    monkeypatch.setattr(emision.bvar, "proyectar_bloque", lambda *a, **k: _Proy())

    em = emision.emitir(db, as_of=date(2026, 8, 20))
    assert em.escritos == 1 and em.omitidos_por_vencidos == 0
    assert db.query(ForecastLog).count() == 1


# ── los escenarios ──────────────────────────────────────────────────────────────────


def test_los_escenarios_se_cuentan_y_no_se_escriben(db, monkeypatch):
    class _Proy:
        def pronosticos(self):
            return []

        def escenarios(self):
            return [object(), object(), object()]

    monkeypatch.setattr(emision.nowcast, "estimar", lambda *a, **k: None)
    monkeypatch.setattr(emision.bloque, "armar",
                        lambda db_: type("B", (), {"Y": ((1.0,),), "nombres": ("pib_real",),
                                                   "trimestres": ("2026-Q3",)})())
    monkeypatch.setattr(emision.bvar, "proyectar_bloque", lambda *a, **k: _Proy())

    em = emision.emitir(db, as_of=date(2026, 8, 20))
    assert em.escenarios_no_registrados == 3
    assert db.query(ForecastLog).count() == 0


# ── idempotencia ────────────────────────────────────────────────────────────────────


def test_el_mismo_corte_dos_veces_no_duplica(db, monkeypatch):
    class _Proy:
        def pronosticos(self):
            return [type("P", (), {"h": 1, "horizonte": "2027-Q1", "punto": 3.0,
                                   "intervalos": [[0.80, 2.0, 4.0]],
                                   "model_id": "bvar.v1", "target_series": SERIE,
                                   "measure": med.DLOG_PCT})()]

        def escenarios(self):
            return []

    monkeypatch.setattr(emision.nowcast, "estimar", lambda *a, **k: None)
    monkeypatch.setattr(emision.bloque, "armar",
                        lambda db_: type("B", (), {"Y": ((1.0,),), "nombres": ("pib_real",),
                                                   "trimestres": ("2026-Q3",)})())
    monkeypatch.setattr(emision.bvar, "proyectar_bloque", lambda *a, **k: _Proy())

    primera = emision.emitir(db, as_of=date(2026, 8, 20))
    segunda = emision.emitir(db, as_of=date(2026, 8, 20))
    assert (primera.escritos, primera.omitidos_por_duplicado) == (1, 0)
    assert (segunda.escritos, segunda.omitidos_por_duplicado) == (0, 1)
    assert db.query(ForecastLog).count() == 1


# ── la operación y su cascada ───────────────────────────────────────────────────────


def test_la_operacion_esta_registrada_y_anclada_al_calendario():
    """Anclada al calendario de la fuente, no al reloj: un intervalo relativo se desfasa
    solo, y así se sirvió Q1 en informes de agosto en el sync de comercio."""
    import app.main  # noqa: F401 — registra las operaciones
    from shared.operations.service import OPERATIONS

    op = OPERATIONS["macro-forecast-emit"]
    assert op.anclaje == "trimestral"
    assert op.periodo_actual is not None, (
        "sin `periodo_actual` el scheduler no distingue «al día» de «falta un trimestre», y "
        "una corrida que no encuentra el dato espera al período siguiente")


def test_la_ingesta_canonica_dispara_la_emision():
    """El dato nuevo fluye solo aguas abajo. Sin la cascada, alguien tiene que acordarse."""
    import app.main  # noqa: F401
    from shared.operations.service import OPERATIONS

    assert "macro-forecast-emit" in OPERATIONS["macro-canonical-sync"].triggers


# ── lo que no se va a poder puntuar no se escribe ───────────────────────────────────


def test_un_objetivo_que_no_es_una_SERIE_no_llega_al_ledger(db, monkeypatch):
    """El defecto tal cual estaba en producción: `pib_real` es el nombre de la variable en el
    bloque. La fila se escribía sin protestar y no cerraba nunca; la sección de desempeño lo
    publicaba como que el trimestre no había cerrado, que es otra cosa."""
    class _Proy:
        def pronosticos(self):
            return [type("P", (), {"h": 1, "horizonte": "2027-Q1", "punto": 3.0,
                                   "intervalos": [[0.80, 2.0, 4.0]],
                                   "model_id": "bvar.v1", "target_series": "pib_real",
                                   "measure": med.DLOG_PCT})()]

        def escenarios(self):
            return []

    monkeypatch.setattr(emision.nowcast, "estimar", lambda *a, **k: None)
    monkeypatch.setattr(emision.bloque, "armar",
                        lambda db_: type("B", (), {"Y": ((1.0,),), "nombres": ("pib_real",),
                                                   "trimestres": ("2026-Q3",)})())
    monkeypatch.setattr(emision.bvar, "proyectar_bloque", lambda *a, **k: _Proy())
    monkeypatch.setattr(emision.bloque, "codigo_de_variable", lambda db_, n: "pib_real")

    em = emision.emitir(db, as_of=date(2026, 8, 20))
    assert db.query(ForecastLog).count() == 0
    assert any("no resolvió a una serie observable" in m for m in em.motivos), em.motivos


def test_la_serie_y_la_medida_del_BVAR_salen_del_BLOQUE(db, monkeypatch):
    """No de una constante escrita al lado. Dos declaraciones del mismo hecho se
    desincronizan, y la que queda vieja es la que puntúa."""
    visto = {}

    def _proyectar(*_a, **kw):
        visto.update(kw)
        return None

    monkeypatch.setattr(emision.nowcast, "estimar", lambda *a, **k: None)
    monkeypatch.setattr(emision.bloque, "armar",
                        lambda db_: type("B", (), {"Y": ((1.0,),), "nombres": ("pib_real",),
                                                   "trimestres": ("2026-Q3",)})())
    monkeypatch.setattr(emision.bvar, "proyectar_bloque", _proyectar)
    monkeypatch.setattr(emision.bloque, "codigo_de_variable", lambda db_, n: SERIE)

    emision.emitir(db, as_of=date(2026, 8, 20))
    assert visto.get("serie_objetivo") == SERIE
    assert visto.get("medida") == med.DLOG_PCT, (
        "el bloque entrega el PIB en variación logarítmica ×100; si la emisión no lo declara, "
        "el ledger puntúa esa tasa contra el índice de volumen")
