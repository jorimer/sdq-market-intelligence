"""La reconciliación sectorial le pregunta la medida a la FILA, no a la variable del bloque.

Dos arreglos del mismo día se cruzaron acá, y el cruce era silencioso:

* uno hizo que `target_series` deje de ser `"pib_real"` —el nombre de la variable en el
  bloque, que no existe como serie— y pase a ser el `series_code` observable;
* el otro puso `bloque.medida_de(...)`, que espera **el nombre de la variable**, para saber
  en qué medida viene el agregado.

Juntos: `medida_de("bcrd.xls.pib_2018.serie_original_indice")` lanza `KeyError`, la sección
sectorial se cae dentro de un `except Exception` que solo escribe un warning, y el informe
sale con dieciséis secciones donde promete diecisiete. Los dos arreglos estaban bien; el
cruce no falla, DESAPARECE.

Y hay una razón de fondo para preguntarle a la fila: en el ledger conviven pronósticos de
DOS motores sobre la misma serie —el nowcast emite una variación trimestral y el BVAR una
interanual—, así que la clase de crecimiento depende de qué fila se está mirando, no de qué
variable la produjo.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor import products_forecast as pf
from modules.macro_monitor.forecasting import ledger, sectoral
from modules.macro_monitor.forecasting import panel as panel_mod
from modules.macro_monitor.models.models import MacroSeries
from shared.data import medida_de_pronostico as med
from shared.database.base import Base

SERIE = panel_mod.PIB_CODE


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(MacroSeries(series_code=SERIE, period="2025-Q3", value=128.0))
    s.commit()
    yield s
    s.close()


def _emitir(db, medida):
    ledger.registrar(db, model_id="bvar_minnesota.5v.v1", target_series=SERIE,
                     horizon="2099-Q4", as_of="2026-08-20", point=4.30, h=1,
                     measure=medida, intervals=[[0.80, 3.0, 5.6], [0.90, 2.4, 6.2]])


def test_el_payload_lleva_la_medida_de_cada_fila(db):
    _emitir(db, med.YOY_PCT)
    payload = pf.MacroForecastProduct(db)._payload(db)
    assert payload["proyecciones"][0]["medida"] == med.YOY_PCT


def test_la_medida_se_resuelve_desde_el_SERIES_CODE_sin_reventar(db, monkeypatch):
    """El cruce exacto. Antes, resolver la medida partiendo de `serie` lanzaba `KeyError`
    porque esperaba el nombre de la variable, y el `except Exception` de la sección se lo
    tragaba: la lectura sectorial desaparecía sin decir por qué."""
    _emitir(db, med.YOY_PCT)
    visto = {}

    def _proyectar(panel, **kw):
        visto.update(kw)
        raise RuntimeError("hasta acá alcanza: lo que se mide es lo que se le pasó")

    monkeypatch.setattr(sectoral, "construir_panel",
                        lambda _db: type("P", (), {"trimestres": ("2026-Q2",)})())
    monkeypatch.setattr(sectoral, "proyectar", _proyectar)

    pf.MacroForecastProduct(db)._payload(db)
    assert visto.get("medida_del_agregado") == panel_mod.INTERANUAL, (
        f"la medida que llegó a la reconciliación fue {visto.get('medida_del_agregado')!r}; "
        "si no llegó ninguna, la resolución reventó y el `except` se lo tragó")


def test_un_agregado_TRIMESTRAL_no_se_reconcilia_contra_un_panel_INTERANUAL(db, monkeypatch):
    """El contraejemplo, y el defecto que la otra rama midió: restar una tasa trimestral de
    una suma de tasas interanuales publicó ocho actividades contrayéndose que ningún modelo
    proyectó. La sección no sale, y no sale con MOTIVO."""
    _emitir(db, med.DLOG_PCT)
    monkeypatch.setattr(sectoral, "construir_panel",
                        lambda _db: type("P", (), {"trimestres": ("2026-Q2",)})())
    monkeypatch.setattr(sectoral, "proyectar",
                        lambda *a, **k: pytest.fail(
                            "reconcilió un agregado trimestral contra un panel interanual"))

    payload = pf.MacroForecastProduct(db)._payload(db)
    assert payload["sectorial"] is None
    assert payload["sectorial_motivo"], (
        "la lectura sectorial no salió y no dijo por qué: una sección que desaparece en "
        "silencio se lee como que el informe no la tiene")
    assert med.DLOG_PCT in payload["sectorial_motivo"]


def test_la_seccion_sectorial_NOMBRA_el_motivo_cuando_no_sale(db, monkeypatch):
    """La prosa se entera del motivo en vez de repetir «no está disponible»."""
    _emitir(db, med.DLOG_PCT)
    monkeypatch.setattr(sectoral, "construir_panel",
                        lambda _db: type("P", (), {"trimestres": ("2026-Q2",)})())
    payload = pf.MacroForecastProduct(db)._payload(db)
    md = pf._md_sectorial(payload)
    assert payload["sectorial_motivo"] in md, md


def test_hoy_la_serie_del_bloque_resuelve_y_la_seccion_SALE(db):
    """Sin este contraejemplo, un `_payload` que nunca arma la sectorial pasa los de arriba.
    Se comprueba contra el mismo camino real, con la fila que el BVAR emite hoy."""
    _emitir(db, med.YOY_PCT)
    assert panel_mod.clase_de_crecimiento(med.YOY_PCT) == sectoral.MEDIDA_DEL_PANEL
    assert date.today() < date(2099, 12, 31)   # el horizonte de la fixture sigue abierto
