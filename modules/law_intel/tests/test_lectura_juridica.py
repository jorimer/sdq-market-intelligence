"""La lectura jurídica de un expediente.

Es la sección que sostiene el informe entero de la 167-21: dice que el «tiempo de respuesta»
lo exige una resolución del MAP y NO la ley. Un informe que le atribuya a la ley una
exigencia que puso una resolución es refutable leyendo la ley.
"""
import pytest

from modules.law_intel.lectura_juridica import Nota, _validar, cargar, prosa, publicable
from modules.law_intel.registro import ExpedienteInvalido


class TestElGuardDeLaCITA:
    def test_un_articulo_que_el_expediente_NO_consigna_levanta(self):
        """Una lectura sobre un artículo que la tabla no muestra deja al lector con una
        referencia que no puede seguir, y es así como se cuela una cita inventada."""
        with pytest.raises(ExpedienteInvalido, match="no consigna"):
            _validar([Nota(articulo=99, dice="x", fuente="y")], {39, 40, 42})

    def test_sin_FUENTE_levanta(self):
        with pytest.raises(ExpedienteInvalido, match="sin `fuente`"):
            _validar([Nota(articulo=39, dice="x", fuente="  ")], {39})

    def test_sin_TEXTO_levanta(self):
        with pytest.raises(ExpedienteInvalido, match="sin `dice`"):
            _validar([Nota(articulo=39, dice="", fuente="y")], {39})

    def test_dos_lecturas_del_MISMO_articulo_levantan(self):
        with pytest.raises(ExpedienteInvalido, match="dos lecturas"):
            _validar([Nota(articulo=39, dice="a", fuente="f"),
                      Nota(articulo=39, dice="b", fuente="f")], {39})

    def test_un_expediente_SIN_obligaciones_no_bloquea_la_lectura(self):
        """El guard compara contra los artículos que el expediente declara. Si no declara
        ninguno no puede afirmar que la cita esté mal, y negarse sería inventar un error."""
        _validar([Nota(articulo=99, dice="x", fuente="y")], set())


class TestLa16721:
    def test_declara_los_TRES_articulos_que_el_informe_usa(self):
        assert {n.articulo for n in cargar("ley_167_21")} == {39, 40, 42}

    def test_el_42_dice_que_la_exigencia_NO_es_de_la_ley(self):
        """Es la afirmación que hace refutable o no al documento entero."""
        n = [x for x in cargar("ley_167_21") if x.articulo == 42][0]
        assert "no del texto legal" in n.dice
        assert "142-2024" in (n.desarrollada_por or "")

    def test_el_40_trae_la_consecuencia_juridica(self):
        n = [x for x in cargar("ley_167_21") if x.articulo == 40][0]
        assert "no es exigible" in n.dice

    def test_la_prosa_va_en_orden_de_ARTICULO(self):
        """El lector viene de la tabla de obligaciones, que está ordenada así."""
        p = prosa("ley_167_21")
        assert p.index("Artículo 39") < p.index("Artículo 40") < p.index("Artículo 42")

    def test_la_prosa_declara_el_RANGO_de_la_norma_que_desarrolla(self):
        assert "de rango inferior a la ley" in prosa("ley_167_21")

    def test_sin_andamiaje_de_metodo(self):
        """Registro EXTERNO: el lector está fuera de SDQ."""
        p = prosa("ley_167_21").lower()
        assert not any(x in p for x in ("hallazgo", "bluf", "severidad", "conclusión:"))


class TestUnExpedienteQueNoLaDeclara:
    def test_no_es_un_error_y_no_hay_seccion(self):
        assert cargar("end_2030") == []
        assert prosa("end_2030") is None
        assert publicable("end_2030")["total"] == 0
