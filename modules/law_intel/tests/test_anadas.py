"""Los cuatro candados del tercer camino, cada uno probado por su lado.

Un camino de excepción sin tests con dientes es una excepción que se vuelve la regla. Cada
test de acá construye el binding COMPLETO y le saca UN candado: si el binding sigue pasando,
ese candado no existe.
"""
import pytest

from modules.law_intel.anadas import (Anada, AnadaInvalida, absorbe,
                                      alguna_reproduce_la_base, factor_mas_adverso)
from modules.law_intel.bindings import (Binding, ExpedienteInvalido, VERIFICADO_POR,
                                        cargar_bindings, _validar)
from modules.law_intel.registro import cargar
from modules.law_intel.verificacion import comprobar_absorcion

E = "end_2030"


def _binding(**kw):
    """El 3.23 completo, tal como está en el expediente. Los tests le quitan piezas."""
    base = dict(
        indicador="3.23", serie="ied_usd_mm", fuente="bcrd", mejor="mayor",
        estado="verificado", periodo_verificado="2025",
        verificado_por="revision_declarada",
        origen="declarado_por_el_evaluado", productor="BCRD — Balanza de Pagos.",
        termino_del_emisor="Flujos de la Inversión Extranjera Directa",
        declaracion_del_emisor={
            "texto": "Estadísticas Conforme al Sexto Manual de Balanza de Pagos del FMI",
            "donde": "Pie del cuadro «IED por actividad anual».",
            "verificado_el": "2026-08-22"},
        anadas=({"valor": 2023.7, "fuente": "BCRD vigente"},
                {"valor": 1896.3, "fuente": "BCRD 2014"}),
        nota="Salvedad impresa: la base de la ley es de otra añada.",
    )
    base.update(kw)
    return Binding(**base)


def _validar_uno(b):
    _validar(cargar(E), [b])


class TestLosCandados:
    def test_el_binding_completo_pasa(self):
        _validar_uno(_binding())

    def test_sin_termino_del_emisor_no_pasa(self):
        with pytest.raises(ExpedienteInvalido, match="con qué término"):
            _validar_uno(_binding(termino_del_emisor=None))

    def test_un_termino_que_no_identifica_al_indicador_no_pasa(self):
        """El mismo contraste que exige la identidad de concepto. Ni un ápice menos: si acá
        bastara con declarar cualquier término, el camino sería «explicar la diferencia con
        una historia» y no «el emisor publica lo mismo con otro método»."""
        with pytest.raises(ExpedienteInvalido):
            _validar_uno(_binding(termino_del_emisor="Índice de precios al consumidor"))

    @pytest.mark.parametrize("falta", ["texto", "donde", "verificado_el"])
    def test_la_declaracion_del_emisor_va_completa_y_fechada(self, falta):
        dec = dict(_binding().declaracion_del_emisor or {})
        dec.pop(falta)
        with pytest.raises(ExpedienteInvalido, match=falta):
            _validar_uno(_binding(declaracion_del_emisor=dec))

    def test_sin_declaracion_del_emisor_no_pasa(self):
        """Sin ella, «el emisor revisó su metodología» es una hipótesis NUESTRA sobre por qué
        no cuadra — que es justo lo que este camino no puede admitir."""
        with pytest.raises(ExpedienteInvalido, match="declarar el EMISOR"):
            _validar_uno(_binding(declaracion_del_emisor=None))

    def test_una_sola_anada_no_alcanza(self):
        with pytest.raises(ExpedienteInvalido, match="al menos dos"):
            _validar_uno(_binding(anadas=({"valor": 2023.7, "fuente": "BCRD vigente"},)))

    def test_si_una_anada_reproduce_la_base_el_camino_es_el_ORACULO(self):
        """El candado que impide que la excepción se coma la regla. Si alguna añada reproduce
        la línea base, el oráculo cierra contra ella y este camino sobra."""
        with pytest.raises(ExpedienteInvalido, match="SÍ reproduce la línea base"):
            _validar_uno(_binding(anadas=(
                {"valor": 1625.3, "fuente": "una añada que sí cuadra"},
                {"valor": 2023.7, "fuente": "BCRD vigente"})))

    def test_con_duda_de_comparabilidad_abierta_no_promueve(self):
        with pytest.raises(ExpedienteInvalido, match="ABIERTA"):
            _validar_uno(_binding(nota_comparabilidad="Falta comprobar el universo."))

    def test_sin_nota_la_salvedad_no_viaja_al_informe(self):
        with pytest.raises(ExpedienteInvalido, match="no trae `nota`"):
            _validar_uno(_binding(nota=None))

    def test_propuesto_no_exige_los_candados(self):
        """Los candados protegen la COBERTURA. Un candidato que todavía no cuenta puede estar
        a medio armar sin que eso publique nada."""
        _validar_uno(_binding(estado="propuesto", declaracion_del_emisor=None, anadas=()))


class TestElCuartoCandado:
    """El que se computa contra el dato, no contra el expediente."""

    IND = [i for i in cargar(E).indicadores if i.id == "3.23"][0]
    ANADAS = [Anada(2023.7, "vigente"), Anada(1896.3, "2014"), Anada(1820.2, "republicador")]

    def test_el_factor_va_en_la_direccion_que_perjudica(self):
        """Si más es mejor, lo adverso es el factor que MÁS achica; si menos es mejor, el que
        menos. Elegir por «el más grande» sin mirar la dirección aplicaría la corrección a
        favor en la mitad de los indicadores.

        La primera versión de este test afirmaba que el factor de «menor» pasa de 1. Es falso
        y el código tenía razón: cuando todas las añadas están POR ENCIMA de la línea base,
        los dos factores quedan abajo de 1 y lo que los separa es cuál de los dos extremos se
        toma. Lo que hay que exigir es eso, no un umbral inventado."""
        peor_si_mayor = factor_mas_adverso(1625.3, self.ANADAS, "mayor")
        peor_si_menor = factor_mas_adverso(1625.3, self.ANADAS, "menor")
        candidatos = [1625.3 / a.valor for a in self.ANADAS]
        assert peor_si_mayor == min(candidatos)
        assert peor_si_menor == max(candidatos)
        assert peor_si_mayor < peor_si_menor

    def test_el_3_23_absorbe_con_la_serie_real(self):
        obs = {"2015": 2204.9, "2020": 2559.6, "2025": 5032.8}
        r = absorbe(1625.3, self.ANADAS, "mayor", obs,
                    {"2015": 1700.0, "2020": 2000.0, "2025": 2250.0, "2030": 2500.0})
        assert r.absorbe
        assert round(r.factor, 4) == 0.8031
        # 2030 tiene meta y no tiene observación: no se cuenta ni a favor ni en contra.
        assert [d[0] for d in r.detalle] == ["2015", "2020", "2025"]

    def test_un_margen_que_NO_alcanza_lo_veta(self):
        """El caso 2.6: la meta se cumple por poco y la corrección se la come."""
        r = absorbe(1625.3, self.ANADAS, "mayor", {"2020": 2100.0}, {"2020": 2000.0})
        assert not r.absorbe
        assert "2020" in r.motivo

    def test_sin_observaciones_no_absorbe(self):
        """«No tengo con qué comprobarlo» no es «lo comprobé y da bien»."""
        r = absorbe(1625.3, self.ANADAS, "mayor", {}, {"2020": 2000.0})
        assert not r.absorbe

    def test_solo_corre_para_el_tercer_camino(self):
        b = _binding(verificado_por="oraculo", termino_del_emisor=None,
                     declaracion_del_emisor=None, anadas=())
        assert comprobar_absorcion(b, self.IND, {"2020": 2559.6}) is None

    def test_una_anada_sin_fuente_no_se_usa_para_computar(self):
        with pytest.raises(AnadaInvalida):
            Anada.desde({"valor": 2023.7})

    def test_alguna_reproduce_devuelve_CUAL(self):
        """Un rechazo sin decir cuál manda a adivinar."""
        a = alguna_reproduce_la_base(1625.3, [Anada(1630.0, "la que cuadra"),
                                              Anada(2023.7, "vigente")])
        assert a is not None and a.fuente == "la que cuadra"


class TestElExpedienteReal:
    def test_el_camino_esta_declarado_en_el_vocabulario(self):
        assert "revision_declarada" in VERIFICADO_POR

    def test_todo_binding_por_este_camino_pasa_los_candados(self):
        """Si mañana alguien agrega otro, esto lo somete a lo mismo sin tocar el test."""
        bs = cargar_bindings(E)
        por_aca = [b for b in bs.values()
                   if b.cuenta and b.verificado_por == "revision_declarada"]
        assert por_aca, "no hay ninguno: el barrido no estaría probando nada"
        for b in por_aca:
            _validar_uno(b)
