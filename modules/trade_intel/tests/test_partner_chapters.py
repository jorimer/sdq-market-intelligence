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
        assert uno["filas_creadas"] == 2
        # La segunda corrida SALTA (reanudable): no re-pide ni duplica.
        assert dos["filas_creadas"] == 0 and dos["socios_saltados"] == 1
        assert db.query(TradePartnerChapter).count() == 2
        # Y con `forzar` sí reescribe en sitio, sin duplicar.
        tres = sync_partner_chapters(db, [2025], socios={"156": "China"}, forzar=True)
        assert tres["filas_actualizadas"] == 2 and tres["filas_creadas"] == 0
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


class TestReanudable:
    """Recorrer 192 socios toma ~40 min y la corrida del 2026-08-13 murió en el 118 por un
    reinicio del contenedor. Sin reanudación, terminar la cola obliga a rehacerlo entero."""

    def _fetch_espia(self, monkeypatch):
        pedidos = []

        def _f(rep, code, years, **k):
            pedidos.append(code)
            return {str(y): {"85": 10.0} for y in years}
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters", _f)
        return pedidos

    def test_salta_al_que_ya_tiene_todos_los_años(self, db, monkeypatch):
        pedidos = self._fetch_espia(monkeypatch)
        socios = {"156": "China", "842": "USA"}
        sync_partner_chapters(db, [2024, 2025], socios=socios)
        assert len(pedidos) == 2
        pedidos.clear()
        r = sync_partner_chapters(db, [2024, 2025], socios=socios)
        assert pedidos == [], "volvió a pedir socios que ya estaban"
        assert r["socios_saltados"] == 2

    def test_NO_salta_si_le_falta_un_año(self, db, monkeypatch):
        """Por socio × AÑO. Dar por hecho el socio completo dejaría huecos invisibles."""
        pedidos = self._fetch_espia(monkeypatch)
        sync_partner_chapters(db, [2025], socios={"156": "China"})
        pedidos.clear()
        sync_partner_chapters(db, [2024, 2025], socios={"156": "China"})
        assert pedidos == ["156"], "saltó un socio al que le faltaba 2024"

    def test_solo_pide_la_cola(self, db, monkeypatch):
        """El caso real: 118 ya adentro, se piden los que faltan y nada más."""
        pedidos = self._fetch_espia(monkeypatch)
        sync_partner_chapters(db, [2025], socios={"156": "China", "842": "USA"})
        pedidos.clear()
        r = sync_partner_chapters(db, [2025],
                                  socios={"156": "China", "842": "USA", "422": "Lebanon"})
        assert pedidos == ["422"]
        assert r["socios_saltados"] == 2 and r["socios_ingeridos"] == 3

    def test_forzar_re_pide_todo(self, db, monkeypatch):
        """La fuente REVISA años ya publicados; tiene que haber forma de re-pedirlos."""
        pedidos = self._fetch_espia(monkeypatch)
        sync_partner_chapters(db, [2025], socios={"156": "China"})
        pedidos.clear()
        sync_partner_chapters(db, [2025], socios={"156": "China"}, forzar=True)
        assert pedidos == ["156"]

    def test_el_saltado_cuenta_para_la_cobertura(self, db, monkeypatch):
        """Saltar no es perder: el dato está, así que la cobertura no debe bajar."""
        monkeypatch.setattr("shared.data.comtrade_client.socios_con_flujo",
                            lambda *a, **k: [("156", "China", 60.0), ("842", "USA", 40.0)])
        self._fetch_espia(monkeypatch)
        assert sync_partner_chapters(db, [2025])["cobertura_valor_pct"] == 100.0
        r = sync_partner_chapters(db, [2025])
        assert r["socios_saltados"] == 2 and r["cobertura_valor_pct"] == 100.0


class TestIdentidadPorCodigo:
    """La identidad del socio es su CÓDIGO M49, no su etiqueta.

    Con el índice único por NOMBRE, la misma corriente entró dos veces al cambiar la lista fija
    en español ("Estados Unidos", "Brasil", "México", "España") por la derivada de Comtrade en
    inglés ("USA", "Brazil", "Mexico", "Spain"): el panel reportaba 196 socios donde hay 192 y
    el ranking por valor gastaba dos cupos en el mismo país.
    """

    def test_el_mismo_codigo_con_otra_etiqueta_NO_duplica(self, db, monkeypatch):
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                            lambda *a, **k: {"2025": {"85": 10.0}})
        sync_partner_chapters(db, [2025], socios={"842": "Estados Unidos"})
        sync_partner_chapters(db, [2025], socios={"842": "USA"}, forzar=True)
        filas = db.query(TradePartnerChapter).all()
        assert len(filas) == 1, "la misma corriente entró dos veces bajo otro nombre"

    def test_la_etiqueta_se_refresca_a_la_de_la_fuente(self, db, monkeypatch):
        """El nombre es etiqueta: la ingesta nueva manda."""
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                            lambda *a, **k: {"2025": {"85": 10.0}})
        sync_partner_chapters(db, [2025], socios={"842": "Estados Unidos"})
        sync_partner_chapters(db, [2025], socios={"842": "USA"}, forzar=True)
        assert db.query(TradePartnerChapter).first().partner == "USA"

    def test_dos_socios_distintos_siguen_siendo_dos(self, db, monkeypatch):
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                            lambda *a, **k: {"2025": {"85": 10.0}})
        sync_partner_chapters(db, [2025], socios={"842": "USA", "156": "China"})
        assert db.query(TradePartnerChapter).count() == 2

    def test_el_conteo_del_panel_no_infla(self, db, monkeypatch):
        """196 socios donde había 192: el ranking contaba países dos veces."""
        monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                            lambda *a, **k: {"2025": {"85": 10.0}})
        sync_partner_chapters(db, [2025], socios={"842": "Estados Unidos", "156": "China"})
        sync_partner_chapters(db, [2025], socios={"842": "USA", "156": "China"}, forzar=True)
        distintos = {r.partner_code for r in db.query(TradePartnerChapter).all()}
        assert len(distintos) == 2


def test_un_codigo_tiene_UNA_sola_etiqueta(db, monkeypatch):
    """Deduplicar por código sin normalizar la etiqueta partió los capítulos de un país entre
    sus dos nombres: en prod quedaron 52 bajo "USA" y 44 bajo "Estados Unidos", y como la
    lectura es por nombre, consultar "USA" devolvía la mitad de su comercio. El arreglo había
    empeorado la lectura, que es peor que el defecto original."""
    monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                        lambda *a, **k: {"2025": {"85": 10.0, "84": 20.0}})
    sync_partner_chapters(db, [2025], socios={"842": "Estados Unidos"})
    sync_partner_chapters(db, [2025], socios={"842": "USA"}, forzar=True)
    etiquetas = {r.partner for r in db.query(TradePartnerChapter)
                 .filter_by(partner_code="842").all()}
    assert etiquetas == {"USA"}, f"un código con dos etiquetas parte su comercio: {etiquetas}"


def test_la_lectura_por_nombre_devuelve_el_pais_COMPLETO(db, monkeypatch):
    monkeypatch.setattr("shared.data.comtrade_client.fetch_partner_chapters",
                        lambda *a, **k: {"2025": {"85": 10.0, "84": 20.0}})
    sync_partner_chapters(db, [2025], socios={"842": "Estados Unidos"})
    sync_partner_chapters(db, [2025], socios={"842": "USA"}, forzar=True)
    r = importaciones_por_capitulo(db, "USA")
    assert r["n_capitulos"] == 2 and r["total_usd_mm"] == 30.0
