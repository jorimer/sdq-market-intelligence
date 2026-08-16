"""El expediente de la END se contrasta contra el TEXTO LEGAL, no contra sí mismo.

Las metas de `CONTROL` fueron leídas una por una del articulado. Cuatro de ellas están acá
por una razón concreta: la primera extracción las publicó MAL y una muestra de control de 17
filas no lo detectó, porque ninguna de las 17 caía entre las equivocadas. Verificar más filas
de la misma lectura no encuentra errores de esa lectura — lo que los encontró fue contrastar
dos lecturas independientes del mismo PDF.
"""
import pytest

from modules.law_intel.registro import (ESCALAS, ESCALAS_CON_DELTA, ExpedienteInvalido,
                                        Indicador, _validar, cargar)

EXPEDIENTE = "end_2030"

# (id, línea base, [2015, 2020, 2025, 2030]) — leídas del articulado.
CONTROL = {
    "1.1": (22.2, [24.7, 27.1, 33.6, 40.1]),
    "1.2": (3.0, [3.9, 4.8, 5.9, 7.0]),
    "1.8": (24.8, [20.0, 15.0, 10.0, 4.0]),
    "2.1": (10.1, [7.6, 5.0, 3.5, 2.0]),
    "2.4": (33.8, [27.1, 22.5, 18.7, 15.4]),
    "2.20": (2.2, [5.0, 6.0, 6.5, 7.0]),
    "2.21": (72.4, [74.6, 77.0, 78.5, 80.0]),
    "3.9": (3.9, [4.2, 4.4, 4.7, 5.0]),
    "3.10": (24.8, [29.2, 33.5, 43.5, 53.5]),
    "3.25": (13.0, [16.0, 19.0, 21.5, 24.0]),
    "3.27": (64.0, [75.1, 83.0, 85.0, 87.0]),
    "3.28": (38.9, [20.0, 9.0, 8.5, 7.0]),
    "3.30": (530.0, [261.7, 70.0, 62.5, 55.0]),
    "4.1": (3.6, [3.4, 3.2, 3.0, 2.8]),
    "4.2": (24.4, [24.4, 24.4, 24.4, 24.4]),
    "3.1": ("D", ["B", "B+", "A-", "A"]),
    "3.8": ("B", ["B+", "A", "A", "A+"]),
    # ── las cuatro que la primera extracción publicó mal ──
    "3.26": (4460.0, [6351.8, 7753.0, 10103.5, 12454.0]),   # salía 4,46: mil veces menos
    "3.24": (2.24, [8.0, 16.0, 25.0, 30.0]),                # el `%` rompía la lectura
    "2.48": (6.0, [4.40, 2.80, 2.15, 1.50]),
    "2.19": (10.5, ["< 4", "< 4", "< 4", "< 4"]),           # UMBRAL, no el valor 4.0
}

ANIOS = ("2015", "2020", "2025", "2030")


@pytest.fixture(scope="module")
def exp():
    return cargar(EXPEDIENTE)


def test_el_registro_cuadra_con_la_ley(exp):
    assert len(exp.numerados) == 90
    por_eje = {e: len([i for i in exp.numerados if i.eje == e]) for e in (1, 2, 3, 4)}
    assert por_eje == {1: 8, 2: 48, 3: 30, 4: 4}


@pytest.mark.parametrize("ind_id", sorted(CONTROL))
def test_meta_contra_el_texto_legal(exp, ind_id):
    base, metas = CONTROL[ind_id]
    i = next(x for x in exp.indicadores if x.id == ind_id)
    assert i.base_valor == base, f"{ind_id}: línea base"
    assert [i.metas.get(a) for a in ANIOS] == metas, f"{ind_id}: metas"


def test_el_ingreso_per_capita_no_vuelve_a_perder_tres_ceros(exp):
    """El defecto más caro de la primera extracción, con su propio test.

    `4,460` con coma de miles se leyó como `4.46`. Una cifra mil veces menor que además tiene
    forma de dato plausible — nada en el informe la habría delatado.
    """
    i = next(x for x in exp.indicadores if x.id == "3.26")
    assert i.base_valor == 4460.0
    assert i.base_valor > 1000, "la coma de miles volvió a leerse como decimal"


def test_un_umbral_no_se_publica_como_valor(exp):
    """`< 4%` es quedar POR DEBAJO de 4; publicarlo como 4.0 afirma que la meta es llegar."""
    i = next(x for x in exp.indicadores if x.id == "2.19")
    assert i.escala == "umbral"
    assert all(isinstance(v, str) and v.startswith("<") for v in i.metas.values())
    assert not i.admite_delta


def test_solo_lo_numerico_admite_delta(exp):
    assert ESCALAS_CON_DELTA == {"numerica"}
    for i in exp.indicadores:
        assert i.admite_delta == (i.escala == "numerica"), i.id
    # Si TODO admitiera delta, la regla no estaría protegiendo nada.
    assert 0 < sum(i.admite_delta for i in exp.numerados) < len(exp.numerados)


def test_las_seis_escalas_estan_declaradas(exp):
    assert {i.escala for i in exp.indicadores} <= set(ESCALAS)
    # Las tres formas no numéricas que la ley realmente usa deben estar presentes: si una
    # desaparece, alguien las colapsó y volvió comparables cosas que no lo son.
    assert {"ordinal", "umbral", "redactada"} <= {i.escala for i in exp.numerados}


def test_el_denominador_del_eje_1_publica_las_dos_vistas(exp):
    """8 indicadores numerados y 13 filas medibles: la ley desagrega 1.5 y 1.6.

    Tres retrocesos sobre 8 es 37,5%; sobre 13 es 23,1%. La cifra cambia según el
    denominador, así que el registro tiene que sostener los dos.
    """
    e1 = [i for i in exp.indicadores if i.eje == 1]
    assert len([i for i in e1 if not i.subfila_de]) == 8
    assert len(e1) == 13


def test_la_lista_blanca_de_fuentes_rige(exp):
    assert exp.fuente_admitida("mhe")
    assert exp.fuente_admitida("pefa"), "la ley incorpora PEFA en 3.1-3.8: es fuente interna"
    assert not exp.fuente_admitida("banco-mundial")
    assert not exp.fuente_admitida("")


class TestValidacionRechaza:
    """Un expediente que no cuadra NO se sirve. Sin esto, una extracción que perdiera
    indicadores en silencio produciría un informe que mide menos sin decirlo — la misma falla
    que el producto existe para señalarle al Estado."""

    META = {"indicadores_por_eje": {1: 2}}

    def _ind(self, **kw):
        base = dict(id="1.1", eje=1, nombre="x", escala="numerica")
        return Indicador(**{**base, **kw})

    def test_conteo_que_no_cuadra(self):
        with pytest.raises(ExpedienteInvalido, match="no cuadra"):
            _validar(self.META, [self._ind()])

    def test_ids_repetidos(self):
        with pytest.raises(ExpedienteInvalido, match="repetidos"):
            _validar(self.META, [self._ind(), self._ind()])

    def test_subfila_huerfana(self):
        # Dos numerados para que cuadre el conteo y la validación llegue hasta la huérfana:
        # una sub-fila no suma al denominador del eje.
        with pytest.raises(ExpedienteInvalido, match="sin indicador padre"):
            _validar(self.META, [self._ind(), self._ind(id="1.2"),
                                 self._ind(id="9.9·M", subfila_de="9.9")])

    def test_escala_inventada(self):
        with pytest.raises(ExpedienteInvalido, match="escalas desconocidas"):
            _validar(self.META, [self._ind(), self._ind(id="1.2", escala="magica")])

    def test_numerica_con_meta_en_texto(self):
        with pytest.raises(ExpedienteInvalido, match="meta en texto"):
            _validar(self.META, [self._ind(), self._ind(id="1.2", metas={"2015": "< 4"})])

    def test_sin_meta_que_trae_metas(self):
        with pytest.raises(ExpedienteInvalido, match="'sin_meta'"):
            _validar(self.META, [self._ind(),
                                 self._ind(id="1.2", escala="sin_meta", metas={"2015": 1.0})])
