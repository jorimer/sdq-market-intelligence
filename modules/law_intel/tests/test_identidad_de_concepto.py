"""El segundo camino a `verificado` — y los candados que impiden que sea «se parece».

La regla fuerte sigue siendo el ORÁCULO: la serie reproduce la línea base que el legislador
escribió, en el año que escribió. Es una coincidencia contra un valor que no se puede
fabricar.

Este camino existe porque varias líneas base son de 2008-2010 y ninguna serie viva llega tan
atrás. Sin él, esos indicadores no son «dudosos»: son inverificables para siempre, y el
informe diría «no lo medimos» sobre un dato que el propio Estado publica con el nombre que el
legislador le puso.

Lo que estos tests protegen es que la puerta no se abra más de eso.
"""
import pytest

from modules.law_intel.bindings import (VERIFICADO_POR, Binding, ExpedienteInvalido, _validar,
                                        cargar_bindings, cobertura, identidad_comprobada)
from modules.law_intel.registro import Expediente, Indicador

NOMBRE = "Índice de recuperación de efectivo en el sector eléctrico (monto real de cobranzas)"


def _exp(nombre=NOMBRE):
    ind = Indicador(id="3.27", eje=3, nombre=nombre, escala="numerica",
                    base_valor=64.0, base_anio=2008, metas={"2025": 85.0})
    return Expediente(id="t", titulo="t", norma="t",
                      meta={"fuentes_admitidas": [{"id": "mem", "nombre": "MEM",
                                                   "del_evaluado": True}]},
                      indicadores=[ind])


def _binding(**kw):
    base = dict(indicador="3.27", serie="s", fuente="mem", mejor="mayor", estado="verificado",
                periodo_verificado="2025", origen="declarado_por_el_evaluado", productor="MEM",
                verificado_por="identidad_de_concepto",
                termino_del_emisor="Índice de Recuperación de Efectivo",
                nota="Salvedad: no se verificó contra la línea base de 2008.")
    return Binding(**{**base, **kw})


class TestLaIdentidadSeCOMPRUEBA:
    """La declaración no se cree. Se contrasta contra el nombre que la ley le puso."""

    def test_el_termino_del_emisor_tiene_que_estar_en_el_nombre_de_la_ley(self):
        vale, motivo = identidad_comprobada("Energía facturada", "Pérdidas en el sector eléctrico")
        assert not vale and "no está en el nombre" in motivo

    def test_coincidir_solo_en_palabras_de_MEDICION_no_alcanza(self):
        """«Índice», «tasa» y «nivel» encabezan medio articulado: identifican la forma, no el
        fenómeno. Sin este corte, un binding a cualquier serie llamada «índice» pasaría."""
        vale, motivo = identidad_comprobada("Índice", NOMBRE)
        assert not vale and "palabras de medición" in motivo

    def test_el_singular_y_el_plural_son_la_misma_palabra(self):
        """El emisor dice «Cobranzas» y la ley «cobranza». Exigir la forma exacta rechazaría
        una identidad real por una `s`."""
        vale, _ = identidad_comprobada(
            "Cobranzas", "Niveles de cobranza en el sector eléctrico (cobro por facturación)")
        assert vale

    def test_un_termino_vacio_no_identifica_nada(self):
        assert not identidad_comprobada("   ", NOMBRE)[0]
        assert not identidad_comprobada("de la", NOMBRE)[0]


class TestLosTresCandados:
    def test_sin_termino_del_emisor_no_promueve(self):
        with pytest.raises(ExpedienteInvalido, match="término"):
            _validar(_exp(), [_binding(termino_del_emisor=None)])

    def test_un_termino_que_no_identifica_no_promueve(self):
        with pytest.raises(ExpedienteInvalido, match="no está en el nombre"):
            _validar(_exp(), [_binding(termino_del_emisor="Energía comprada")])

    def test_no_promueve_con_una_duda_de_comparabilidad_ABIERTA(self):
        """O la duda está resuelta y pasa a `nota`, o el binding no promueve. Mezclarlas
        dejaría promover con el problema todavía sin contestar."""
        with pytest.raises(ExpedienteInvalido, match="ABIERTA"):
            _validar(_exp(), [_binding(nota_comparabilidad="¿mide lo mismo?")])

    def test_sin_la_salvedad_ESCRITA_no_promueve(self):
        """Es el candado que sostiene la decisión: si la salvedad no viaja, la cobertura se
        lee como si todos hubieran pasado por el filtro fuerte."""
        with pytest.raises(ExpedienteInvalido, match="salvedad"):
            _validar(_exp(), [_binding(nota=None)])

    def test_con_los_tres_candados_puestos_promueve(self):
        _validar(_exp(), [_binding()])

    def test_un_camino_inventado_no_carga(self):
        with pytest.raises(ExpedienteInvalido, match="verificado_por"):
            _validar(_exp(), [_binding(verificado_por="me_parece")])


class TestLaCoberturaSeABREPorCamino:
    """Una sola cifra sobre dos filtros distintos es una cifra sobre dos poblaciones."""

    def test_el_expediente_real_declara_los_dos(self):
        c = cobertura("end_2030")
        por = c["medidos_por_camino_de_verificacion"]
        assert set(por) == set(VERIFICADO_POR)
        assert sum(por.values()) == c["medidos"]

    def test_el_oraculo_sigue_siendo_el_camino_por_defecto(self):
        """Si el default fuera el débil, cada binding nuevo entraría por la puerta ancha."""
        assert Binding(indicador="x", serie="s", fuente="mem",
                       mejor="mayor", estado="propuesto").verificado_por == "oraculo"
        por = cobertura("end_2030")["medidos_por_camino_de_verificacion"]
        assert por["oraculo"] > por["identidad_de_concepto"]


def test_toda_verificacion_que_NO_es_por_oraculo_lleva_su_salvedad_al_contexto():
    """ESTRUCTURAL: se computa del estado de los bindings, no de una lista a mano.

    Una lista a mano envejece en cuanto alguien promueve el siguiente, y el que falte es
    justo el que se publicaría sin salvedad.
    """
    from modules.law_intel.ai_context import salvedades_obligatorias

    esperados = {b.indicador for b in cargar_bindings("end_2030").values()
                 if b.cuenta and b.verificado_por != "oraculo"}
    servidos = {s["indicador"] for s in salvedades_obligatorias("end_2030")}
    assert servidos == esperados
    assert esperados, "el barrido quedó vacío: dejó de proteger algo"
    for s in salvedades_obligatorias("end_2030"):
        assert s["salvedad"].strip(), s["indicador"]
        assert s["termino_del_emisor"].strip(), s["indicador"]
