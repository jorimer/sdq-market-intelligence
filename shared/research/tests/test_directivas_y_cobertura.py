"""Pedirle rigor al motor no puede BAJARLE la cobertura, y los porcentajes deben leerse bien.

Informe del 2026-08-14: la pregunta se partió en 5 sub-preguntas, dos de las cuales eran
INSTRUCCIONES mías al motor —«no infieras la composición», «no quiero categorías plausibles»—.
Una instrucción no se ancla a ningún dato, así que arrastraron la cobertura a 40% y degradaron
el informe a «alcance limitado». Cuanto más preciso el encargo, peor la nota.

Y la línea decía «40% anclada a dato real, 40% con ancla declarada»: dos porcentajes ANIDADOS
que se leen como aditivos, dejando al lector buscando el 20% que falta para 100.
"""
from shared.research.assemble import _coverage_line
from shared.research.decompose import directivas, es_directiva, split_question

_PREGUNTA = (
    "Necesito la composición de las importaciones de República Dominicana por país de origen "
    "y capítulo arancelario. Agrega la dependencia importadora del país y la concentración "
    "por socio. Dos condiciones: nombra qué orígenes cubre el sistema y cuáles no. "
    "No infieras la composición: si un cruce no está computado, decláralo. "
    "No quiero \"categorías plausibles\"."
)


class TestDirectivas:
    def test_las_instrucciones_no_cuentan_como_sub_preguntas(self):
        subs = " || ".join(split_question(_PREGUNTA)).lower()
        assert "no quiero" not in subs
        assert "no infieras" not in subs

    def test_las_preguntas_sustantivas_SÍ_sobreviven(self):
        subs = " || ".join(split_question(_PREGUNTA)).lower()
        assert "composición de las importaciones" in subs
        assert "dependencia importadora" in subs

    def test_pedir_rigor_ya_no_baja_la_cobertura(self):
        """El caso real: 5 sub-preguntas de las que 2 eran instrucciones."""
        con_condiciones = len(split_question(_PREGUNTA))
        sin_condiciones = len(split_question(
            "Necesito la composición de las importaciones de República Dominicana por país de "
            "origen y capítulo arancelario. Agrega la dependencia importadora del país y la "
            "concentración por socio."))
        assert con_condiciones == sin_condiciones

    def test_las_directivas_se_registran_no_desaparecen(self):
        d = " ".join(directivas(_PREGUNTA)).lower()
        assert "no infieras" in d and "no quiero" in d

    def test_el_filtro_es_ESTRECHO(self):
        """Una pregunta legítima que pide algo no debe caer como directiva."""
        assert not es_directiva("Agrega la dependencia importadora y la concentración")
        assert not es_directiva("nombra los capítulos de mayor peso")
        assert not es_directiva("¿qué se importa desde China?")

    def test_si_TODO_es_directiva_no_se_queda_sin_sub_preguntas(self):
        subs = split_question('No quiero "categorías plausibles"')
        assert subs and len(subs) == 1


class TestLineaDeCobertura:
    def test_no_se_leen_como_aditivos(self):
        linea = _coverage_line(0.40, 0.40)
        assert "40% anclada a dato real, 40%" not in linea
        assert "60% restante" in linea

    def test_dice_que_no_hay_rubrica_cuando_coinciden(self):
        assert "nada se apoya en rúbrica" in _coverage_line(0.40, 0.40)

    def test_desglosa_la_rubrica_cuando_existe(self):
        linea = _coverage_line(0.40, 0.60)
        assert "40% con dato real y 20% con rúbrica" in linea
        assert "40% restante" in linea

    def test_los_tres_pedazos_suman_cien(self):
        for real, anc in ((0.4, 0.4), (0.4, 0.6), (1.0, 1.0), (0.0, 0.0)):
            linea = _coverage_line(real, anc)
            import re
            nums = [int(x) for x in re.findall(r"(\d+)%", linea)]
            assert sum(nums[-2:]) == 100 or nums[-1] == round((1 - anc) * 100)
