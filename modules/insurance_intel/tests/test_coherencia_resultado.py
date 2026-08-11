"""La compuerta de §5.2 y el cruce contra el estado de resultados.

El caso testigo de cada test es una compañía real del panel 2018-2024, con sus cifras: si
alguien recalibra un umbral y estos tests siguen pasando, la recalibración no rompió la
discriminación que motivó la compuerta.
"""
from modules.insurance_intel.scoring import coherencia_resultado as coh
from modules.insurance_intel.scoring.perfil_sdq import (
    CESION_MAX_SANA, CESION_NO_INTERPRETABLE, INVERSION_DOMINANTE, calcular_ejes,
    motivo_no_publicable,
)


def _ciclo(cesion: float, inversion: float = 0.0, combined: float = 1.40) -> dict:
    return {"años": ["2022", "2023", "2024"], "combined_promedio": combined,
            "loss_volatilidad": 0.05, "cesion_promedio": cesion,
            "inversion_sobre_prima": inversion, "ponderado_por_exposicion": True,
            "pendiente_combined": 0.0, "pendiente_error_estandar": 1.0,
            "ciclo_comparable": True}


class TestCompuertaEjecucion:
    def test_angloamericana_cede_83_no_publica_ejecucion(self):
        ejes = calcular_ejes(_ciclo(cesion=0.83), 1.2, 1.1)
        assert ejes["ejecucion"] is None
        assert "cede 83%" in ejes["ejecucion_no_publicable"]

    def test_crecer_inversion_157_no_publica_ejecucion(self):
        ejes = calcular_ejes(_ciclo(cesion=0.30, inversion=1.57), 1.2, 1.1)
        assert ejes["ejecucion"] is None
        assert "producto de inversiones" in ejes["ejecucion_no_publicable"]

    def test_sura_cede_64_si_publica(self):
        """El corte cae en la brecha 64→77: la cedente normal NO puede quedar barrida."""
        ejes = calcular_ejes(_ciclo(cesion=0.64, combined=0.73), 1.2, 1.1)
        assert ejes["ejecucion"] is not None
        assert ejes["ejecucion_no_publicable"] is None

    def test_resiliencia_se_sigue_publicando(self):
        """Separar los ejes sirve justamente para poder callar uno sin callar el otro."""
        ejes = calcular_ejes(_ciclo(cesion=0.83), 1.2, 1.1)
        assert ejes["ejecucion"] is None
        assert ejes["resiliencia"] is not None
        assert ejes["dimensiones"]["reaseguro"] is not None

    def test_una_sola_constante_para_la_cesion(self):
        """Dos constantes para un mismo hecho económico divergen con el tiempo."""
        assert CESION_NO_INTERPRETABLE == CESION_MAX_SANA

    def test_inversion_ausente_no_dispara(self):
        """Un ejercicio sin 45xx capturado no debe leerse como 'no tiene inversiones'…
        ni al revés: la compuerta solo se enciende CON dato."""
        assert motivo_no_publicable({"cesion_promedio": 0.2}) is None

    def test_umbral_inversion_deja_holgura_al_panel(self):
        """La Monumental (30%) es el segundo del panel; el corte no puede acercársele."""
        assert INVERSION_DOMINANTE >= 2 * 0.30


class TestCruceContraResultado:
    def _ej(self, margen_ing: float, patrimonio: list) -> dict:
        # prima 100 por año; ingresos-gastos = margen_ing × 100
        return {a: {"ingresos_totales": 200.0 + margen_ing * 100.0,
                    "gastos_totales": 200.0, "primas_devengadas": 100.0,
                    "patrimonio": p}
                for a, p in zip(("2022", "2023", "2024"), patrimonio)}

    def test_marca_combined_alto_con_utilidad(self):
        h = coh.evaluar("angloamericana", 1.40, self._ej(0.10, [100, 117, 137]))
        assert h is not None and h["margen_neto"] > 0
        assert "no puede" not in h["detalle"]  # el detalle describe, no juzga
        assert "140%" in h["detalle"]

    def test_no_marca_deterioro_real(self):
        """Unit: combined 440% con margen −330%. Coherente, aunque pésimo."""
        assert coh.evaluar("unit", 4.40, self._ej(-3.30, [100, 60, 40])) is None

    def test_no_marca_multiseguros(self):
        """Combined 194% con patrimonio cayendo: las dos lecturas concuerdan."""
        assert coh.evaluar("multiseguros", 1.94, self._ej(-0.96, [100, 50, 16])) is None

    def test_combined_sano_nunca_es_hallazgo(self):
        assert coh.evaluar("reservas", 0.77, self._ej(0.10, [100, 116, 134])) is None

    def test_sin_prima_no_afirma_nada(self):
        """La ausencia de dato no es un hallazgo — se declara la brecha, no se inventa."""
        vacio = {"2023": {"ingresos_totales": 5.0, "gastos_totales": 1.0,
                          "primas_devengadas": None, "patrimonio": 10.0}}
        assert coh.evaluar("x", 1.50, vacio) is None

    def test_margen_apenas_positivo_no_contradice(self):
        """Entre 0 y 5% lo explica el resultado financiero de cualquier compañía."""
        assert coh.evaluar("x", 1.20, self._ej(0.02, [100, 105, 110])) is None


class TestUnaSolaDefinicionDeLaRegla:
    """La lección sola no alcanzó cinco veces en este módulo: se vuelve test estructural.

    Cualquier función que derive una métrica del combined ratio tiene que CONSULTAR la
    compuerta, no reimplementarla. Se lee el código con `ast` en vez de confiar en que quien
    agregue el próximo motor se acuerde.
    """

    def _fuente(self, mod):
        import ast
        import inspect
        return ast.parse(inspect.getsource(mod))

    def test_ambos_motores_consultan_la_misma_funcion(self):
        import modules.insurance_intel.scoring.isf as isf
        import modules.insurance_intel.scoring.perfil_sdq as psdq

        for mod in (isf, psdq):
            import inspect
            src = inspect.getsource(mod)
            assert "motivo_combined_no_interpretable" in src, (
                f"{mod.__name__} deriva del combined ratio y no consulta la compuerta")

    def test_los_umbrales_viven_en_un_solo_modulo(self):
        """Si el ISF define su propio corte, los dos motores divergen en silencio."""
        import inspect

        import modules.insurance_intel.scoring.isf as isf
        src = inspect.getsource(isf)
        for prohibido in ("CESION_NO_INTERPRETABLE =", "INVERSION_DOMINANTE ="):
            assert prohibido not in src, f"el ISF redefine {prohibido!r} en vez de importarlo"

    def test_el_isf_apaga_las_dos_dimensiones_del_combined(self):
        from modules.insurance_intel.scoring.isf import _raw_metric

        fronting = {"primas_devengadas": 1000.0, "primas_cedidas": 880.0,
                    "siniestros_incurridos": 1200.0, "gastos_operativos": 350.0,
                    "productos_inversion": 50.0, "activos_totales": 3.0e9,
                    "indice_solvencia": 1.8, "indice_liquidez": 1.4}
        assert _raw_metric(fronting, "siniestralidad") is None
        assert _raw_metric(fronting, "resultado_tecnico") is None
        # …y NO toca las que no salen del combined ratio: el índice se sigue publicando.
        assert _raw_metric(fronting, "solvencia") == 1.8
        assert _raw_metric(fronting, "escala") == 3.0e9

    def test_una_aseguradora_normal_conserva_las_dos(self):
        from modules.insurance_intel.scoring.isf import _raw_metric

        normal = {"primas_devengadas": 1000.0, "primas_cedidas": 300.0,
                  "siniestros_incurridos": 550.0, "gastos_operativos": 300.0,
                  "productos_inversion": 50.0}
        assert _raw_metric(normal, "siniestralidad") == 0.55
        assert _raw_metric(normal, "resultado_tecnico") is not None
