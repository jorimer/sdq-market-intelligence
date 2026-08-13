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


class TestListaDeSociosDerivada:
    """La lista se DERIVA del dato. La versión fija de 5 socios cubría 70,2% del valor
    importado y dejaba fuera 187 países — justo la parte que responde "¿quién más me lo
    puede vender?" en una pregunta sobre restringir importaciones por origen."""

    def _fake(self, monkeypatch, socios):
        monkeypatch.setattr("shared.data.comtrade_client.socios_con_flujo",
                            lambda *a, **k: socios)
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                            lambda rep, code, years, **k: {"2025": {"85": 10.0}})

    def test_ingiere_todos_los_socios_con_flujo(self, db, monkeypatch):
        self._fake(monkeypatch, [("842", "USA", 12460.0), ("156", "China", 5988.0),
                                 ("724", "Spain", 1432.0)])
        r = sync_partner_chapters(db, [2025])
        assert r["socios_intentados"] == 3 and r["socios_ingeridos"] == 3
        assert {x.partner for x in db.query(TradePartnerChapter).all()} == {
            "USA", "China", "Spain"}

    def test_reporta_la_cobertura_del_valor(self, db, monkeypatch):
        """Sin esta cifra el panel se lee como exhaustivo aunque no lo sea."""
        self._fake(monkeypatch, [("842", "USA", 75.0), ("156", "China", 25.0)])
        assert sync_partner_chapters(db, [2025])["cobertura_valor_pct"] == 100.0

    def test_la_cobertura_baja_si_un_socio_falla(self, db, monkeypatch):
        monkeypatch.setattr("shared.data.comtrade_client.socios_con_flujo",
                            lambda *a, **k: [("842", "USA", 75.0), ("156", "China", 25.0)])

        def _fetch(rep, code, years, **k):
            if code == "156":
                raise RuntimeError("timeout")
            return {"2025": {"85": 10.0}}
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters", _fetch)
        r = sync_partner_chapters(db, [2025])
        assert r["socios_fallidos"] == ["China"]
        assert r["cobertura_valor_pct"] == 75.0

    def test_si_no_se_puede_derivar_la_lista_no_se_inventa(self, db, monkeypatch):
        """Cae al mínimo declarado en vez de a una lista de juicio."""
        def _boom(*a, **k):
            raise RuntimeError("comtrade caído")
        monkeypatch.setattr("shared.data.comtrade_client.socios_con_flujo", _boom)
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                            lambda *a, **k: {"2025": {"85": 1.0}})
        r = sync_partner_chapters(db, [2025])
        assert r["socios_intentados"] == 2      # SOCIOS_FALLBACK
        assert r["cobertura_valor_pct"] is None  # no se afirma cobertura sin saber el total

    def test_se_ordenan_por_valor(self, db, monkeypatch):
        """Si la ingesta se corta a la mitad, adentro queda lo que más pesa."""
        from shared.data.comtrade_client import socios_con_flujo  # noqa: F401
        import inspect
        from shared.data import comtrade_client
        assert "out.sort(key=lambda t: -t[2])" in inspect.getsource(
            comtrade_client.socios_con_flujo)
