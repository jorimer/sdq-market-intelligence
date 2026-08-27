"""Las DOS lecturas del año, que hasta el 2026-08-27 eran la misma.

**El defecto.** «SDQ Banking Intelligence» y «SDQ Banking · Revisión Anual» llamaban los dos a
`revision_anual`, que es un híbrido: trae el camino DENTRO del año *y* la comparación contra el
cierre anterior. El dueño lo vio en la app —«en dos productos diferentes se está sirviendo el
mismo reporte»— y fijó la separación:

* **Intelligence** → el año POR DENTRO: la serie de sus trimestres y el movimiento de cada
  tramo. La pregunta es **cuándo**.
* **Revisión Anual** → el año TOTAL contra los años anteriores y la tendencia. La pregunta es
  **contra qué**.

La diferencia no es de profundidad ni de sujeto: es la **unidad de comparación**. Estos tests
fijan que no vuelvan a colapsar.
"""
from __future__ import annotations

import pytest

from modules.banking_score.reports.anio_contra_anios import _tendencia, _variaciones
from modules.banking_score.reports.anio_por_trimestres import _tramo_que_mas_movio, _tramos

#: Serie REAL de Bonao 2025, de la trayectoria publicada en su Deep Dive de diciembre.
SERIE_2025 = [
    {"period_end": "2024-12-31", "score": 64.73}, {"period_end": "2025-03-31", "score": 64.24},
    {"period_end": "2025-06-30", "score": 62.53}, {"period_end": "2025-09-30", "score": 62.41},
    {"period_end": "2025-12-31", "score": 58.71},
]
#: Cierres anuales sintéticos con una reversión en 2024, para que la racha no sea trivial.
CIERRES = [{"anio": a, "score": s, "banda": b, "corte": f"{a}-12-31"} for a, s, b in
           [(2020, 71.2, "Sólida"), (2021, 69.8, "Sólida"), (2022, 66.4, "Adecuada"),
            (2023, 63.0, "Adecuada"), (2024, 64.73, "Adecuada"), (2025, 58.71, "Adecuada")]]


# ── El año POR DENTRO: la pregunta es CUÁNDO ───────────────────────────

def test_da_el_movimiento_de_CADA_trimestre_y_no_solo_los_extremos():
    """Amplitud, pico y valle dicen cuánto se movió el año; el tramo dice EN QUÉ TRIMESTRE.
    «Cayó todo el año» y «cayó en el cuarto» son años distintos con el mismo cierre."""
    t = {x["tramo"]: x for x in _tramos(SERIE_2025)}
    assert t["cuarto trimestre"]["cambio"] == -3.70
    assert t["cuarto trimestre"]["direccion"] == "a la baja"


def test_un_tramo_INMATERIAL_no_se_llama_movimiento():
    t = {x["tramo"]: x for x in _tramos(SERIE_2025)}
    assert t["tercer trimestre"]["cambio"] == -0.12
    assert t["tercer trimestre"]["direccion"] == "estable"


def test_computa_QUE_CUOTA_del_año_concentró_un_trimestre():
    """Es una RELACIÓN —«el 61,5 % de la caída ocurrió en el cuarto trimestre»— y por eso se
    computa: deducirla es lo que el modelo hace mal."""
    m = _tramo_que_mas_movio(_tramos(SERIE_2025))
    assert m["tramo"] == "cuarto trimestre"
    assert m["cuota_del_movimiento_pct"] == pytest.approx(61.5, abs=0.2)


def test_la_cuota_se_mide_sobre_el_ABSOLUTO_y_no_sobre_el_neto():
    """Sobre el neto, un año que baja y sube daría cuotas por encima del 100 % sin que nada
    esté mal — y una cuota de 340 % en un informe destruye la confianza en todo el resto."""
    sube_y_baja = [{"period_end": "2024-12-31", "score": 60.0},
                   {"period_end": "2025-03-31", "score": 50.0},
                   {"period_end": "2025-06-30", "score": 60.0},
                   {"period_end": "2025-12-31", "score": 61.0}]
    m = _tramo_que_mas_movio(_tramos(sube_y_baja))
    assert 0 < m["cuota_del_movimiento_pct"] <= 100


# ── El año CONTRA los años: la pregunta es CONTRA QUÉ ──────────────────

def test_compara_año_contra_año_y_marca_el_cambio_de_banda():
    v = {x["anio"]: x for x in _variaciones(CIERRES)}
    assert v[2025]["cambio"] == -6.02
    assert v[2022]["cambio_de_banda"] == {"desde": "Sólida", "hasta": "Adecuada"}
    assert v[2024]["direccion"] == "al alza"


def test_la_RACHA_se_corta_cuando_cambia_la_direccion():
    """Un mal año y el cuarto consecutivo bajando son decisiones de exposición distintas. Con
    la reversión de 2024, la racha a la baja es de UNO — no de cinco."""
    t = _tendencia(_variaciones(CIERRES), len(CIERRES))
    assert t["direccion_sostenida"] == "a la baja"
    assert t["anios_consecutivos"] == 1


def test_un_año_ESTABLE_no_corta_la_racha_ni_la_alarga():
    """Cortarla con un año plano diría que el deterioro se detuvo cuando solo hizo una pausa;
    contarlo como parte de la racha afirmaría un movimiento que no hubo."""
    serie = [{"anio": a, "score": s, "banda": "X", "corte": f"{a}-12-31"} for a, s in
             [(2021, 70.0), (2022, 66.0), (2023, 65.9), (2024, 62.0)]]
    t = _tendencia(_variaciones(serie), len(serie))
    assert t["direccion_sostenida"] == "a la baja"
    assert t["anios_consecutivos"] == 2


def test_DECLARA_su_horizonte_y_de_quien_es_el_limite():
    """Seis cierres no son «siempre». Y el piso de 2020 es NUESTRO backfill, no el de la
    fuente: confundirlos sería leer «no hay dato» donde dice «no lo trajimos»."""
    t = _tendencia(_variaciones(CIERRES), len(CIERRES))
    assert t["horizonte_disponible"] == 6
    assert "backfill" in t["por_que_este_horizonte"]


def test_con_UN_solo_cierre_no_se_finge_una_tendencia():
    t = _tendencia(_variaciones(CIERRES[:1]), 1)
    assert t["anios_comparados"] == 0
    assert "no se puede hablar de tendencia" in t["lectura"]


# ── Que no vuelvan a colapsar ──────────────────────────────────────────

def test_cada_producto_llama_a_SU_lectura():
    """El defecto era literalmente que los dos llamaban a la misma función."""
    import inspect

    from modules.banking_score import products, products_year_review

    trimestral = inspect.getsource(products)
    anual = inspect.getsource(products_year_review)
    assert "anio_por_trimestres" in trimestral and "anio_contra_anios" not in trimestral
    assert "anio_contra_anios" in anual and "anio_por_trimestres" not in anual


def test_cada_lectura_DECLARA_cuál_es_para_que_el_modelo_no_las_mezcle():
    """El contexto lleva la frontera escrita. Sin ella, el modelo del año por dentro habla de
    tendencia plurianual con dos puntos, que es el error que originó todo esto."""
    from modules.banking_score.reports import anio_contra_anios as b
    from modules.banking_score.reports import anio_por_trimestres as a

    assert "POR DENTRO" in inspect_texto(a)
    assert "contra los años" in inspect_texto(b).lower()


def inspect_texto(mod) -> str:
    import inspect
    return inspect.getsource(mod)
