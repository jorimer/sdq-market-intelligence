"""Las consultas salen del nombre que el legislador le puso al indicador.

Un término por eje —lo que hace `source_intel` para los demás— desperdiciaría lo mejor que
tiene una ley: 84 nombres escritos para describir exactamente lo que se quiso medir.
"""
import pytest

from modules.law_intel.descubrimiento import (barrido, consultas, resumen, terminos_de)
from modules.law_intel.registro import Indicador


def ind(nombre, **kw):
    base = dict(id="1.1", eje=1, nombre=nombre, escala="numerica")
    return Indicador(**{**base, **kw})


class TestTerminos:
    def test_quita_las_palabras_que_no_discriminan(self):
        """«Porcentaje de población» aparece en media ley: no identifica ningún fenómeno."""
        t = terminos_de(ind("Porcentaje de población bajo la línea de pobreza extrema nacional"))
        assert "porcentaje" not in t and "población" not in t and "nacional" not in t
        assert "pobreza" in t and "extrema" in t

    def test_un_termino_distintivo_alcanza(self):
        """«homicidios» encontró un dataset real en la sonda contra el catálogo."""
        c = consultas.__wrapped__ if hasattr(consultas, "__wrapped__") else None
        from modules.law_intel.descubrimiento import Consulta
        assert Consulta("1.8", "Tasa de homicidios", 1, terminos_de(ind("Tasa de homicidios"))).util

    def test_gini_sobrevive_al_filtro_de_largo(self):
        """Un umbral de cinco letras se comía justo el término más discriminante."""
        assert terminos_de(ind("Índice de GINI")) == "gini"

    def test_no_repite_palabras(self):
        t = terminos_de(ind("Exportaciones dominicanas en exportaciones mundiales"))
        assert t.split().count("exportaciones") == 1

    def test_una_consulta_vacia_no_es_util(self):
        from modules.law_intel.descubrimiento import Consulta
        assert not Consulta("x", "Tasa", 1, "").util


class TestQueSeConsulta:
    def test_no_se_descubre_lo_que_ya_se_mide(self):
        """Se computa de los bindings en vez de listar ids: la lista escrita a mano decía
        «2.4, 2.18, 2.19, 2.21» y quedó falsa en cuanto tres de esos se demotaron por medir
        una región en vez del país. Un test que enumera la foto se rompe al corregirla."""
        from modules.law_intel.bindings import cargar_bindings
        medidos = {k for k, b in cargar_bindings("end_2030").items() if b.cuenta}
        assert medidos, "sin bindings verificados el test no probaría nada"
        ids = {c.indicador for c in consultas("end_2030")}
        assert not (medidos & ids), "ya tienen binding verificado"

    def test_no_se_reabre_un_indicador_descartado(self):
        """Su problema no es falta de fuente: es que la evaluada no mide lo que el eje
        afirma. Volver a proponerle algo sería re-abrir una decisión documentada.

        El 3.9 lo sigue siendo: su emisor (WEF) dejó de publicar en 2020 y no hay serie que
        proponer. El 3.26 salió de esta lista y NO por relajar el criterio — ver abajo."""
        ids = {c.indicador for c in consultas("end_2030")}
        assert "3.9" not in ids

    def test_rechazar_una_SERIE_no_agota_al_indicador(self):
        """La distinción que costó entender: un descarte es sobre un CANDIDATO.

        El 3.26 tenía rechazado el ingreso familiar mensual, y la serie que la ley nombra
        —INB per cápita por método Atlas— existía todo el tiempo en otro emisor. Tratar al
        indicador como agotado nos habría mantenido ciegos indefinidamente: hoy está
        VERIFICADO, midiendo 10.620 US$ en 2025.

        El test comprueba la propiedad y no el caso, porque el caso ya avanzó: la constancia
        del candidato rechazado sobrevive a la promoción, y toda consulta lleva los suyos."""
        from modules.law_intel.bindings import cargar_bindings
        bs = cargar_bindings("end_2030")
        assert any(b.candidatos_descartados for b in bs.values()), (
            "el registro acumulativo de candidatos rechazados no puede quedar vacío")
        assert "social_dev:income_per_capita" in {
            c["serie"] for c in bs["3.26"].candidatos_descartados}, (
            "promover el indicador no puede borrar el rechazo de la serie que no servía")
        for c in consultas("end_2030"):
            b = bs.get(c.indicador)
            esperado = tuple(x["serie"] for x in (b.candidatos_descartados if b else ()))
            assert c.excluir == esperado, f"{c.indicador} no arrastra sus rechazos"

    def test_todas_las_consultas_del_expediente_son_utiles(self):
        r = resumen(consultas("end_2030"))
        assert r["sin_terminos_suficientes"] == []
        assert r["consultas_utiles"] == r["indicadores_sin_medicion"]


class TestBarrido:
    def test_no_hace_red(self):
        """El buscador se inyecta: el módulo no depende de un catálogo concreto."""
        llamadas = []

        def buscar(q):
            llamadas.append(q)
            return [{"title": f"ds de {q}"}]

        res = barrido("end_2030", buscar, max_por_indicador=1, limite=3)
        assert len(res) == 3 and len(llamadas) == 3
        assert all(r["indicador"] and r["consulta"] for r in res)

    def test_respeta_el_tope_por_indicador(self):
        res = barrido("end_2030", lambda q: [{"t": 1}, {"t": 2}, {"t": 3}],
                      max_por_indicador=2, limite=4)
        assert len(res) == 4
        assert len({r["indicador"] for r in res}) == 2, "dos por indicador"

    def test_un_buscador_sin_resultados_no_rompe(self):
        assert barrido("end_2030", lambda q: [], limite=5) == []
