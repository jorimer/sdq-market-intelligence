"""Mezcla de ramos y tipo de compañía derivado."""
from modules.insurance_intel.scoring.mezcla_ramos import (
    agrupar_por_entidad, clasificar, mezcla_de_una,
)


def _f(dim, val, period="2024"):
    return {"entity_slug": "x", "dimension": dim, "value": val, "period": period}


class TestMezcla:

    def test_el_tipo_sale_del_negocio_real_no_de_una_etiqueta(self):
        m = mezcla_de_una([_f("salud", 800.0), _f("vehiculos_motor", 200.0)])
        assert m["peso_personas"] == 0.8 and m["peso_salud"] == 0.8
        assert m["tipo"] == "salud"

    def test_personas_se_separa_en_SALUD_y_VIDA(self):
        """«Personas» agrupaba negocios distintos: Seguros Ademi tiene 76% en personas y 0%
        en salud —vida y accidentes— y salía junto a Bupa, que es 100% salud. Una ARS y una
        compañía de vida no comparten estructura de siniestralidad ni marco regulatorio."""
        salud = mezcla_de_una([_f("salud", 900.0), _f("vehiculos_motor", 100.0)])
        vida = mezcla_de_una([_f("vida_individual", 500.0), _f("vida_colectivo", 300.0),
                              _f("accidentes_personales", 100.0), _f("vehiculos_motor", 100.0)])
        assert salud["tipo"] == "salud"
        assert vida["tipo"] == "vida" and vida["peso_personas"] >= 0.6
        assert vida["peso_salud"] == 0.0

    def test_sin_peso_de_salud_se_degrada_a_personas_y_no_adivina(self):
        from modules.insurance_intel.scoring.mezcla_ramos import clasificar
        assert clasificar(0.8) == "personas"
        assert clasificar(0.8, 0.9) == "salud"
        assert clasificar(0.8, 0.0) == "vida"

    def test_una_aseguradora_de_danos_se_clasifica_como_tal(self):
        m = mezcla_de_una([_f("vehiculos_motor", 700.0), _f("incendio_catastrofico", 200.0),
                           _f("vida_individual", 100.0)])
        assert m["peso_danos"] == 0.9 and m["tipo"] == "danos"

    def test_la_franja_intermedia_es_mixta(self):
        m = mezcla_de_una([_f("salud", 400.0), _f("vehiculos_motor", 600.0)])
        assert m["tipo"] == "mixta"

    def test_sin_desglose_NO_se_asume_danos(self):
        """Clasificar por ausencia de dato es el error que la doctrina prohíbe."""
        assert mezcla_de_una([]) is None
        assert mezcla_de_una([_f("salud", None)]) is None
        assert mezcla_de_una([_f(None, 500.0)]) is None
        assert clasificar(None) is None

    def test_un_ramo_desconocido_se_reporta_no_se_reparte(self):
        """Taxonomía nueva no se asigna en silencio a la familia que más convenga."""
        m = mezcla_de_una([_f("vehiculos_motor", 500.0), _f("ramo_que_no_existe", 500.0)])
        assert m["peso_sin_clasificar"] == 0.5
        assert m["peso_danos"] == 0.5 and m["peso_personas"] == 0.0

    def test_las_primas_negativas_no_forman_parte_de_la_mezcla(self):
        """Ajustes de cierre negativos distorsionarían el denominador."""
        m = mezcla_de_una([_f("vehiculos_motor", 1000.0), _f("transporte", -300.0)])
        assert m["primas_totales"] == 1000.0 and m["peso_danos"] == 1.0

    def test_suma_los_ejercicios_de_un_mismo_ramo(self):
        m = mezcla_de_una([_f("salud", 100.0, "2023"), _f("salud", 300.0, "2024")])
        assert m["primas_totales"] == 400.0

    def test_la_taxonomia_se_hereda_del_extractor(self):
        """No se re-escribe acá: un ramo nuevo del catálogo entra solo."""
        from modules.insurance_intel.external.audited_excel_extractor import (
            RAMOS_GENERALES, RAMOS_PERSONAS,
        )
        from modules.insurance_intel.scoring.mezcla_ramos import (
            RAMOS_DE_DANOS, RAMOS_DE_PERSONAS,
        )
        assert RAMOS_DE_PERSONAS == frozenset(RAMOS_PERSONAS)
        assert RAMOS_DE_DANOS == frozenset(RAMOS_GENERALES.values())

    def test_agrupa_por_entidad_y_no_pierde_filas(self):
        filas = [{"entity_slug": "a", "dimension": "salud", "value": 1.0},
                 {"entity_slug": "b", "dimension": "salud", "value": 2.0},
                 {"entity_slug": "a", "dimension": "transporte", "value": 3.0},
                 {"entity_slug": None, "dimension": "salud", "value": 9.0}]
        g = agrupar_por_entidad(filas)
        assert sorted(g) == ["a", "b"] and len(g["a"]) == 2
