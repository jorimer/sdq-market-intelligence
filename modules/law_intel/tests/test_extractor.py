"""Las cinco trampas de lectura del articulado, cada una con su test.

Los cinco defectos de la primera extracción venían del INPUT: `pdftotext -layout` aplana el
PDF a una grilla de caracteres y descarta los límites de celda, así que había que
reconstruirlos por distancia horizontal. La versión vigente lee celdas, y estos tests fijan
el comportamiento del normalizador de valor — que es donde queda el juicio real una vez que
la geometría está resuelta.

No abren el PDF: prueban las funciones puras sobre celdas sintéticas. `pdfplumber` solo hace
falta para RE-EXTRAER, que es mantenimiento local y no ruta de servicio.
"""
import pytest

from modules.law_intel.corpus.extractor import _escala, _valor


class TestValorDeCelda:
    def test_coma_de_miles_no_es_decimal(self):
        """`4,460` son 4.460 dólares. Leído como decimal fue 4,46 — mil veces menos, y con
        forma de dato plausible: nada en el informe lo habría delatado."""
        assert _valor("4,460") == 4460.0
        assert _valor("6,351.8") == 6351.8
        assert _valor("12,454.0") == 12454.0

    def test_punto_sigue_siendo_decimal(self):
        assert _valor("2.24") == 2.24
        assert _valor("38.9") == 38.9

    def test_porcentaje_no_invalida_el_numero(self):
        assert _valor("2.24%") == 2.24
        assert _valor("30%") == 30.0

    def test_umbral_se_conserva_como_umbral(self):
        """`< 4%` no es 4.0: cumplir es quedar por debajo, no llegar."""
        assert _valor("< 4%") == "< 4"
        assert _valor("< 4%") != 4.0

    def test_valor_con_banda_al_lado(self):
        assert _valor("421 (Nivel I)") == 421.0

    def test_banda_pefa(self):
        assert _valor("B+") == "B+"
        assert _valor("A-") == "A-"
        assert _valor("D") == "D"

    def test_celda_con_varias_series_no_elige_una(self):
        """2.17 apila Matemáticas / Lectura / Ciencias. Quedarse con la primera publica una
        serie y esconde dos."""
        assert _valor("Matemáticas: 92.9 Lectura: 89.40") == "compuesta"

    def test_meta_redactada_sobrevive(self):
        assert _valor("Pertenecer al nivel II") == "Pertenecer al nivel II"

    def test_celda_vacia(self):
        assert _valor("") is None
        assert _valor("   ") is None


class TestEscala:
    """La escala se nombra por lo que la meta ES. Colapsarlas vuelve comparables cosas que no
    lo son — y comparar un umbral con una banda PEFA no significa nada."""

    def test_numerica(self):
        assert _escala([10.1, 7.6, 5.0], {"2015": 7.6}) == "numerica"

    def test_ordinal_gana_a_numerica_si_hay_una_banda(self):
        assert _escala(["D", "B", "A"], {"2015": "B"}) == "ordinal"

    def test_umbral_no_se_confunde_con_ordinal(self):
        assert _escala([10.5, "< 4"], {"2015": "< 4"}) == "umbral"

    def test_redactada(self):
        assert _escala([421.0, "Pertenecer al nivel II"],
                       {"2015": "Pertenecer al nivel II"}) == "redactada"

    def test_compuesta(self):
        assert _escala(["compuesta"], {"2015": "compuesta"}) == "compuesta"

    def test_sin_meta(self):
        """1.5 y 1.6 solo desagregan en sub-filas: existen y la ley no les fija meta propia.
        Descartarlos dejaba el registro en 81 de 90 pareciendo completo."""
        assert _escala([None], {}) == "sin_meta"


@pytest.mark.parametrize("celda,esperado", [
    ("2008", 2008.0),      # un año suelto sigue siendo número; la columna decide qué es
    ("-0.2", -0.2),        # la tasa de deforestación es negativa por definición
    ("0", 0.0),            # cero es un valor, no una ausencia
])
def test_casos_de_borde(celda, esperado):
    assert _valor(celda) == esperado
