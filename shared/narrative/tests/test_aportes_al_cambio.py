"""Qué MOVIÓ el score se computa; el modelo no lo decide mirando las series.

`derived_figures` ya servía el aporte de cada componente al NIVEL (score × peso). Faltaba el
aporte al CAMBIO, que es otra relación: **la dimensión que más se movió no es la que más movió
el resultado**, porque los pesos difieren.

Defecto real en un informe ENTREGADO (Insight de Asociación Bonao, 2025-12-31, §1):

    «el deterioro se aceleró en el segundo semestre de 2025, impulsado precisamente por el
     colapso de eficiencia»

En ese semestre la eficiencia **mejoró** (+0.96) y aportó **+0.12** al score. La caída la
causaron solidez (−2.24) y calidad (−1.34): el 97% del total. El colapso de eficiencia había
sido en el PRIMER semestre (−8.77). Todas las cifras del informe eran correctas — el contexto
servía las cinco series. Lo derivado, y errado, fue la atribución.
"""
import pytest

from modules.banking_score.scoring.weights import get_sub_component_weights
from shared.narrative.derived import aportes_al_cambio

#: Trayectoria REAL de Bonao, ocho cortes (2024-03 → 2025-12), verificada contra producción.
_SERIES = {
    "solidez":         [79.02, 79.84, 81.56, 81.61, 82.32, 80.53, 79.78, 74.64],
    "calidad":         [78.71, 77.81, 76.97, 77.54, 75.21, 76.10, 76.43, 72.15],
    "eficiencia":      [28.99, 27.20, 24.71, 19.24, 16.84, 10.47,  8.03, 11.43],
    "liquidez":        [61.29, 60.03, 62.05, 61.49, 61.53, 59.19, 61.58, 57.21],
    "diversificacion": [22.77, 20.82, 20.77, 21.91, 28.78, 23.24, 21.73, 22.75],
}
_TRAY = {k: [{"score": s} for s in v] for k, v in _SERIES.items()}
_PESOS = get_sub_component_weights("aap")


def _ventana(nombre):
    return next(v for v in aportes_al_cambio(_TRAY, _PESOS) if v["ventana"] == nombre)


# ── El caso publicado ──────────────────────────────────────────────────

def test_EL_CASO_el_semestre_no_lo_movio_la_eficiencia():
    v = _ventana("el último semestre")
    assert v["principal"] == "solidez", v["principal"]
    aporte_ef = next(a for a in v["aportes"] if a["componente"] == "eficiencia")
    assert aporte_ef["aporte_al_cambio"] > 0, (
        "la eficiencia MEJORÓ en el semestre: no pudo impulsar la caída")


def test_el_colapso_de_eficiencia_fue_en_el_OTRO_semestre():
    """La afirmación del informe no era falsa por inventada, sino por estar en la ventana
    equivocada. Con la serie completa, el año sí carga una caída fuerte de eficiencia."""
    anio = _ventana("el último año")
    ef = next(a for a in anio["aportes"] if a["componente"] == "eficiencia")
    assert ef["delta_score"] < -7, ef


def test_la_dimension_que_MAS_SE_MUEVE_no_es_la_que_mas_mueve_el_score():
    """El corazón del defecto: sin los pesos, eficiencia parece la explicación del año."""
    anio = _ventana("el último año")
    mas_movida = min(anio["aportes"], key=lambda a: a["delta_score"])["componente"]
    assert mas_movida == "eficiencia"
    assert anio["principal"] == "solidez"


# ── La identidad que lo hace verificable ───────────────────────────────

@pytest.mark.parametrize("nombre", ["el último trimestre", "el último semestre", "el último año"])
def test_los_aportes_SUMAN_el_cambio_total(nombre):
    v = _ventana(nombre)
    assert sum(a["aporte_al_cambio"] for a in v["aportes"]) == pytest.approx(
        v["cambio_total"], abs=0.02)


def test_la_ventana_viaja_con_el_numero():
    """«Lo que movió el score» sin decir en qué período no significa nada — y una dimensión
    puede hundirlo en un semestre y sostenerlo en el otro."""
    for v in aportes_al_cambio(_TRAY, _PESOS):
        assert v["ventana"] and v["ventana"] in v["lectura"]


# ── Bordes ─────────────────────────────────────────────────────────────

def test_no_se_emite_una_ventana_que_la_serie_no_soporta():
    """Una ventana inventada es peor que una ventana ausente."""
    corta = {k: v[-2:] for k, v in _TRAY.items()}      # solo dos cortes
    nombres = [v["ventana"] for v in aportes_al_cambio(corta, _PESOS)]
    assert nombres == ["el último trimestre"], nombres


def test_si_el_score_SUBE_el_principal_es_quien_mas_empuja():
    """Tomar siempre el mínimo daría, en un score que sube, «el principal» a quien menos
    ayudó."""
    subiendo = {"a": [{"score": 10.0}, {"score": 30.0}],
                "b": [{"score": 10.0}, {"score": 12.0}]}
    v = aportes_al_cambio(subiendo, {"a": 0.5, "b": 0.5})[0]
    assert v["cambio_total"] > 0 and v["principal"] == "a"


def test_sin_serie_no_se_inventa_nada():
    assert aportes_al_cambio({}, _PESOS) == []


def test_los_pesos_son_los_del_TIPO_de_entidad():
    """Con los pesos de banca múltiple sobre una asociación, la cuota del principal cambia —
    es el mismo defecto que ya se corrigió en la tabla del PDF."""
    aap = _ventana("el último año")["cuota_del_principal_pct"]
    bm = next(v for v in aportes_al_cambio(_TRAY, get_sub_component_weights("banca_multiple"))
              if v["ventana"] == "el último año")["cuota_del_principal_pct"]
    assert aap != bm
