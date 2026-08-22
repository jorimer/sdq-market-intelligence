"""La sonda: el filtro barato que descarta candidatos antes de que cuesten un conector.

Cada test fija un caso REAL del barrido de los 67 indicadores del expediente de la END. El
orden va del más caro al más barato: primero lo que impide que la sonda se convierta en un
atador automático, que es el único modo en que esta herramienta puede hacer daño.
"""
from modules.law_intel.registro import Indicador
from modules.law_intel.sonda import sondear


def _ind(base, anio="2010", **kw):
    return Indicador(id="X.1", eje=2, nombre="indicador", escala="numerica",
                     base_valor=base, base_anio=anio, **kw)


class TestLoQueImpideQueSeVuelvaUnAtadorAutomatico:
    def test_el_veredicto_mas_fuerte_NO_dice_verificado(self):
        """Dice `revisar_concepto`: «sobrevivió al filtro barato, andá a mirar qué mide».

        El caso que lo prueba está en este mismo expediente: el 2.34 (saneamiento) da 80,77
        contra una base legal de 82,7 —Δ 2,3%— y está DESCARTADO con razón, porque el emisor
        cambió su escala en 2015. La cercanía de niveles es justamente lo que haría pasar ese
        cambio de definición por un dato comparable. La sonda mide NIVEL; ese descarte era de
        DEFINICIÓN y ninguna tolerancia numérica lo habría visto."""
        s = sondear(_ind(82.7, "2007"), [("2007", 80.769)])
        assert s.veredicto == "revisar_concepto_con_salvedad"
        assert "verificado" not in s.veredicto
        assert s.sobrevive, "sobrevivir al filtro no es lo mismo que estar verificado"

    def test_sobrevivir_no_es_una_promocion(self):
        s = sondear(_ind(24.8, "2008"), [("2008", 25.007)])
        assert s.veredicto == "revisar_concepto"
        assert "AHORA hay que comprobar qué mide" in (s.motivo or "")


class TestLosCasosRealesDelBarrido:
    def test_el_homicidio_es_la_coincidencia_mas_limpia(self):
        s = sondear(_ind(24.8, "2008"), [("2008", 25.007)])
        assert s.delta_pct == 0.8 and s.veredicto == "revisar_concepto"

    def test_sin_la_transformacion_un_candidato_BUENO_parece_pesimo(self):
        """El error más caro de usar esto mal, y me pasó: la ley pide ANALFABETISMO y el
        emisor publica alfabetización. Crudo da 752% de discrepancia y lo habría descartado;
        con el complemento coincide al 0,4%. Un «descartar» sin haber revisado la
        transformación no es un descarte: es una pregunta sin responder."""
        crudo = sondear(_ind(10.5), [("2010", 89.54)])
        assert crudo.veredicto == "descartar"
        conv = sondear(_ind(10.5), [("2010", 89.54)], transformar=lambda v: 100 - v)
        assert conv.veredicto == "revisar_concepto" and conv.delta_pct == 0.4

    def test_una_diferencia_de_CONCEPTO_se_delata_en_el_numero(self):
        """El 2.37: la ley mide desocupación AMPLIADA (definición dominicana) y el emisor da
        la abierta modelada por la OIT. 5,21 contra 14,3."""
        s = sondear(_ind(14.3), [("2010", 5.212)])
        assert s.veredicto == "descartar" and s.delta_pct > 60


class TestLoQueNoSePuedeContrastar:
    def test_sin_dato_en_el_ano_base_NO_es_un_descarte(self):
        """Que la serie no llegue al año base no dice nada sobre qué mide. Confundirlo con
        un descarte tiraría candidatos buenos por un hueco de cobertura."""
        s = sondear(_ind(2.2, "2009"), [("2007", 1.9), ("2010", 1.887)])
        assert s.veredicto == "sin_dato_en_la_base"
        assert not s.sobrevive
        assert "2007" in (s.motivo or "") and "2010" in (s.motivo or "")

    def test_una_base_ORDINAL_no_tiene_oraculo(self):
        """Los ocho indicadores PEFA fijan su base en letras («D», «B», «D+»). No hay delta
        porcentual posible y hay que evaluarlos a mano — se declara en vez de simular."""
        s = sondear(_ind("D+", "2007"), [("2007", 3.0)])
        assert s.veredicto == "sin_oraculo"

    def test_una_base_de_CERO_no_admite_delta_porcentual(self):
        """El 3.11 y el 3.12 fijan base 0 (instituciones acreditadas). Dividir por cero o
        declarar 100% de discrepancia serían las dos formas de mentir acá."""
        s = sondear(_ind(0.0), [("2010", 3.0)])
        assert s.veredicto == "sin_oraculo" and "0" in (s.motivo or "")

    def test_una_serie_vacia_se_declara_como_tal(self):
        s = sondear(_ind(24.4, "2009"), [])
        assert s.veredicto == "sin_dato_en_la_base"
        assert "no devolvió observaciones" in (s.motivo or "")


def test_una_serie_lejos_de_la_base_no_dice_que_esta_vacia():
    """Tres situaciones distintas dichas iguales mandan al lector a la conclusión errónea.

    «La serie no devolvió observaciones» sobre una serie de seis años se lee como que el
    conector está roto. Lo que pasa es otra cosa y se resuelve distinto: el legislador fijó
    la línea base en un año que la fuente no cubre. Salió con el conector del MEM, cuyas
    series arrancan en 2019 contra bases de 2008.
    """
    from modules.law_intel.registro import Indicador
    from modules.law_intel.sonda import sondear

    ind = Indicador(id="3.27", eje=3, nombre="CRI", escala="numerica",
                    base_valor=64.0, base_anio=2008, metas={"2025": 85.0})
    s = sondear(ind, [("2019", 70.4), ("2024", 59.4)])
    assert s.veredicto == "sin_dato_en_la_base"
    assert "2019-2024" in s.motivo
    assert "no devolvió observaciones" not in s.motivo
    # Y la serie realmente vacía sigue diciendo lo suyo.
    assert "no devolvió observaciones" in sondear(ind, []).motivo


class TestLaVentanaPromediada:
    """Para nueve indicadores la ley no fechó la línea base con un año sino con una ventana.

    Rendirse ahí dejaba a esos indicadores sin la comprobación fuerte para siempre: no es que
    el oráculo fallara, es que nunca se le preguntaba.

    Que la lectura correcta sea el promedio no se supuso, se comprobó sobre el 3.22 contra la
    serie viva: la razón exportaciones/importaciones va de 0,639 a 0,850 dentro de la ventana
    y NINGÚN año suelto cae a menos del 2% de la base legal. Solo el promedio, a 0,9%.
    """

    def _ind(self, texto, base=0.75):
        from modules.law_intel.registro import Indicador

        return Indicador(id="3.22", eje=3, nombre="Razón exportaciones sobre importaciones",
                         escala="numerica", base_valor=base, base_anio=None,
                         base_anio_texto=texto, metas={"2030": 1.0})

    #: Los seis años reales de la ventana, tomados del emisor el 2026-08-21.
    SERIE = [("2005", 0.8502), ("2006", 0.7941), ("2007", 0.7764),
             ("2008", 0.6390), ("2009", 0.7136), ("2010", 0.6843)]

    def test_el_promedio_de_la_ventana_reproduce_la_linea_base(self):
        from modules.law_intel.sonda import sondear

        s = sondear(self._ind("2005- 2010"), self.SERIE)
        assert s.veredicto == "revisar_concepto"
        assert s.delta_pct is not None and s.delta_pct <= 2.0
        assert s.anio_base == "2005-2010"

    def test_y_NINGUN_ano_suelto_lo_reproduce(self):
        """Es lo que vuelve discriminante la coincidencia. Con una serie plana, acertar
        promediando no diría nada: acertaría cualquier lectura."""
        base = 0.75
        cerca = [a for a, v in self.SERIE if abs(v - base) / base * 100 <= 2.0]
        assert not cerca, f"si algún año suelto casara, el promedio no probaría nada: {cerca}"

    def test_la_lectura_VIAJA_con_el_resultado(self):
        """Un acierto promediando seis años y uno contra un año exacto no son la misma
        evidencia, y quien decide el binding tiene que poder distinguirlos."""
        from modules.law_intel.sonda import sondear

        s = sondear(self._ind("Promedio 2005- 2010"), self.SERIE)
        assert "promedio de la ventana 2005-2010" in (s.lectura or "")
        assert "completa" in (s.lectura or "")

    def test_una_ventana_INCOMPLETA_no_se_promedia(self):
        """Un promedio de tres años sobre una ventana de seis es otro número, y se parecería
        lo suficiente como para pasar por bueno. Misma regla que los conteos regionales."""
        from modules.law_intel.sonda import sondear

        s = sondear(self._ind("2005- 2010"), self.SERIE[3:])
        assert s.veredicto == "sin_dato_en_la_base"
        assert "faltan" in s.motivo and "2005" in s.motivo

    def test_un_rango_TRUNCADO_no_se_adivina(self):
        """«2005-» es un defecto de transcripción del registro. Completar el año que falta
        sería inventar el período sobre el que se promedia."""
        from modules.law_intel.sonda import sondear, ventana_de

        assert ventana_de("2005-") is None
        assert sondear(self._ind("2005-"), self.SERIE).veredicto == "sin_oraculo"

    def test_la_ventana_NO_afloja_la_tolerancia(self):
        """El contrapeso: el camino nuevo usa el mismo umbral que el del año exacto."""
        from modules.law_intel.sonda import sondear

        s = sondear(self._ind("2005- 2010", base=0.40), self.SERIE)
        assert s.veredicto == "descartar"

    def test_el_ano_exacto_sigue_teniendo_prioridad(self):
        """Si la ley declara un año, se usa ese. La ventana es para cuando no lo hay."""
        from modules.law_intel.registro import Indicador
        from modules.law_intel.sonda import sondear

        i = Indicador(id="x", eje=1, nombre="n", escala="numerica", base_valor=0.6843,
                      base_anio=2010, base_anio_texto="2005- 2010", metas={"2030": 1.0})
        s = sondear(i, self.SERIE)
        assert s.anio_base == "2010" and "año exacto" in (s.lectura or "")
