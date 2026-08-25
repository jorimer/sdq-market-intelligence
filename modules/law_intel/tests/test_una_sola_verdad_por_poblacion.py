"""Que la plataforma no le sirva al modelo dos verdades sobre la misma población.

El informe generado del END se contradijo consigo mismo tres veces, y **ninguna fue culpa del
modelo**: las tres contradicciones estaban en el contexto que le dimos.

1. «veredicto sobre 44 de esos 90» en una sección y «sobre 46 de esos 90» en otra. Son dos
   poblaciones distintas —los medidos y los que producen veredicto— que además dan 44 y 46
   cruzados, así que el mismo número nombra dos cosas.
2. «20 brechas de medición propias de la plataforma» cuando el campo declara 2. `brecha.py`
   atribuía por la ESTRUCTURA del binding y `campo.py` por el MOTIVO declarado, y las dos
   particiones de los mismos 44 indicadores no coincidían.
3. «el acceso a medicamentos antirretrovirales (2.35)» sobre un indicador que mide acceso a
   agua de la red pública, y «cobertura educativa secundaria (2.43)» sobre uno que mide
   mujeres en el Senado. Los bloques publicaban el ID sin el nombre.

Los tres tienen la misma forma: **dos afirmaciones sobre lo mismo, servidas juntas.** Estos
tests las cruzan.
"""
import pytest

from modules.law_intel.ai_context import law_ai_context
from modules.law_intel.bindings import cargar_bindings
from modules.law_intel.campo import RESPONSABLE_POR_MOTIVO, campo
from modules.law_intel.campo import resumen as resumen_del_campo
from modules.law_intel.registro import cargar, expedientes
from modules.law_intel.scoring.brecha import brechas
from modules.law_intel.scoring.brecha import resumen as resumen_brecha

EXPEDIENTES = expedientes()


@pytest.mark.parametrize("eid", EXPEDIENTES)
class TestUnaSolaVerdadPorPoblacion:
    def test_la_atribucion_de_las_brechas_COINCIDE_con_el_campo(self, eid):
        """El defecto que decía «20 son de SDQ» mientras el campo decía «2»."""
        exp = cargar(eid)
        motivos = {k: c.estado for k, c in campo(eid).items()}
        r = resumen_brecha(brechas(exp.numerados, cargar_bindings(eid), motivos),
                           len(exp.numerados))
        esperado = {"sdq": 0, "estado": 0, "instrumento": 0}
        for motivo, n in resumen_del_campo(eid)["por_estado"].items():
            esperado[RESPONSABLE_POR_MOTIVO[motivo]] += n
        assert r["por_responsable"] == {k: v for k, v in sorted(esperado.items()) if v}, (
            "brechas y campo atribuyen los mismos indicadores a responsables distintos")

    def test_TODO_motivo_del_campo_tiene_responsable_declarado(self, eid):
        """Un motivo nuevo sin clasificar caería del lado que convenga."""
        sin_clasificar = [m for m in resumen_del_campo(eid)["por_estado"]
                          if m not in RESPONSABLE_POR_MOTIVO]
        assert not sin_clasificar, f"motivos sin responsable declarado: {sin_clasificar}"

    def test_las_poblaciones_del_contexto_CUADRAN_entre_si(self, eid):
        p = law_ai_context(eid, "2025", {})["poblaciones_de_la_ley"]
        assert (p["medidos_con_serie_verificada"]
                + p["sin_medicion_con_motivo_declarado"]
                == p["indicadores_que_la_ley_numera"])
        assert (p["con_veredicto_de_cumplimiento"]
                + p["medidos_sin_observacion_utilizable"]
                == p["medidos_con_serie_verificada"])
        assert p["alcanzan_su_meta"] <= p["con_veredicto_de_cumplimiento"]

    def test_el_campo_no_llama_VEREDICTO_a_los_medidos(self, eid):
        """`con_veredicto` contaba los que tienen serie, no los que producen veredicto."""
        r = resumen_del_campo(eid)
        assert "medidos" in r
        assert "con_veredicto" not in r, (
            "el nombre viejo puso dos poblaciones detrás del mismo número")

    def test_toda_clave_de_porcentaje_NOMBRA_su_denominador(self, eid):
        """El sujeto viaja con el número, también cuando el número es una razón."""
        ctx = law_ai_context(eid, "2025", {})

        def recorrer(nodo, ruta=""):
            if isinstance(nodo, dict):
                for k, v in nodo.items():
                    if k.startswith("pct_"):
                        assert "_sobre_" in k, f"«{ruta}.{k}» no dice sobre qué se computa"
                    recorrer(v, f"{ruta}.{k}")
            elif isinstance(nodo, list):
                for x in nodo:
                    recorrer(x, ruta)

        recorrer(ctx)


@pytest.mark.parametrize("eid", EXPEDIENTES)
def test_el_contexto_trae_el_NOMBRE_de_cada_indicador_que_la_ley_numera(eid):
    """Sin el diccionario canónico, una sección cita «2.35» y le pega el rótulo más cercano
    que haya visto — así se publicó un indicador de agua potable como si midiera acceso a
    antirretrovirales."""
    exp = cargar(eid)
    nombres = law_ai_context(eid, "2025", {})["nombres_de_los_indicadores_de_la_ley"]
    assert set(nombres) == {i.id for i in exp.numerados}
    assert all(nombres[i.id] == i.nombre for i in exp.numerados)
    assert all(v.strip() for v in nombres.values())


@pytest.mark.parametrize("eid", EXPEDIENTES)
def test_ninguna_fila_del_contexto_publica_un_ID_PELADO(eid):
    """Toda fila que identifique un indicador por su número lleva su nombre al lado.

    Se recorre el contexto entero en vez de revisar los bloques de a uno: el hueco entra
    siempre por el bloque que alguien agregó después.
    """
    ctx = law_ai_context(eid, "2025", {})
    ids = {i.id for i in cargar(eid).numerados}
    huerfanas = []

    def recorrer(nodo, ruta=""):
        if isinstance(nodo, dict):
            valores = {k: v for k, v in nodo.items() if isinstance(v, str)}
            cita = next((k for k, v in valores.items()
                         if k in ("indicador", "id") and v in ids), None)
            if cita is not None:
                lleva_nombre = any("nombre" in k for k in nodo)
                if not lleva_nombre:
                    huerfanas.append(f"{ruta} → {nodo[cita]}")
            for k, v in nodo.items():
                recorrer(v, f"{ruta}.{k}")
        elif isinstance(nodo, list):
            for x in nodo:
                recorrer(x, ruta)

    recorrer(ctx)
    assert not huerfanas, (
        "filas que citan un indicador sin su nombre —el modelo le pegará el rótulo más "
        f"cercano que tenga: {huerfanas[:6]}")
