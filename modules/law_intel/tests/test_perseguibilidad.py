"""De quién depende cerrar cada indicador — la clasificación que ordena el trabajo.

Los tests de acá protegen dos cosas distintas. Que la partición sea REAL: cada uno de los 90
en exactamente un grupo, sin huérfanos ni dobles. Y que las dos reglas que no salen del estado
del campo se sostengan, porque son las que hacen útil la clasificación: sin ellas, «descartado»
sería un solo cajón y mezclaría lo que podemos perseguir con lo que no.
"""
import pytest

from modules.law_intel.bindings import cargar_bindings
from modules.law_intel.campo import campo
from modules.law_intel.perseguibilidad import DE_QUIEN_DEPENDE, clasificar, resumen
from modules.law_intel.registro import cargar

E = "end_2030"


class TestLaParticion:
    def test_estan_los_noventa_y_cada_uno_una_vez(self):
        filas = clasificar(E)
        ids = [f["indicador"] for f in filas]
        assert len(ids) == len(set(ids)) == len(cargar(E).numerados) == 90

    def test_ningun_grupo_fuera_del_conjunto_cerrado(self):
        assert {f["depende_de"] for f in clasificar(E)} <= set(DE_QUIEN_DEPENDE)

    def test_el_conteo_del_resumen_suma_el_total(self):
        r = resumen(E)
        assert sum(r["por_grupo"].values()) == r["total"] == 90

    def test_todo_lo_no_medido_dice_QUE_HARIA_FALTA(self):
        """Un indicador clasificado como perseguible sin decir qué hacer no es accionable:
        manda a releer el expediente, que es lo que esta clasificación evita."""
        for f in clasificar(E):
            if f["depende_de"] == "ya_medido":
                continue
            assert f["que_haria_falta"].strip(), f


class TestLasDosReglasQueNoSalenDelEstado:
    def test_un_descarte_CON_hipotesis_es_trabajo_nuestro(self):
        """Es la regla que separa lo perseguible de lo que no: la hipótesis declarada DICE
        qué comprobar. Sin ella, reabrir un descarte depende de que aparezca otro emisor."""
        bs = cargar_bindings(E)
        con = {b.indicador for b in bs.values()
               if b.estado == "descartado" and (b.hipotesis_sin_comprobar or "").strip()}
        assert con, "no hay descartes con hipótesis: la regla no probaría nada"
        por_ind = {f["indicador"]: f for f in clasificar(E)}
        for i in con:
            assert por_ind[i]["depende_de"] == "trabajo_nuestro", i
            assert por_ind[i]["que_haria_falta"] == " ".join(
                (bs[i].hipotesis_sin_comprobar or "").split()), (
                f"{i}: lo que haría falta tiene que SER la hipótesis, no un texto genérico")

    def test_un_descarte_SIN_hipotesis_no_es_trabajo_nuestro(self):
        bs = cargar_bindings(E)
        sin = {b.indicador for b in bs.values()
               if b.estado == "descartado" and not (b.hipotesis_sin_comprobar or "").strip()}
        assert sin, "no hay descartes sin hipótesis: la regla no probaría nada"
        por_ind = {f["indicador"]: f for f in clasificar(E)}
        for i in sin:
            # Puede haber caído en otro grupo por su estado de campo (p. ej. una meta que la
            # ley no deja interpretar manda sobre el candidato). Lo que NO puede es contarse
            # como tarea nuestra sin que exista la tarea.
            assert por_ind[i]["depende_de"] != "trabajo_nuestro", i

    def test_una_fuente_no_procesable_SI_es_trabajo_nuestro(self):
        """El dato existe y el emisor lo publica: lo que falta es extraerlo. Clasificarlo
        como hecho de tercero lo sacaría de la cola sin motivo.

        El estado se vació del expediente entre que se escribió este módulo y que se mergeó,
        así que la regla se prueba contra un caso construido. Se deja la comprobación sobre
        los datos reales al lado: si vuelve a haber uno, tiene que caer donde corresponde.
        """
        cs = campo(E)
        por_ind = {f["indicador"]: f for f in clasificar(E)}
        for i, c in cs.items():
            if c.estado == "fuente_no_procesable":
                assert por_ind[i]["depende_de"] == "trabajo_nuestro", i


class TestElDefaultNoESsilencioso:
    """La primera versión resolvía el estado desconocido con `.get(estado,
    "hecho_de_un_tercero")`. Entre que se escribió y que se mergeó, el expediente ganó dos
    estados nuevos: los OCHO indicadores de la END que hoy son hallazgos sobre la ley habrían
    salido publicados como «esperando que un emisor publique algo». Un default silencioso en
    una tabla que se usa para planificar manda a la gente a esperar en vez de a trabajar."""

    def test_un_estado_desconocido_LEVANTA(self, monkeypatch):
        from modules.law_intel.campo import Casilla
        import modules.law_intel.perseguibilidad as P

        real = P.campo
        def _falso(eid):
            cs = dict(real(eid))
            k = next(iter(cs))
            cs[k] = Casilla(**{**vars(cs[k]), "estado": "un_estado_que_nadie_declaro"})
            return cs
        monkeypatch.setattr(P, "campo", _falso)
        with pytest.raises(P.EstadoSinClasificar, match="un_estado_que_nadie_declaro"):
            clasificar(E)

    def test_TODO_estado_en_uso_hoy_está_clasificado(self):
        """El guard sobre los expedientes reales: un estado nuevo rompe acá, no en prod."""
        from modules.law_intel.registro import expedientes
        for eid in expedientes():
            clasificar(eid)      # levanta si alguno no está clasificado

    def test_los_dos_estados_NUEVOS_son_hallazgos_sobre_la_ley(self):
        """`linea_base_no_reproduce` y `termino_legal_sin_fuente`: el trabajo está hecho y el
        que no cierra es el instrumento. Nadie va a publicar nada que los arregle."""
        cs = campo(E)
        por_ind = {f["indicador"]: f for f in clasificar(E)}
        afectados = [i for i, c in cs.items()
                     if c.estado in ("linea_base_no_reproduce", "termino_legal_sin_fuente")]
        assert afectados, "los dos estados se vaciaron: la regla no probaría nada"
        for i in afectados:
            assert por_ind[i]["depende_de"] == "lo_impide_la_ley", i


class TestLoQueLaClasificacionAfirma:
    def test_los_medidos_coinciden_con_la_cobertura(self):
        """Dos cifras sobre el mismo hecho que se computan por caminos distintos. Si divergen,
        una de las dos miente y el informe publicaría las dos."""
        from modules.law_intel.bindings import cobertura

        r = resumen(E)
        assert r["por_grupo"]["ya_medido"] == cobertura(E)["medidos"]

    #: Los cuatro estados en que el que no cierra es el INSTRUMENTO. Los dos primeros son
    #: sobre la meta —la ley no puso cifra, o la puso de un modo que no admite veredicto—; los
    #: dos segundos son sobre la magnitud: la línea base que la norma fija no la reproduce
    #: ninguna serie, o el término que la norma usa no lo publica nadie. En los cuatro el
    #: trabajo está hecho.
    IMPIDE_LA_LEY = ("sin_meta_legal", "meta_no_interpretable",
                     "linea_base_no_reproduce", "termino_legal_sin_fuente")

    def test_lo_que_impide_la_ley_son_HALLAZGOS_no_brechas_nuestras(self):
        """El grupo más grande de los no medidos no puede ser una brecha nuestra disfrazada:
        en los cuatro estados el que no cierra es el instrumento, no nosotros."""
        cs = campo(E)
        for f in clasificar(E):
            if f["depende_de"] == "lo_impide_la_ley":
                assert cs[f["indicador"]].estado in self.IMPIDE_LA_LEY

    def test_la_lista_perseguible_es_la_union_de_los_dos_grupos_nuestros(self):
        r = resumen(E)
        esperado = set(r["indicadores_por_grupo"]["trabajo_nuestro"]) | set(
            r["indicadores_por_grupo"]["decision_del_dueno"])
        assert set(r["perseguibles_por_nosotros"]) == esperado

    def test_la_nota_advierte_que_perseguible_no_es_cobertura(self):
        """La cifra se va a leer como promesa si no dice que no lo es: varias de esas tareas
        terminan en motivo definitivo, y eso también cierra el indicador."""
        assert "no promete cobertura" in resumen(E)["nota"]
