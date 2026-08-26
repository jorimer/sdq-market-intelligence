"""El fin de la ley agregado desde los veredictos.

Los casos de acá salen de la forma REAL del expediente END: un fin grande y bien cubierto
(Desarrollo social, 48 indicadores), uno mediano (Económico, 30), y dos que la ley dejó
chicos (Institucionalidad 8, Ambiental 4) donde la cobertura no alcanza para caracterizar.
Esa asimetría es el caso de prueba, no un detalle: es lo que hace que un promedio entre
fines sea mentira.
"""
import pytest

from modules.law_intel.registro import Indicador
from modules.law_intel.scoring.fines import (ALCANZAN, ESTADOS, FRACCION_MINIMA_DE_LA_LEY,
                                             MINIMO_EVALUADOS, NO_ALCANZAN, SIN_VEREDICTO,
                                             clase_de, por_fin, publicable)
from modules.law_intel.scoring.semaforo import VEREDICTOS, Veredicto


def _ind(id_: str, eje: int) -> Indicador:
    return Indicador(id=id_, eje=eje, nombre=f"Indicador {id_}", escala="porcentaje")


def _caso(eje: int, veredictos: list) -> tuple:
    """`n` indicadores del mismo eje, con el veredicto que se le pase a cada uno."""
    inds = [_ind(f"{eje}.{k + 1}", eje) for k in range(len(veredictos))]
    vs = [Veredicto(i.id, v) for i, v in zip(inds, veredictos)]
    return inds, vs


class TestQueNingunVeredictoSeCAIGA:
    def test_TODO_veredicto_del_semaforo_tiene_clase_declarada(self):
        """El guard que importa. `medido_sin_certificar` se agregó al semáforo después de que
        el resto del módulo existía; sin este test, la próxima categoría nueva se contaría
        como «sin veredicto» y un incumplimiento desaparecería del fin sin ruido."""
        sin_clasificar = [v for v in VEREDICTOS
                          if v not in ALCANZAN + NO_ALCANZAN + SIN_VEREDICTO]
        assert not sin_clasificar, (
            f"veredictos del semáforo que fines.py no clasifica: {sin_clasificar}")

    def test_un_veredicto_DESCONOCIDO_levanta_en_vez_de_caer_del_lado_mudo(self):
        with pytest.raises(ValueError, match="sin clase declarada"):
            clase_de("avance_moderado")   # el eufemismo del informe oficial

    def test_las_tres_clases_son_disjuntas(self):
        todas = ALCANZAN + NO_ALCANZAN + SIN_VEREDICTO
        assert len(todas) == len(set(todas))


class TestElFinSeCARACTERIZAoNO:
    def test_un_fin_bien_cubierto_recibe_estado(self):
        inds, vs = _caso(2, ["alcanzada"] * 7 + ["no_alcanzara"] * 14 + ["sin_medicion"] * 6)
        f = por_fin(inds, vs, {2: "Desarrollo social"})[0]
        assert f.estado == "no_alcanza_en_su_mayoria"
        assert (f.evaluados_en_este_informe, f.alcanzadas, f.no_alcanzadas) == (21, 7, 14)
        assert f.indicadores_que_la_ley_le_fija == 27

    def test_dos_evaluados_NO_caracterizan_aunque_sean_la_mitad_del_fin(self):
        """El Eje 4 de la END: 4 indicadores, 2 juzgados. La fracción pasa y el N no, y con
        N=2 una sola observación decide la «mayoría»."""
        inds, vs = _caso(4, ["alcanzada", "retrocede", "sin_medicion", "sin_medicion"])
        f = por_fin(inds, vs)[0]
        assert f.estado == "no_caracterizable"
        assert "hacen falta 3" in (f.motivo_sin_caracterizar or "")
        assert f.retroceden == 1        # el conteo SIGUE, lo que no sale es el veredicto

    def test_una_muestra_por_debajo_de_un_tercio_NO_caracteriza_aunque_sobre_el_N(self):
        inds, vs = _caso(1, ["no_alcanzara"] * 3 + ["sin_medicion"] * 15)
        f = por_fin(inds, vs)[0]
        assert f.estado == "no_caracterizable"
        assert "menos de un tercio" in (f.motivo_sin_caracterizar or "")

    def test_el_fin_no_caracterizable_NO_desaparece_de_la_salida(self):
        """Un veto silencioso se lee como que el fin no tiene problemas."""
        inds = [_ind("1.1", 1), _ind("1.2", 1)] + [_ind(f"2.{k}", 2) for k in range(1, 10)]
        vs = ([Veredicto("1.1", "no_alcanzada"), Veredicto("1.2", "sin_medicion")]
              + [Veredicto(f"2.{k}", "alcanzada") for k in range(1, 10)])
        fines = por_fin(inds, vs)
        assert [f.eje for f in fines] == [1, 2]
        publicado = publicable(fines)
        assert len(publicado["fines_de_la_ley_computados"]) == 2
        assert publicado["caracterizables"] == 1

    def test_los_umbrales_son_CONSTANTES_y_no_numeros_sueltos(self):
        """Si algún día hay que moverlos, se mueven a la vista. Escritos dentro de un `if`
        se mueven dentro de una frase de informe y nadie se entera."""
        assert MINIMO_EVALUADOS == 3
        assert FRACCION_MINIMA_DE_LA_LEY == pytest.approx(1 / 3)


class TestLaMayoriaSeCOMPUTA:
    @pytest.mark.parametrize("alc,no_alc,esperado", [
        (7, 3, "alcanza_en_su_mayoria"),
        (3, 7, "no_alcanza_en_su_mayoria"),
        (5, 5, "dividido"),
    ])
    def test_el_estado_sale_de_comparar_conteos(self, alc, no_alc, esperado):
        inds, vs = _caso(3, ["alcanzada"] * alc + ["no_alcanzada"] * no_alc)
        assert por_fin(inds, vs)[0].estado == esperado

    def test_el_estado_declarado_existe_en_el_vocabulario(self):
        inds, vs = _caso(3, ["alcanzada"] * 4 + ["retrocede"] * 4)
        assert por_fin(inds, vs)[0].estado in ESTADOS

    def test_el_porcentaje_se_computa_sobre_EVALUADOS_no_sobre_la_ley(self):
        inds, vs = _caso(2, ["alcanzada"] * 5 + ["no_alcanzada"] * 5 + ["sin_medicion"] * 20)
        f = por_fin(inds, vs)[0]
        assert f.pct_alcanzadas_sobre_evaluados == 50.0     # 5 de 10, no 5 de 30


class TestLaFRASEquesEModeloCOPIA:
    def test_estancada_NO_se_redacta_como_que_se_aleja(self):
        """La doctrina del contexto prohíbe llamar «se aleja» a una serie plana. Fundir los
        dos contadores en uno la habría metido de vuelta por la puerta de atrás."""
        inds, vs = _caso(2, ["alcanzada"] * 3 + ["estancada"] * 4 + ["no_alcanzada"] * 2)
        f = por_fin(inds, vs)[0]
        assert f.estancadas == 4 and f.retroceden == 0
        frase = f.frase()
        assert "se alejan" not in frase
        assert "no se mueven mientras la meta avanza" in frase

    def test_la_frase_CONCUERDA_en_numero(self):
        """«1 no se mueven» le dice al lector que nadie leyó el informe antes de venderlo."""
        inds, vs = _caso(2, ["alcanzada"] + ["retrocede"] + ["estancada"] + ["no_alcanzada"] * 3)
        frase = por_fin(inds, vs)[0].frase()
        assert "1 alcanza su meta" in frase
        assert "1 se aleja de su meta" in frase and "1 se alejan" not in frase
        assert "1 no se mueve mientras" in frase and "1 no se mueven" not in frase

    def test_la_frase_del_fin_no_caracterizable_habla_de_EVIDENCIA_no_de_desempeno(self):
        inds, vs = _caso(4, ["alcanzada", "sin_medicion", "sin_medicion", "sin_medicion"])
        frase = por_fin(inds, vs)[0].frase()
        assert "No alcanzan para caracterizar el fin" in frase
        for palabra in ("cumple", "incumple", "alcanza su meta"):
            assert palabra not in frase

    def test_la_frase_lleva_los_DOS_denominadores(self):
        inds, vs = _caso(3, ["alcanzada"] * 4 + ["no_alcanzada"] * 4 + ["sin_medicion"] * 4)
        frase = por_fin(inds, vs)[0].frase()
        assert "de los 12 compromisos que la ley le fija" in frase
        assert "juzga 8" in frase

    def test_el_fin_toma_el_nombre_QUE_LA_LEY_LE_DA(self):
        inds, vs = _caso(2, ["alcanzada"] * 4 + ["no_alcanzada"] * 4)
        assert por_fin(inds, vs, {2: "Desarrollo social"})[0].frase().startswith(
            "Desarrollo social:")
        # Sin nombre declarado no se inventa un título: se rotula por lo que es.
        assert por_fin(inds, vs)[0].nombre == "Eje 2"


def test_la_regla_prohibe_ORDENAR_los_fines_entre_si():
    """Denominadores distintos y coberturas distintas: rankearlos es el error que este repo
    ya pagó en el catálogo de scores."""
    inds, vs = _caso(2, ["alcanzada"] * 4 + ["no_alcanzada"] * 4)
    pub = publicable(por_fin(inds, vs))
    assert "No ordenes los fines entre sí" in pub["regla_de_la_comparacion_entre_fines"]


class TestLaTABLAquesEsLaEvidencia:
    """A «Lo que se logró» se le pedía nombrar indicadores con su meta, y se le daba «11
    alcanzan, 33 no». El modelo reconstruía las cifras de memoria y las erraba: publicó
    «2.7 alcanza 0.39 contra una meta de 0.42» cuando la ley fija 0.44, y «3.13 91.0% frente
    a una meta de 70.0%» cuando fija 60.0.

    Y el guard de cifra sin respaldo no las atrapa: con noventa indicadores casi cualquier
    número aparece en algún lado del contexto. El guard comprueba PRESENCIA, no ATRIBUCIÓN.
    """

    def _panel(self):
        from modules.law_intel.registro import Indicador
        from modules.law_intel.scoring.semaforo import Veredicto, tabla
        inds = [Indicador(id="2.7", eje=2, nombre="Índice de GINI", escala="numerica"),
                Indicador(id="3.13", eje=3, nombre="Usuarios de internet", escala="numerica"),
                Indicador(id="1.4", eje=1, nombre="Sin fuente", escala="numerica")]
        vs = [Veredicto("2.7", "alcanzada", meta_periodo="2025", meta=0.44, observado=0.39),
              Veredicto("3.13", "alcanzada", meta_periodo="2025", meta=60.0, observado=91.0),
              Veredicto("1.4", "sin_medicion")]
        return inds, vs, tabla(vs, inds, {2: "Desarrollo social", 3: "Desarrollo económico"})

    def test_cada_fila_lleva_la_meta_QUE_FIJA_LA_LEY(self):
        _, _, filas = self._panel()
        por_id = {f["indicador"]: f for f in filas}
        assert por_id["2.7"]["meta_que_fija_la_ley"] == 0.44
        assert por_id["3.13"]["meta_que_fija_la_ley"] == 60.0

    def test_solo_entran_los_que_PRODUCEN_veredicto(self):
        """Una fila sin meta que citar es un hueco que el redactor va a completar."""
        _, _, filas = self._panel()
        assert [f["indicador"] for f in filas] == ["2.7", "3.13"]

    def test_cada_fila_lleva_el_NOMBRE_y_el_FIN(self):
        _, _, filas = self._panel()
        assert filas[0]["nombre_del_indicador"] == "Índice de GINI"
        assert filas[0]["fin"] == "Desarrollo social"
        assert filas[1]["fin"] == "Desarrollo económico"

    def test_el_reparto_por_fin_se_CUENTA_sobre_la_tabla(self):
        """El informe dijo «nueve del Eje social, uno del Económico» cuando eran siete y
        tres. Con la tabla, el reparto se cuenta en vez de estimarse."""
        import collections
        _, _, filas = self._panel()
        alcanzadas = [f for f in filas if f["veredicto"] == "alcanzada"]
        reparto = collections.Counter(f["fin"] for f in alcanzadas)
        assert reparto == {"Desarrollo social": 1, "Desarrollo económico": 1}

    def test_un_fin_sin_nombre_declarado_se_rotula_por_lo_que_ES(self):
        from modules.law_intel.registro import Indicador
        from modules.law_intel.scoring.semaforo import Veredicto, tabla
        inds = [Indicador(id="9.1", eje=9, nombre="Otro", escala="numerica")]
        filas = tabla([Veredicto("9.1", "alcanzada", meta=1.0, observado=2.0)], inds, {})
        assert filas[0]["fin"] == "Eje 9"
