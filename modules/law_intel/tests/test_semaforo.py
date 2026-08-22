"""El semáforo no puede lavar un incumplimiento ni inventar una tendencia.

Los dos defectos que estos tests fijan salieron del expediente real de la END: el informe
oficial llama «avance moderado» a lo que su propia definición describe como *no se alcanzará
la meta*, y ninguna de sus categorías distingue «no cumple» de «no lo medimos».
"""
import pytest

from modules.law_intel.bindings import Binding, direccion_de_metas
from modules.law_intel.registro import Indicador
from modules.law_intel.scoring.semaforo import evaluar, resumen

VERIF = dict(serie="s", fuente="one", estado="verificado")


def ind(**kw):
    base = dict(id="1.8", eje=1, nombre="Tasa de homicidios", escala="numerica",
                base_valor=24.8, metas={"2015": 20.0, "2020": 15.0, "2025": 10.0, "2030": 4.0})
    return Indicador(**{**base, **kw})


class TestNoLavarElIncumplimiento:
    def test_avanzar_sin_llegar_se_llama_no_alcanzara(self):
        """El eufemismo que el producto existe para no repetir: avanzar no es cumplir."""
        v = evaluar(ind(), Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2020", 14.0), ("2025", 12.0)], corte="2025")
        assert v.veredicto == "no_alcanzara"
        assert v.cumple is False
        assert "faltan" in (v.motivo or "")

    def test_alejarse_de_la_meta_es_retroceso(self):
        v = evaluar(ind(), Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2020", 12.0), ("2025", 14.0)], corte="2025")
        assert v.veredicto == "retrocede"
        assert v.cumple is False

    def test_cumplir_es_cumplir(self):
        v = evaluar(ind(), Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2020", 12.0), ("2025", 9.0)], corte="2025")
        assert v.veredicto == "alcanzada" and v.cumple is True


class TestNoInventarTendencia:
    def test_una_observacion_no_produce_trayectoria(self):
        v = evaluar(ind(), Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2025", 12.0)], corte="2025")
        assert v.veredicto == "no_alcanzada"
        assert v.trayectoria is None, "una sola observación no define una pendiente"
        assert "no la trayectoria" in (v.motivo or "")

    def test_sin_observacion_no_hay_veredicto_de_cumplimiento(self):
        v = evaluar(ind(), Binding(indicador="1.8", mejor="menor", **VERIF), [], corte="2025")
        assert v.veredicto == "sin_dato" and v.cumple is None


class TestDireccion:
    def test_mayor_es_mejor_se_juzga_al_reves(self):
        """Presión tributaria: quedarse corto es incumplir, aunque el número sea menor."""
        i = ind(id="3.25", nombre="Presión tributaria", base_valor=13.0,
                metas={"2015": 16.0, "2020": 19.0, "2025": 21.5, "2030": 24.0})
        v = evaluar(i, Binding(indicador="3.25", mejor="mayor", **VERIF),
                    [("2020", 14.0), ("2025", 14.4)], corte="2025")
        assert v.veredicto == "no_alcanzara"
        assert v.distancia == pytest.approx(7.1), "la distancia se firma hacia «cuánto falta»"

    def test_la_direccion_se_computa_de_las_metas(self):
        assert direccion_de_metas(ind()) == "menor"
        assert direccion_de_metas(ind(base_valor=13.0,
                                     metas={"2015": 16.0, "2030": 24.0})) == "mayor"

    def test_meta_plana_no_es_direccion(self):
        """Áreas protegidas: la ley pide SOSTENER 24,4 en los cuatro cortes."""
        i = ind(base_valor=24.4, metas={a: 24.4 for a in ("2015", "2020", "2025", "2030")})
        assert direccion_de_metas(i) == "plana"

    def test_trayectoria_no_monotona_es_ambigua(self):
        assert direccion_de_metas(ind(metas={"2015": 5.0, "2020": 3.0, "2025": 9.0})) == "ambigua"


class TestLoQueNoSeEvalua:
    def test_umbral_no_se_RESTA_pero_ahora_si_se_JUZGA(self):
        """La mitad de este test seguía siendo cierta y la otra mitad era una limitación que
        se leía como decisión.

        «No se resta» es correcto: la ley fijó un techo, no un objetivo puntual, así que
        publicar una distancia sugeriría que falta poco para una meta que no existe. Pero de
        ahí no se sigue que no se pueda juzgar — 5,0 no es menor que 4, y el informe callaba
        ese incumplimiento pudiendo afirmarlo."""
        i = ind(escala="umbral", metas={"2025": "< 4"})
        v = evaluar(i, Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2025", 5.0)], corte="2025")
        assert v.veredicto == "no_alcanzada" and v.cumple is False
        assert v.distancia is None, "un umbral sigue sin admitir distancia"

    def test_binding_propuesto_no_mide(self):
        """Un binding sin verificar es una hipótesis. Contarlo como medición afirma haber
        medido algo que nadie comprobó."""
        b = Binding(indicador="1.8", serie="s", fuente="one", mejor="menor", estado="propuesto")
        v = evaluar(ind(), b, [("2025", 9.0)], corte="2025")
        assert v.veredicto == "sin_medicion"
        assert "propuesto" in (v.motivo or "")

    def test_meta_que_todavia_no_vence(self):
        v = evaluar(ind(), Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2013", 22.0)], corte="2013")
        assert v.veredicto == "no_evaluable"


def test_la_meta_juzgada_es_la_ya_vencida():
    """Juzgar contra la meta de 2030 en 2025 diría que casi todo está incumplido."""
    v = evaluar(ind(), Binding(indicador="1.8", mejor="menor", **VERIF),
                [("2025", 9.5)], corte="2025")
    assert v.meta_periodo == "2025" and v.meta == 10.0


def test_el_resumen_separa_no_cumple_de_no_medido():
    vs = [evaluar(ind(), Binding(indicador="1.8", mejor="menor", **VERIF),
                  [("2020", 12.0), ("2025", 9.0)], "2025"),
          evaluar(ind(id="1.9"), None, [], "2025"),
          evaluar(ind(id="1.10", escala="redactada", metas={"2025": "x"}), None, [], "2025")]
    r = resumen(vs)
    assert r["total"] == 3 and r["evaluados"] == 1
    assert r["pct_sobre_evaluados"] == 100.0, "no se diluye con lo que no se midió"


def test_el_valor_observado_no_arrastra_precision_espuria():
    """El 2.44 se publicó como `37.3684210526316`: trece decimales que son el residuo de
    dividir 71 escaños entre 190, no una medición. Esa cifra viaja al informe tal cual, y
    junto a metas de un decimal desacredita al resto de la tabla."""
    v = evaluar(ind(metas={"2025": 41.5}), Binding(indicador="1.8", mejor="mayor", **VERIF),
                [("2025", 71 / 190 * 100)], corte="2025")
    assert v.observado == 37.3684


class TestEstancarseNoEsRetroceder:
    """Con una sola observación los dos casos eran indistinguibles. Al servir la serie
    completa el motor empezó a llamar «retrocede» a una serie plana, con el motivo «el
    indicador se mueve en contra de la meta» — una falsedad que el lector puede comprobar
    en la misma tabla, y que le hace perder la fe en el resto."""

    def test_una_serie_plana_no_se_mueve_en_contra(self):
        v = evaluar(ind(metas={"2025": 41.5}), Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2020", 12.5), ("2024", 12.5)], corte="2025")
        assert v.veredicto == "estancada" and v.trayectoria == "plana"
        assert "en contra" not in (v.motivo or "")

    def test_pero_tampoco_es_inocuo(self):
        """La meta avanza con los años: quedarse quieto ensancha la brecha."""
        v = evaluar(ind(metas={"2025": 41.5}), Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2020", 12.5), ("2024", 12.5)], corte="2025")
        assert v.cumple is False

    def test_retroceder_de_verdad_sigue_llamandose_retroceder(self):
        v = evaluar(ind(metas={"2025": 41.5}), Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2020", 30.2), ("2024", 25.8)], corte="2025")
        assert v.veredicto == "retrocede" and v.trayectoria == "se aleja"

    def test_cumplir_estancado_no_se_declara_como_alejarse(self):
        """Quien ya cumple y no se mueve tampoco «se aleja»: sigue cumpliendo, plano."""
        v = evaluar(ind(metas={"2025": 10.0}), Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2020", 8.0), ("2024", 8.0)], corte="2025")
        assert v.veredicto == "alcanzada" and v.trayectoria == "plana"


class TestUnUmbralNoAdmiteDeltaPeroSIVeredicto:
    """La distinción que faltaba. «< 4%» no dice cuánto falta —no hay un objetivo puntual del
    que restar— pero sí dice si se cumple.

    El motor ya conocía la semántica: su propio motivo decía «se cumple o no, no se resta». Y
    aun así devolvía `no_evaluable`, así que el informe callaba un incumplimiento que podía
    afirmar. El 2.19 (analfabetismo) está medido en 5,97% contra un techo legal de 4%.
    """

    def _umbral(self, metas, **kw):
        return ind(escala="umbral", metas=metas, **kw)

    def test_un_umbral_INCUMPLIDO_ahora_se_declara(self):
        v = evaluar(self._umbral({"2025": "< 4"}),
                    Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2024", 5.97)], corte="2025")
        assert v.veredicto == "no_alcanzada"
        assert v.cumple is False
        assert "NO lo cumple" in (v.motivo or "")

    def test_un_umbral_CUMPLIDO_tambien(self):
        v = evaluar(self._umbral({"2025": "< 4"}),
                    Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2024", 3.1)], corte="2025")
        assert v.veredicto == "alcanzada" and v.cumple is True

    def test_la_DISTANCIA_queda_en_None_a_proposito(self):
        """Publicar «faltan 1,97» sugeriría que la meta es 4 y que falta poco. Lo que la ley
        fijó es un TECHO, no un objetivo puntual."""
        v = evaluar(self._umbral({"2025": "< 4"}),
                    Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2024", 5.97)], corte="2025")
        assert v.distancia is None

    def test_el_operador_MAYOR_QUE_se_juzga_al_reves(self):
        v = evaluar(self._umbral({"2025": ">2000"}),
                    Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2024", 2614.0)], corte="2025")
        assert v.veredicto == "alcanzada"

    def test_una_forma_AMBIGUA_no_se_adivina(self):
        """«>1,700» es ambiguo en notación española: ¿1700 o 1,7? Resolverlo por
        plausibilidad —«1,7 no tiene sentido para inversión extranjera»— es la inferencia que
        produce cifras inventadas. Se declara y no se juzga."""
        v = evaluar(self._umbral({"2025": ">1,700"}),
                    Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2024", 1820.0)], corte="2025")
        assert v.veredicto == "no_evaluable"
        assert "no se interpreta" in (v.motivo or "")

    def test_una_meta_en_PROSA_sigue_sin_juzgarse(self):
        v = evaluar(self._umbral({"2025": "Se cumple con tiempos establecidos legalmente"}),
                    Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2024", 1.0)], corte="2025")
        assert v.veredicto == "no_evaluable"

    def test_el_valor_observado_VIAJA_aunque_no_se_pueda_juzgar(self):
        """Que no se pueda emitir veredicto no es razón para ocultar la medición: el lector
        necesita ver el dato aunque el motor no lo compare."""
        v = evaluar(self._umbral({"2025": ">1,700"}),
                    Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2024", 1820.0)], corte="2025")
        assert v.observado == 1820.0


class TestUnEscalarROTULADOSeJuzgaConSuSujeto:
    """«Matemáticas : 63.0» no es prosa: es un número con su sujeto pegado.

    La ley lo escribe así porque el indicador 2.17 nombra TRES materias —lectura, matemáticas
    y ciencias— y solo le fija meta a una. Quitar la etiqueta para dejar un 63.0 pelado
    borraría justamente el dato que deja ver que se juzga una de tres, y violaría la regla que
    este repo hace cumplir en todos lados: el sujeto viaja con el número.
    """

    def _rot(self, metas):
        return ind(escala="redactada", metas=metas)

    def test_se_juzga_y_el_SUJETO_viaja_al_veredicto(self):
        v = evaluar(self._rot({"2025": "Matemáticas : 63.0"}),
                    Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2019", 97.84)], corte="2025")
        assert v.veredicto == "no_alcanzada"
        assert "Matemáticas" in (v.motivo or ""), "sin el sujeto no se ve que es una de tres"
        assert "97.84" in (v.motivo or "") and "63" in (v.motivo or "")

    def test_una_meta_rotulada_CUMPLIDA(self):
        v = evaluar(self._rot({"2025": "Matemáticas : 63.0"}),
                    Binding(indicador="1.8", mejor="menor", **VERIF),
                    [("2019", 52.0)], corte="2025")
        assert v.veredicto == "alcanzada" and v.cumple is True

    def test_una_meta_REDACTADA_de_verdad_sigue_sin_juzgarse(self):
        """«Pertenecer al nivel II» requiere juicio, no aritmética. La rama nueva no puede
        volverse una excusa para juzgar lo que no se mide."""
        v = evaluar(self._rot({"2025": "Pertenecer al nivel III"}),
                    Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2019", 643.95)], corte="2025")
        assert v.veredicto == "no_evaluable"

    def test_una_meta_COMPUESTA_tampoco(self):
        """«Pertenecer al nivel II Con un puntaje promedio > 484» mezcla nivel y puntaje: no se
        puede juzgar media meta y callar la otra."""
        v = evaluar(self._rot({"2025": "Pertenecer al nivel II Con un puntaje promedio > 484"}),
                    Binding(indicador="1.8", mejor="mayor", **VERIF),
                    [("2019", 643.95)], corte="2025")
        assert v.veredicto == "no_evaluable"

    def test_la_direccion_la_pone_el_BINDING_no_el_rotulo(self):
        """El mismo 97,84 cumple o no según si el indicador mejora subiendo o bajando."""
        arriba = evaluar(self._rot({"2025": "Cobertura : 63.0"}),
                         Binding(indicador="1.8", mejor="mayor", **VERIF),
                         [("2019", 97.84)], corte="2025")
        assert arriba.veredicto == "alcanzada"


class TestUnaMetaREDACTADAQueEsUnNumero:
    """La escala describe el CONJUNTO de metas; el veredicto se emite contra UNA.

    El 2.36 tiene tres metas que son el número 100 y una sola escrita en prosa —«100 al
    2016»—. Esa celda bastaba para clasificar el indicador como `redactada` y para que el
    motor devolviera `no_evaluable` sobre las otras tres, perfectamente legibles. La peor
    celda no decide por las demás.
    """

    def _ind(self, metas):
        return ind(id="2.36", escala="redactada", base_valor=42.4, metas=metas)

    def test_se_juzga_contra_la_meta_numerica_que_vence(self):
        i = self._ind({"2015": "100 al 2016", "2020": 100.0, "2025": 100.0})
        v = evaluar(i, Binding(indicador="2.36", mejor="mayor", **VERIF),
                    [("2020", 91.36), ("2025", 92.08)], corte="2025")
        assert v.veredicto == "no_alcanzara"
        assert v.meta == 100.0 and v.observado == 92.08
        assert v.distancia == pytest.approx(7.92, abs=0.01)

    def test_si_la_meta_vigente_NO_es_numérica_sigue_sin_juzgarse(self):
        """El contrapeso: no se afloja la regla, se afina quién decide."""
        i = self._ind({"2025": "Se cumple con tiempos establecidos legalmente"})
        v = evaluar(i, Binding(indicador="2.36", mejor="mayor", **VERIF),
                    [("2025", 92.0)], corte="2025")
        assert v.veredicto == "no_evaluable"

    def test_el_escalar_ROTULADO_sigue_funcionando(self):
        """La vía que ya existía no se rompe: «Matemáticas : 63.0» se juzga como antes."""
        i = self._ind({"2025": "Matemáticas : 63.0"})
        v = evaluar(i, Binding(indicador="2.36", mejor="menor", **VERIF),
                    [("2019", 97.84)], corte="2025")
        assert v.veredicto == "no_alcanzada"
