"""Un contenedor de magnitudes DECLARA su unidad, o el guard vetará cómo se dicen.

**Tercera instancia del mismo defecto en una semana**, y la que más costó encontrar. Las
magnitudes relacionales viajan al modelo de DOS formas:

1. en una FILA con su clave — ``{"razon_vs_referencia": 1.32}``
2. dentro de un CONTENEDOR cuyo nombre declara la unidad de todo lo de adentro —
   ``{"pesos_sub_componentes": {"solidez": 0.38, "calidad": 0.34}}``, donde las claves son los
   SUJETOS y no la magnitud.

El detector solo miraba la primera. El caso real, capturado con la frase que el modelo escribió
—que es exactamente para lo que se agregó el registro de fragmentos—:

    «La dimensión de mayor peso en el modelo (solidez de capital, ponderación 38 %) sostiene
     la calificación con 82.32 puntos»

El 0,38 estaba servido: es el peso de solidez para las AAyP. El modelo lo dijo como se dice un
peso. El guard lo marcó como inventado y el informe no se entregó — tres veces.

Este test barre los contextos REALES que produce banca y falla si aparece un contenedor de
decimales entre 0 y 1 que nadie declaró. Un decimal en esa banda es un candidato a decirse en
porcentaje, que es la forma en la que el defecto se manifiesta.

**Qué queda afuera, a propósito:** se barre `modules/banking_score`, que es el eje que produce
la mayoría de los informes narrados y el único cuyo constructor de contexto es alcanzable sin
base de datos. Un eje nuevo con contexto propio no queda cubierto por este barrido — lo que sí
lo cubre es que su contenedor se declare, y esta prueba deja escrito por qué.
"""
import pytest

from shared.narrative.numeric_guard import (CONTENEDORES_RELACIONALES, FORMAS_POR_CLAVE,
                                            deterministic_uncited_figures)


def _contextos_reales():
    """Un contexto por sección del SDQ Rating, con la muestra versionada del módulo."""
    from modules.banking_score.products import SAMPLE_PEER, SAMPLE_SCORING
    from modules.banking_score.reports.narrative import (REPORT_SECTIONS,
                                                         _build_section_context)
    for seccion in REPORT_SECTIONS.get("full_rating", ()):
        try:
            yield seccion, _build_section_context(
                seccion, "Entidad de Prueba", dict(SAMPLE_SCORING), "2025-03-31",
                dict(SAMPLE_PEER))
        except Exception:  # noqa: BLE001 — una sección que la muestra no soporta no es el objeto
            continue


def _contenedores(obj, ruta="ctx"):
    """Dicts cuyos valores son TODOS decimales entre 0 y 1: candidatos a decirse en %."""
    hallados = {}

    def _walk(o, r):
        if isinstance(o, dict):
            nums = [v for v in o.values()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums and len(nums) == len(o) and all(0 < abs(v) < 1 for v in nums):
                hallados.setdefault(r.split(".")[-1], sorted(nums))
            for k, v in o.items():
                _walk(v, f"{r}.{k}")
        elif isinstance(o, list):
            for v in o:
                _walk(v, f"{r}[]")

    _walk(obj, ruta)
    return hallados


def test_el_barrido_encuentra_algo():
    """Prueba negativa: sin secciones, la regla de abajo pasa sin mirar nada."""
    secciones = list(_contextos_reales())
    assert secciones, "el barrido no construyó ningún contexto — la regla no protege nada"


def test_todo_contenedor_de_magnitudes_declara_su_unidad():
    sin_declarar = {}
    for seccion, ctx in _contextos_reales():
        for nombre, valores in _contenedores(ctx).items():
            if nombre in CONTENEDORES_RELACIONALES or nombre in FORMAS_POR_CLAVE:
                continue
            sin_declarar.setdefault(nombre, (seccion, valores))
    assert not sin_declarar, (
        f"Estos contenedores llevan decimales que el modelo va a decir en PORCENTAJE y nadie "
        f"declaró su unidad: {sin_declarar}. Sin declararlos, el guard marca como inventada "
        "una cifra que sí servimos y el informe no se entrega — pasó tres veces. Agregalos a "
        "CONTENEDORES_RELACIONALES en shared/narrative/numeric_guard.py.")


@pytest.mark.parametrize("cita", ["38", "34", "13"])
def test_el_peso_de_la_rubrica_se_puede_decir_en_porcentaje(cita):
    """El caso concreto, con los pesos REALES de una AAyP."""
    ctx = {"pesos_sub_componentes": {"solidez": 0.38, "calidad": 0.34, "eficiencia": 0.13,
                                     "liquidez": 0.1, "diversificacion": 0.05}}
    assert deterministic_uncited_figures(ctx, f"ponderación de {cita}%") == []


def test_un_porcentaje_que_NO_es_ningun_peso_se_sigue_marcando():
    """El contrapeso: sin él, declarar un contenedor abriría el guard de par en par."""
    ctx = {"pesos_sub_componentes": {"solidez": 0.38, "calidad": 0.34}}
    assert deterministic_uncited_figures(ctx, "ponderación de 27%")
