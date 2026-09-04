"""El bloque `quality` de la Data API suma la cobertura proyectada, sin tocar la real.

Es aditivo: ningún consumidor existente se rompe. Y la cobertura proyectada viaja SEPARADA
—nunca sumada a `coverage_real`—, que es la asimetría que sostiene todo el bloque: una
proyección puede anclar una pregunta, no puede inflar cuánto de un índice está sostenido por
dato real.
"""
import inspect

from shared.data_api import router


def test_el_payload_de_calidad_declara_la_cobertura_proyectada():
    fuente = inspect.getsource(router)
    assert '"coverage_projected": axis.coverage_projected' in fuente, (
        "el bloque `quality` no expone `coverage_projected`: la cobertura proyectada no "
        "llega al consumidor y el reporte queda sin la mitad de la historia")


def test_sigue_exponiendo_la_cobertura_real_sin_tocarla():
    fuente = inspect.getsource(router)
    assert '"coverage_real": axis.coverage_real' in fuente
