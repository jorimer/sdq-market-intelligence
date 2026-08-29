"""Test the single-pass carteras/creditos aggregation (Mayores Deudores, A, vencida, HHI)."""
from datetime import date

from modules.banking_score.external.sib_data_client import SIBDataClient


def test_compute_carteras_metrics_aggregates_mayores_deudores(monkeypatch):
    client = SIBDataClient.__new__(SIBDataClient)  # no network init

    rows = [
        # entidad, tipoCredito, clasificacionEntidad, sectorEconomico, deuda, deudaVencida
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Créditos Comerciales a Mayores Deudores",
         "clasificacionEntidad": "A", "sectorEconomico": "D - INDUSTRIA", "deuda": 600, "deudaVencida": 10},
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Créditos Comerciales a Menores Deudores",
         "clasificacionEntidad": "A", "sectorEconomico": "G - COMERCIO", "deuda": 200, "deudaVencida": 0},
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Créditos Hipotecarios",
         "clasificacionEntidad": "B", "sectorEconomico": "", "deuda": 200, "deudaVencida": 40},
    ]
    monkeypatch.setattr(client, "_quarters_in_range", lambda ps, pe: ["2025-12"])
    monkeypatch.setattr(client, "_fetch_for_all_types", lambda ep, ps, pe: rows)

    out = client._compute_carteras_metrics("2025-12", "2025-12")
    m = out["Banreservas"][date(2025, 12, 31)]
    assert m["total"] == 1000               # all three rows (incl. mortgage w/o sector)
    assert m["mayores"] == 600              # only the Mayores Deudores row
    assert m["cartera_a"] == 800            # the two clasificación-A rows
    assert m["vencida"] == 50               # 10 + 0 + 40
    # HHI only over sectored rows (600 D + 200 G; mortgage has no sector) → (0.75²+0.25²)·10000
    assert abs(m["hhi"] - 6250.0) < 1.0


def test_concentracion_top10_from_mayores_deudores():
    """The scoring indicator picks up suma_top10 = Mayores Deudores."""
    from types import SimpleNamespace
    from modules.banking_score.scoring.engine import calc_concentracion_top10
    d = SimpleNamespace(suma_top10=600, cartera_total=1000, cartera_bruta=1000)
    r = calc_concentracion_top10(d)
    assert r["raw"] == 60.0  # 600/1000 → 60% en mayores deudores


class TestDesgloseSectorial:
    """El cubo de créditos se guarda ABIERTO por sector Y PROVINCIA, no colapsado a un escalar.

    Hasta ahora, de cada fila del cubo —que trae sector, provincia, mora, mora TEMPRANA de 31
    a 90 días, clasificación, garantía y provisión— se computaba el HHI y se tiraba el resto.
    Es el único lugar donde existe el libro de crédito de TODAS las entidades abierto así: un
    banco tiene su propia fila del cubo y ninguna de las otras noventa y una, y eso es lo que
    permite separar si su deterioro en un sector es suyo o del sector.

    El grano es sector × provincia porque agregar hacia arriba es una suma y bajar exigiría
    volver a descargar los 22 trimestres.
    """

    @staticmethod
    def _corte(monkeypatch, rows):
        from datetime import date as _d
        client = SIBDataClient.__new__(SIBDataClient)
        monkeypatch.setattr(client, "_quarters_in_range", lambda ps, pe: ["2025-12"])
        monkeypatch.setattr(client, "_fetch_for_all_types", lambda ep, ps, pe: rows)
        return client._compute_carteras_metrics("2025-12", "2025-12")["Banreservas"][_d(2025, 12, 31)]

    @staticmethod
    def _celdas(m, sector=None, provincia=None):
        return [c for c in m["por_sector"]
                if (sector is None or c["sector"] == sector)
                and (provincia is None or c["provincia"] == provincia)]

    _FILAS = [
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Comerciales",
         "clasificacionEntidad": "A", "sectorEconomico": "F - CONSTRUCCIÓN",
         "provincia": "DISTRITO NACIONAL", "region": "Región Metropolitana", "deuda": 600,
         "deudaVencida": 60, "deudaVencidaDe31A90Dias": 25, "valorGarantia": 900,
         "valorProvisionCapitalYRendimiento": 30, "cantidadCredito": 12},
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Comerciales",
         "clasificacionEntidad": "B", "sectorEconomico": "F - CONSTRUCCIÓN",
         "provincia": "LA ALTAGRACIA", "region": "Región Este", "deuda": 200,
         "deudaVencida": 40, "deudaVencidaDe31A90Dias": 15, "valorGarantia": 100,
         "valorProvisionCapitalYRendimiento": 20, "cantidadCredito": 3},
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Hipotecarios",
         "clasificacionEntidad": "A", "sectorEconomico": "", "provincia": "AZUA",
         "deuda": 200, "deudaVencida": 5, "deudaVencidaDe31A90Dias": 0, "cantidadCredito": 8},
    ]

    def test_el_grano_es_sector_POR_provincia(self, monkeypatch):
        """Dos filas del mismo sector en provincias distintas son dos celdas, no una."""
        m = self._corte(monkeypatch, self._FILAS)
        constru = self._celdas(m, sector="F - CONSTRUCCIÓN")
        assert len(constru) == 2
        assert {c["provincia"] for c in constru} == {"DISTRITO NACIONAL", "LA ALTAGRACIA"}

    def test_cada_celda_trae_su_mora_y_su_mora_TEMPRANA(self, monkeypatch):
        """La de 31-90 días es un indicador ADELANTADO: se deteriora antes que la vencida."""
        c = self._celdas(self._corte(monkeypatch, self._FILAS),
                         "F - CONSTRUCCIÓN", "DISTRITO NACIONAL")[0]
        assert c["deuda"] == 600 and c["vencida"] == 60
        assert c["vencida_31_90"] == 25      # la señal temprana
        assert c["cartera_a"] == 600         # la fila está clasificada A
        assert c["garantia"] == 900 and c["provision"] == 30 and c["creditos"] == 12

    def test_la_region_se_COPIA_de_la_fuente(self, monkeypatch):
        """No se deriva de un mapa propio, que se desincroniza si la SIB reagrupa."""
        c = self._celdas(self._corte(monkeypatch, self._FILAS),
                         "F - CONSTRUCCIÓN", "LA ALTAGRACIA")[0]
        assert c["region"] == "Región Este"

    def test_agregar_POR_SECTOR_sigue_siendo_una_suma(self, monkeypatch):
        """El grano fino no cuesta la lectura sectorial: se suma sobre las provincias."""
        m = self._corte(monkeypatch, self._FILAS)
        assert sum(c["deuda"] for c in self._celdas(m, sector="F - CONSTRUCCIÓN")) == 800
        assert sum(c["vencida_31_90"] for c in self._celdas(m, sector="F - CONSTRUCCIÓN")) == 40

    def test_lo_que_NO_tiene_sector_se_MIDE_en_vez_de_desaparecer(self, monkeypatch):
        """Sin esta cifra, una cartera con mucho crédito sin sector se leería como si el
        desglose cubriera todo el libro. La hipoteca del fixture no trae sector."""
        m = self._corte(monkeypatch, self._FILAS)
        assert m["deuda_sin_sector"] == 200
        assert m["cobertura_sectorial"] == 0.8      # 800 de 1000

    def test_el_desglose_RECONCILIA_con_los_totales_de_la_entidad(self, monkeypatch):
        """Si el desglose y el total se separan, una de las dos lecturas miente y no hay
        forma de saber cuál."""
        m = self._corte(monkeypatch, self._FILAS)
        assert sum(c["deuda"] for c in m["por_sector"]) + m["deuda_sin_sector"] == m["total"]

    def test_una_fila_sin_provincia_se_ROTULA_en_vez_de_perderse(self, monkeypatch):
        """Un NULL en una clave única se comporta distinto en cada motor; la celda existe."""
        filas = [dict(self._FILAS[0])]
        filas[0].pop("provincia")
        c = self._celdas(self._corte(monkeypatch, filas), "F - CONSTRUCCIÓN")[0]
        assert c["provincia"] == "SIN PROVINCIA" and c["deuda"] == 600

    def test_un_campo_ausente_no_rompe_ni_inventa_cero_en_la_deuda(self, monkeypatch):
        """Las filas reales del cubo no siempre traen garantía o provisión."""
        filas = [dict(self._FILAS[0])]
        del filas[0]["valorGarantia"]
        c = self._celdas(self._corte(monkeypatch, filas), "F - CONSTRUCCIÓN")[0]
        assert c["deuda"] == 600 and c["garantia"] == 0.0
