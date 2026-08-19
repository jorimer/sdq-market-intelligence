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
