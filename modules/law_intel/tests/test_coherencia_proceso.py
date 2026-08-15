"""Cumplir el proceso no es mover el resultado — y el oráculo tiene que discriminar.

Un detector que marcara toda combinación de mal resultado no serviría: lo que importa es
distinguir «se ejecutó y no sirvió» de «no se ejecutó», que son hallazgos distintos y llevan
a conversaciones distintas.
"""
import pytest

from modules.law_intel.registro import Indicador, cargar
from modules.law_intel.scoring.coherencia_proceso import (AVANCE_MINIMO, CUMPLIMIENTO_ALTO,
                                                          evaluar, resumen, revisar)

EXPEDIENTE = "end_2030"


def ind(**kw):
    base = dict(id="3.28", eje=3, nombre="Pérdidas del sector eléctrico", escala="numerica",
                base_valor=38.9, metas={"2015": 20.0, "2020": 9.0, "2025": 8.5, "2030": 7.0})
    return Indicador(**{**base, **kw})


class TestElCasoQueLoMotiva:
    def test_pacto_electrico_marca_contradiccion(self):
        """148 de 167 compromisos y las pérdidas donde estaban en 2008."""
        h = evaluar("pacto-electrico", 148 / 167, ind(), 38.8, "2025", 167)
        assert h.veredicto == "contradiccion"
        assert h.brecha_cerrada == pytest.approx(0.0033, abs=1e-3)
        f = h.frase()
        assert "88.6%" in f and "no pueden ser ambas satisfactorias" in f

    def test_sale_del_expediente_real(self):
        e = cargar(EXPEDIENTE)
        hs = revisar(EXPEDIENTE, {i.id: i for i in e.indicadores}, "2025")
        cs = [h for h in hs if h.veredicto == "contradiccion"]
        assert {h.indicador for h in cs} == {"3.28", "3.30"}
        assert all(h.instrumento == "pacto-electrico" for h in cs)


class TestDiscrimina:
    def test_bajo_cumplimiento_no_es_contradiccion(self):
        """Un instrumento que no se ejecutó explica su mal resultado sin otra lectura."""
        h = evaluar("x", 0.20, ind(), 38.8, "2025", 100)
        assert h.veredicto == "no_ejecutado"

    def test_resultado_que_avanza_es_coherente(self):
        h = evaluar("x", 0.90, ind(), 20.0, "2025", 100)
        assert h.veredicto == "coherente"

    def test_el_umbral_de_avance_es_el_declarado(self):
        """Se prueba a cada lado del umbral, no EN el umbral: comparar una fracción calculada
        contra su propio borde compara errores de coma flotante, no la regla."""
        def cierra(frac):
            return 38.9 + frac * (8.5 - 38.9)
        assert evaluar("x", 0.9, ind(), cierra(AVANCE_MINIMO * 1.5), "2025", 100).veredicto == "coherente"
        assert evaluar("x", 0.9, ind(), cierra(AVANCE_MINIMO * 0.5), "2025", 100).veredicto == "contradiccion"

    def test_el_umbral_de_cumplimiento_es_el_declarado(self):
        assert evaluar("x", CUMPLIMIENTO_ALTO, ind(), 38.8, "2025", 100).veredicto == "contradiccion"
        assert evaluar("x", CUMPLIMIENTO_ALTO - 0.01, ind(), 38.8, "2025", 100).veredicto == "no_ejecutado"


class TestLoQueNoSeCruza:
    def test_sin_conteo_de_compromisos_no_se_supone_uno(self):
        """El Pacto Educativo tiene el seguimiento congelado desde 2019."""
        h = evaluar("pacto-educativo", None, ind(), 38.8, "2025", None)
        assert h.veredicto == "no_evaluable"
        assert "no hay conteo público" in h.frase()

    def test_cero_compromisos_es_ausencia_de_instrumento(self):
        """El Pacto Fiscal nunca se convocó. Llamarlo «no ejecutado» sugiere que hubo algo
        que ejecutar; el hallazgo es que no hay instrumento."""
        h = evaluar("pacto-fiscal", None, ind(), 14.4, "2025", 0)
        assert h.veredicto == "instrumento_ausente"
        assert "nunca se convocó" in h.frase()
        assert "::" not in h.frase() and h.frase().count(":") == 1

    def test_sin_observacion_no_hay_cruce(self):
        assert evaluar("x", 0.9, ind(), None, "2025", 100).veredicto == "no_evaluable"

    def test_escala_no_numerica_no_admite_brecha(self):
        i = ind(escala="redactada", metas={"2025": "Pertenecer al nivel II"})
        assert evaluar("x", 0.9, i, 400.0, "2025", 100).veredicto == "no_evaluable"

    def test_meta_plana_no_mide_avance(self):
        """Áreas protegidas: sostener 24,4 no se computa como fracción de brecha."""
        i = ind(base_valor=24.4, metas={"2025": 24.4})
        assert evaluar("x", 0.9, i, 24.4, "2025", 100).veredicto == "no_evaluable"


def test_alejarse_se_dice_alejarse():
    """El subsidio eléctrico pasó de 530 a 1.659 con meta de 62,5. «Cerró −241,6% de la
    brecha» es cierto e ilegible."""
    i = ind(id="3.30", base_valor=530.0, metas={"2025": 62.5})
    f = evaluar("pacto-electrico", 0.886, i, 1659.3, "2025", 167).frase()
    assert "se ALEJÓ" in f and "-241" not in f and "−241" not in f


def test_el_resumen_no_llama_contradiccion_a_lo_no_ejecutado():
    hs = [evaluar("a", 0.2, ind(), 38.8, "2025", 100),
          evaluar("b", 0.9, ind(), 38.8, "2025", 100)]
    r = resumen(hs)
    assert r["por_veredicto"] == {"contradiccion": 1, "no_ejecutado": 1}
    assert len(r["contradicciones"]) == 1
