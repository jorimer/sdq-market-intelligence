"""La agregación del sistema colombiano: las dos formas de hacerla mal.

Las dos están medidas contra el dato real del corte 2026-06-30, no supuestas.
"""
import pytest

from shared.data.sfc_client import SFCClient, agregar_cartera, agregar_solvencia


def _solvencia_de(*entidades):
    """Filas al estilo de `x586-r5d2`: (código, patrimonio técnico, APNR)."""
    filas = []
    for codigo, patrimonio, apnr in entidades:
        filas.append({"codigo_entidad": codigo, "concepto": "PATRIMONIO TÉCNICO",
                      "valor": str(patrimonio)})
        filas.append({"codigo_entidad": codigo,
                      "concepto": "TOTAL ACTIVOS PONDERADOS POR NIVEL DE RIESGO",
                      "valor": str(apnr)})
    return filas


class TestSolvencia:
    def test_es_el_cociente_de_los_agregados_y_no_el_promedio(self):
        """Un banco grande con 10% y uno chico con 30% NO dan 20% de sistema.

        Con el dato real del 2026-06-30 la diferencia es de 0,83 puntos porcentuales:
        18,2564% agregando contra 17,4240% promediando las 30 relaciones por entidad. Un
        promedio le da el mismo peso a un banco de dos billones que a uno de veinte mil
        millones.
        """
        filas = _solvencia_de(("grande", 100, 1000), ("chico", 3, 10))
        agg = agregar_solvencia(filas)
        # Σ patrimonio / Σ APNR = 103 / 1010 = 10,198 %
        assert agg["solvencia_total_sistema_pct"] == pytest.approx(10.198, abs=0.001)
        # promediar los ratios de las dos entidades daría 20 %: casi el doble
        assert (10.0 + 30.0) / 2 == pytest.approx(20.0)

    def test_sin_denominador_no_se_inventa_un_ratio(self):
        agg = agregar_solvencia([{"codigo_entidad": "x", "concepto": "PATRIMONIO TÉCNICO",
                                  "valor": "100"}])
        assert agg["solvencia_total_sistema_pct"] is None

    def test_cuenta_las_entidades_que_agregó(self):
        agg = agregar_solvencia(_solvencia_de(("a", 1, 10), ("b", 2, 20), ("c", 3, 30)))
        assert agg["entidades"] == 3


def _cartera(*filas):
    return [{"unicap": uc, "desc_renglon": renglon,
             "_1_saldo_de_la_cartera_a": str(saldo), "_2_vigente": str(vigente)}
            for uc, renglon, saldo, vigente in filas]


class TestCartera:
    def test_no_suma_el_total_con_sus_componentes(self):
        """Dentro de una unidad de captura conviven el renglón TOTAL y sus partes.

        Sumar todo daba 1,25x la cartera real del sistema colombiano — 950 billones donde
        hay 758.
        """
        filas = _cartera(("2", "TARJETA DE CRÉDITO TOTAL", 100, 90),
                         ("2", "TARJETA HASTA 2 SMMLV", 40, 36),
                         ("2", "TARJETA MAYOR 2 SMMLV", 60, 54))
        assert agregar_cartera(filas)["cartera_bruta_sistema"] == 100

    def test_las_unidades_de_captura_si_se_suman(self):
        """Las 32 son modalidades disjuntas: ahí no hay doble conteo."""
        filas = _cartera(("2", "TARJETA DE CRÉDITO TOTAL", 100, 90),
                         ("5", "VEHÍCULO", 50, 45))
        assert agregar_cartera(filas)["cartera_bruta_sistema"] == 150

    def test_descarta_la_unidad_cuyo_total_no_cuadra(self):
        """Si el TOTAL deja de ser la suma de sus partes, cambió la jerarquía del emisor y
        ya no sabemos leer ese cuadro: se descarta declarando el motivo, no se elige."""
        filas = _cartera(("2", "TARJETA DE CRÉDITO TOTAL", 100, 90),
                         ("2", "TARJETA HASTA 2 SMMLV", 40, 36),
                         ("2", "TARJETA MAYOR 2 SMMLV", 999, 900))
        agg = agregar_cartera(filas)
        assert agg["cartera_bruta_sistema"] is None
        assert agg["avisos"] and "no cuadra" in agg["avisos"][0]

    def test_la_mora_no_suma_los_buckets_que_se_solapan(self):
        """El cuadro trae «vencida 1-2», «1-3» y «1-4 meses» a la vez: sumarlos cuenta la
        misma cartera varias veces. La mora es saldo menos vigente."""
        agg = agregar_cartera(_cartera(("5", "VEHÍCULO", 200, 180)))
        assert agg["cartera_vencida_sistema"] == 20
        assert agg["morosidad_sistema_pct"] == 10.0


class TestContrato:
    def test_el_agregado_es_calculo_propio_y_no_reventa_del_dato(self):
        """La SFC publica por entidad; el sistema lo calculamos nosotros. Por eso el
        share-alike de CC BY-SA, que retiene el activo VERBATIM, no alcanza al boletín."""
        assert SFCClient.DERIVACION == "derived"
        assert "-SA" in SFCClient.license.upper()

    def test_el_fixture_trae_agregados_reales_y_coherentes(self):
        recs = SFCClient().fetch()
        solvencias = [r for r in recs if r.series == "solvencia_total_sistema_pct"]
        assert len(solvencias) >= 4
        assert all(10 < r.value < 30 for r in solvencias), "solvencia fuera de rango creíble"
        assert all(r.dimension == "COL" and r.unit == "%" for r in solvencias)
        moras = [r for r in recs if r.series == "morosidad_sistema_pct"]
        assert all(0 < r.value < 20 for r in moras)
