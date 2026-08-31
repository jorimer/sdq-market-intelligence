"""El guard conocía dos formas de acortar una cifra y las personas usan una tercera.

`round()` de Python es half-EVEN, y sobre un float el empate casi nunca es exacto en
binario: `round(43.925, 2)` da 43.92. La truncación da lo mismo. Falta half-UP —43.93—, que
es lo que hacen las personas, las planillas y, por imitación, el modelo.

Qué costó: el SDQ Rating de Banco Múltiple Caribe Internacional al 2026-06-30 devolvía 503 y
no se entregaba, porque la prosa citaba «43.93%» de un `cost_to_income` servido como 43.925.
La cifra era CORRECTA. Es el mismo modo de falla que el «5,4 puntos» de un 5,47 que ya había
motivado aceptar la truncación: el guard veta una cifra real cuando cambia de FORMA.
"""

import pytest

from shared.narrative.numeric_guard import (_half_up,
                                            deterministic_uncited_figures)

CTX = {"cost_to_income_pct": 43.925, "morosidad_pct": 3.56}


class TestElEmpateExactoSeRedondeaHaciaARRIBA:

    def test_half_up_es_distinto_de_round_en_el_empate(self):
        assert _half_up(43.925, 2) == 43.93
        assert round(43.925, 2) == 43.92, "si esto cambia, el helper dejó de hacer falta"

    @pytest.mark.parametrize("x,d,esperado", [
        (43.925, 2, 43.93), (5.45, 1, 5.5), (2.5, 0, 3.0), (0.125, 2, 0.13),
        (-1.5, 0, -2.0),
    ])
    def test_la_convencion_humana_en_varios_puntos(self, x, d, esperado):
        assert _half_up(x, d) == esperado

    def test_no_rompe_ante_un_valor_imposible_de_cuantizar(self):
        """El guard nunca puede tumbar la entrega."""
        import math
        assert math.isnan(_half_up(float("inf"), 2))


def _marcas(texto: str) -> list:
    """Envoltorio que FALLA si el guard se traga una excepción.

    La primera versión de estos tests invocaba con los argumentos al revés; el guard captura
    todo —nunca puede tumbar la entrega— y devolvía `[]`, así que las tres aserciones de
    ausencia pasaban en vacío. Un contexto sin ninguna cifra citable no es «todo en orden».
    """
    marcas = deterministic_uncited_figures(CTX, texto)
    assert deterministic_uncited_figures(CTX, "El indicador se ubica en 99.99% al cierre."), (
        "el guard no está marcando NADA: se tragó una excepción y estas aserciones de "
        "ausencia pasarían solas")
    return marcas


class TestLaCifraREALDejaDeVetarse:

    def test_el_caso_que_mato_el_informe_de_Caribe(self):
        texto = ("El ratio de gastos operativos sobre ingresos de 43.93% es el más "
                 "eficiente del panel comparable.")
        assert _marcas(texto) == []

    def test_las_otras_dos_convenciones_siguen_pasando(self):
        """Contra-caso: si el arreglo hubiera reemplazado en vez de sumar, esto caería."""
        for cita in ("43.92%", "43.9%", "3.56%"):
            texto = f"El indicador se ubica en {cita} al cierre."
            assert _marcas(texto) == [], cita

    def test_una_cifra_INVENTADA_se_sigue_marcando(self):
        """El contra-caso que importa: sin esto, abrir el guard del todo pasaría los de
        arriba y el test no protegería nada."""
        texto = "La eficiencia operativa alcanza 71.48% al cierre del período."
        marcas = _marcas(texto)
        assert marcas and "71.48" in marcas[0], marcas

    def test_el_vecino_de_al_lado_NO_entra(self):
        """La apertura es de un ULP en el empate, no de un rango: 43.94 no es una forma de
        decir 43.925 y tiene que seguir marcándose."""
        texto = "El ratio se ubica en 43.94% al cierre."
        assert _marcas(texto), (
            "aceptar el vecino convertiría la tolerancia en un rango")
