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


class TestLasMedidasQueSeSumanEnLaMISMA_pasada:
    """Todo lo que el cubo trae y sirve, capturado de una vez.

    Re-hacer el backfill cuesta unas dos horas y media: cada campo que se agregue después
    obliga a pagar esa espera otra vez. Por eso se decidió el conjunto completo antes de
    repoblar, y por eso las dimensiones de cardinalidad baja entran como MEDIDA —`moneda` y
    `persona` tienen dos valores, `clasificacionEntidad` seis; como grano multiplicarían las
    filas por veinticuatro para no decir nada nuevo—.
    """

    @staticmethod
    def _celda(monkeypatch, filas, sector="F - CONSTRUCCIÓN"):
        from datetime import date as _d
        client = SIBDataClient.__new__(SIBDataClient)
        monkeypatch.setattr(client, "_quarters_in_range", lambda ps, pe: ["2025-12"])
        monkeypatch.setattr(client, "_fetch_for_all_types", lambda ep, ps, pe: filas)
        m = client._compute_carteras_metrics("2025-12", "2025-12")["Banreservas"][_d(2025, 12, 31)]
        return [c for c in m["por_sector"] if c["sector"] == sector]

    @staticmethod
    def _fila(**kw):
        base = {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Comerciales",
                "sectorEconomico": "F - CONSTRUCCIÓN", "provincia": "SANTIAGO",
                "clasificacionEntidad": "A", "deuda": 100}
        base.update(kw)
        return base

    def test_la_tasa_del_emisor_YA_viene_ponderada_y_no_se_vuelve_a_multiplicar(self, monkeypatch):
        """`tasaPorDeuda` es el NUMERADOR del promedio, no una tasa.

        Comprobado contra el cubo: una fila de ADEMI trae deuda 500.291 y tasaPorDeuda
        18.435.617 —treinta y siete veces mayor— y el cociente da 36,85%, la banda del
        microcrédito. Multiplicarla otra vez por la deuda desbordó `Numeric(22,4)` y tumbó
        un backfill de 107 minutos; peor, con una columna más ancha habría guardado un
        número sin sentido en silencio. Se acumula TAL CUAL y la tasa sale del cociente.
        """
        c = self._celda(monkeypatch, [
            self._fila(deuda=900, tasaPorDeuda=9000.0),      # 10% ponderado
            self._fila(deuda=100, tasaPorDeuda=2000.0, provincia="AZUA"),   # 20%
        ])
        num = sum(x["tasa_por_deuda"] for x in c)
        base = sum(x["deuda_con_tasa"] for x in c)
        assert num == 11000.0            # se SUMA, no se multiplica
        assert base == 1000
        assert num / base == 11.0        # ponderada; el promedio simple daría 15,0

    def test_una_celda_sin_tasa_no_entra_en_la_BASE_del_promedio(self, monkeypatch):
        """Si entrara con cero, bajaría el promedio de todas las demás."""
        c = self._celda(monkeypatch, [self._fila(deuda=500, tasaPorDeuda=6000.0),
                                      self._fila(deuda=500, provincia="AZUA")])[0:2]
        assert sum(x["deuda_con_tasa"] for x in c) == 500
        assert sum(x["tasa_por_deuda"] for x in c) / 500 == 12.0

    def test_moneda_y_persona_entran_como_MEDIDA_no_como_dimension(self, monkeypatch):
        """Dos valores cada una: como grano cuadruplicarían las filas para decir lo mismo.
        Lo que no es extranjera es nacional; lo que no es física, jurídica."""
        c = self._celda(monkeypatch, [
            self._fila(deuda=300, moneda="Moneda Extranjera", persona="Persona física"),
            self._fila(deuda=700, moneda="Moneda Nacional", persona="Persona jurídica"),
        ])
        assert len(c) == 1, "no debe abrirse una fila por moneda ni por persona"
        assert c[0]["deuda"] == 1000
        assert c[0]["deuda_moneda_extranjera"] == 300
        assert c[0]["deuda_persona_fisica"] == 300

    def test_la_clasificacion_COMPLETA_no_solo_la_A(self, monkeypatch):
        """Con las cinco clases se computa migración y pérdida esperada por sector."""
        c = self._celda(monkeypatch, [self._fila(deuda=100, clasificacionEntidad=k)
                                      for k in ("A", "B", "C", "D", "E")])[0]
        assert [c[f"cartera_{k}"] for k in "abcde"] == [100.0] * 5
        assert c["deuda"] == 500

    def test_el_DESEMBOLSO_es_flujo_y_la_deuda_es_stock(self, monkeypatch):
        """Son cosas distintas: uno dice cuánto se prestó NUEVO, el otro cuánto se debe."""
        c = self._celda(monkeypatch, [self._fila(deuda=1000, valorDesembolso=250)])[0]
        assert c["deuda"] == 1000 and c["desembolso"] == 250

    def test_un_campo_ausente_deja_CERO_medido_y_no_rompe(self, monkeypatch):
        """Las filas reales no siempre traen todos los campos."""
        c = self._celda(monkeypatch, [self._fila(deuda=100)])[0]
        assert c["desembolso"] == 0.0 and c["tasa_por_deuda"] == 0.0
        assert c["deuda"] == 100


class TestElDesgloseSeEscribePorTRIMESTRE:
    """Un fallo cuesta un trimestre, no la serie entera.

    Dos backfills murieron el 2026-08-30 —106 y 107 minutos— y los dos tiraron todo lo
    agregado, porque el desglose se acumulaba en memoria y la escritura ocurría después de
    los veintidós trimestres. Ahora cada corte se entrega al cerrar, se escribe y se LIBERA:
    el fallo cuesta cinco minutos y la memoria queda plana en vez de crecer hasta las 133.000
    celdas.
    """

    @staticmethod
    def _correr(monkeypatch, trimestres, filas_por_q, on_quarter=None):
        client = SIBDataClient.__new__(SIBDataClient)
        monkeypatch.setattr(client, "_quarters_in_range", lambda ps, pe: trimestres)
        monkeypatch.setattr(client, "_fetch_for_all_types",
                            lambda ep, ps, pe: filas_por_q.get(ps, []))
        return client._compute_carteras_metrics(trimestres[0], trimestres[-1],
                                                on_quarter=on_quarter)

    @staticmethod
    def _fila(periodo, deuda=100):
        return {"entidad": "BANRESERVAS", "periodo": periodo, "tipoCredito": "Comerciales",
                "sectorEconomico": "F - CONSTRUCCIÓN", "provincia": "SANTIAGO",
                "clasificacionEntidad": "A", "deuda": deuda}

    def test_se_emite_UNA_vez_por_trimestre_al_cerrarlo(self, monkeypatch):
        vistos = []
        self._correr(monkeypatch, ["2025-09", "2025-12"],
                     {"2025-09": [self._fila("2025-09", 100)],
                      "2025-12": [self._fila("2025-12", 200)]},
                     on_quarter=lambda pe, d: vistos.append((str(pe), d)))
        assert [p for p, _ in vistos] == ["2025-09-30", "2025-12-31"]
        assert vistos[0][1]["Banreservas"][0]["deuda"] == 100
        assert vistos[1][1]["Banreservas"][0]["deuda"] == 200

    def test_lo_emitido_se_LIBERA_para_que_la_memoria_no_crezca(self, monkeypatch):
        from datetime import date
        r = self._correr(monkeypatch, ["2025-09", "2025-12"],
                         {"2025-09": [self._fila("2025-09")],
                          "2025-12": [self._fila("2025-12")]},
                         on_quarter=lambda pe, d: None)
        assert r["Banreservas"][date(2025, 9, 30)]["por_sector"] == []

    def test_los_ESCALARES_sobreviven_porque_el_resto_del_flujo_los_necesita(self, monkeypatch):
        """Se libera lo pesado (`por_sector`), no el hhi ni los totales."""
        from datetime import date
        r = self._correr(monkeypatch, ["2025-12"], {"2025-12": [self._fila("2025-12", 500)]},
                         on_quarter=lambda pe, d: None)
        c = r["Banreservas"][date(2025, 12, 31)]
        assert c["total"] == 500 and c["hhi"] is not None and c["cartera_a"] == 500

    def test_SIN_escritor_el_comportamiento_anterior_se_conserva(self, monkeypatch):
        """`recompute_carteras_metrics` no pasa escritor y sigue recibiendo el desglose
        completo en el retorno: los dos caminos funcionan."""
        from datetime import date
        r = self._correr(monkeypatch, ["2025-12"], {"2025-12": [self._fila("2025-12")]})
        assert len(r["Banreservas"][date(2025, 12, 31)]["por_sector"]) == 1
