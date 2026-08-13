"""Socio × capítulo: el cruce que el motor de Research declaraba fuera de alcance.

La pregunta era "¿qué le importamos a China, desglosado por bien?". El informe respondió que
excedía lo que el sistema puede computar. No lo excedía: el cliente de Comtrade pedía
producto × mundo y socio × total, nunca las dos juntas, y la API responde el cruce en una
llamada. Peor: el informe INFIRIÓ la composición pudiendo medirla.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.trade_intel.models.models import (
    TradeDirection, TradeFlow, TradePartnerChapter,
)
from modules.trade_intel.partner_chapters_sync import (
    importaciones_por_capitulo, sync_partner_chapters,
)

engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
Session = sessionmaker(bind=engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    s = Session()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


def _sembrar(db, partner="China", period="2025", caps=(("85", 1040.0), ("84", 946.0))):
    for ch, v in caps:
        db.add(TradePartnerChapter(period=period, partner=partner, partner_code="156",
                                   direction=TradeDirection.import_, chapter=ch, value=v))
    db.commit()


class TestLectura:
    def test_devuelve_capitulos_ordenados_con_su_peso(self, db):
        _sembrar(db)
        r = importaciones_por_capitulo(db, "China")
        assert r["period"] == "2025" and r["n_capitulos"] == 2
        assert r["capitulos"][0]["capitulo"] == "85"
        assert r["capitulos"][0]["pct"] == pytest.approx(52.4, abs=0.2)
        assert r["total_usd_mm"] == pytest.approx(1986.0)

    def test_sin_dato_DECLARA_la_brecha_y_no_cae_al_mundo(self, db):
        """Caer al agregado del país mediría otra cosa — ése fue el error del informe."""
        r = importaciones_por_capitulo(db, "Vietnam")
        assert r["capitulos"] == [] and r["period"] is None and r["total_usd_mm"] is None

    def test_toma_el_ultimo_periodo_si_no_se_pide_uno(self, db):
        _sembrar(db, period="2023", caps=(("85", 1.0),))
        _sembrar(db, period="2025", caps=(("85", 2.0),))
        assert importaciones_por_capitulo(db, "China")["period"] == "2025"


class TestIngesta:
    def test_es_idempotente(self, db, monkeypatch):
        import modules.trade_intel.partner_chapters_sync as m
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                            lambda *a, **k: {"2025": {"85": 1040.0, "84": 946.0}})
        uno = sync_partner_chapters(db, [2025], socios={"156": "China"})
        dos = sync_partner_chapters(db, [2025], socios={"156": "China"})
        assert uno["filas_creadas"] == 2 and dos["filas_creadas"] == 0
        assert dos["filas_actualizadas"] == 2
        assert db.query(TradePartnerChapter).count() == 2

    def test_un_socio_caido_no_tumba_a_los_demas(self, db, monkeypatch):
        def _fetch(rep, code, years, **k):
            if code == "999":
                raise RuntimeError("timeout")
            return {"2025": {"85": 10.0}}
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters", _fetch)
        r = sync_partner_chapters(db, [2025], socios={"156": "China", "999": "Roto"})
        assert r["socios_fallidos"] == ["Roto"]
        assert db.query(TradePartnerChapter).count() == 1

    def test_un_socio_sin_dato_se_reporta_no_se_rellena(self, db, monkeypatch):
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                            lambda *a, **k: {})
        r = sync_partner_chapters(db, [2025], socios={"156": "China"})
        assert r["socios_sin_dato"] == ["China"]
        assert db.query(TradePartnerChapter).count() == 0


class TestNoContaminaLosAgregados:
    def test_vive_en_su_propia_tabla(self, db):
        """Una fila socio × capítulo en `ti_flows` sería indistinguible por `product` de una
        del mundo: cualquier consumidor que sume por producto contaría dos veces."""
        _sembrar(db)
        assert db.query(TradeFlow).count() == 0
        assert db.query(TradePartnerChapter).count() == 2

    def test_el_sync_de_capitulos_ya_no_borra_las_filas_de_socio(self, db):
        """En prod 2026-Q2 tenía 60 filas de socio y 0 de capítulo; el próximo sync de
        capítulos las habría borrado con su `delete()` por período."""
        from modules.trade_intel.partners_sync import PARTNER_PRODUCT
        from modules.trade_intel.service import _persist_flows
        db.add(TradeFlow(period="2026-Q2", product=PARTNER_PRODUCT, partner="China",
                         direction=TradeDirection.import_, value=5.0))
        db.add(TradeFlow(period="2026-Q2", product="Capítulo viejo",
                         direction=TradeDirection.import_, value=1.0))
        db.commit()
        _persist_flows(db, "2026-Q2", [{"product": "Capítulo nuevo", "direction": "import",
                                        "value": 2.0}])
        db.commit()
        quedan = db.query(TradeFlow).filter_by(period="2026-Q2").all()
        productos = {r.product for r in quedan}
        assert PARTNER_PRODUCT in productos, "el sync de capítulos borró las filas de socio"
        assert "Capítulo viejo" not in productos      # sí reemplaza lo suyo
        assert "Capítulo nuevo" in productos
