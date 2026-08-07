"""Perfil SDQ en pensiones — Fase 3 (spec §6)."""
import pytest

from modules.pension_intel.scoring.perfil_sdq import (
    FUERA_DE_LOS_EJES,
    PESOS_EJECUCION,
    PESOS_RESILIENCIA,
    banda_ejecucion,
    banda_resiliencia,
    calcular_ejes,
    perfil_panel,
)

_DIMS = {"solvencia": 90.0, "riesgo": 60.0, "rentabilidad": 50.0, "costo": 70.0,
         "escala": 85.0}


def test_los_pesos_renormalizan_sin_alterar_proporciones():
    """El ISA tenía solvencia:riesgo = 35:15 y rentabilidad:costo = 25:10 (§6.5)."""
    assert PESOS_RESILIENCIA["solvencia"] / PESOS_RESILIENCIA["riesgo"] == pytest.approx(
        0.35 / 0.15, abs=0.02)
    assert PESOS_EJECUCION["rentabilidad"] / PESOS_EJECUCION["costo"] == pytest.approx(
        0.25 / 0.10, abs=0.05)
    assert sum(PESOS_RESILIENCIA.values()) == pytest.approx(1.0)
    assert sum(PESOS_EJECUCION.values()) == pytest.approx(1.0)


def test_escala_queda_fuera_de_los_dos_ejes():
    """§6.4: el ISA ya tiene volatilidad del NAV, una señal REAL de riesgo. El proxy de
    tamaño no aporta nada que la señal directa no diga mejor — y metía ruido: AFP Romana es
    la más pequeña del sistema y la más resiliente."""
    assert "escala" in FUERA_DE_LOS_EJES
    assert "escala" not in PESOS_RESILIENCIA and "escala" not in PESOS_EJECUCION
    # Cambiar Escala no mueve ninguno de los dos ejes.
    a = calcular_ejes(_DIMS)
    b = calcular_ejes(dict(_DIMS, escala=2.0))
    assert a["ejecucion"] == b["ejecucion"] and a["resiliencia"] == b["resiliencia"]
    # Pero se sigue reportando, para que la decisión sea auditable y no un olvido.
    assert b["fuera_de_los_ejes"]["escala"] == 2.0


def test_una_dimension_ausente_no_cuenta_como_cero():
    e = calcular_ejes(dict(_DIMS, costo=None))
    # La cobertura se redondea a 2 decimales para la respuesta.
    assert e["cobertura_ejecucion"] == pytest.approx(
        round(PESOS_EJECUCION["rentabilidad"], 2))
    assert e["ejecucion"] == pytest.approx(50.0)   # solo rentabilidad, renormalizada


def test_sin_ninguna_dimension_del_eje_el_eje_es_none():
    e = calcular_ejes({"escala": 90.0})
    assert e["ejecucion"] is None and e["resiliencia"] is None
    assert e["banda_ejecucion"] is None and e["banda_resiliencia"] is None


def test_las_bandas_usan_el_vocabulario_de_cada_eje():
    assert banda_resiliencia(80) == "Sólida" and banda_ejecucion(80) == "Sobresaliente"
    assert banda_resiliencia(62) == "Adecuada" and banda_ejecucion(62) == "Competitiva"
    assert banda_resiliencia(50) == "En vigilancia" and banda_ejecucion(50) == "Rezagada"
    assert banda_resiliencia(10) == "Frágil" and banda_ejecucion(10) == "Deficiente"


def test_el_split_separa_dos_fragiles_por_razones_opuestas():
    """Caso real: Atlántico y JMMB comparten "Frágil" en el ISA por causas distintas.

    Atlántico es sólida y rinde mal; JMMB tiene un problema de solvencia, no de desempeño.
    Un índice único no puede decir eso.
    """
    atlantico = calcular_ejes({"solvencia": 55.5, "riesgo": 93.0,
                               "rentabilidad": 7.1, "costo": 40.7})
    jmmb = calcular_ejes({"solvencia": 15.2, "riesgo": 96.1,
                          "rentabilidad": 47.4, "costo": 50.4})
    assert atlantico["resiliencia"] > jmmb["resiliencia"]     # Atlántico es más sólida…
    assert atlantico["ejecucion"] < jmmb["ejecucion"]         # …y rinde mucho peor


def test_la_regla_de_n_chico_expone_posicion_en_AMBOS_ejes():
    """Con 7 AFP, "Sobresaliente" dice bastante menos que entre 42 (§4.2)."""
    afps = [{"slug": f"a{i}", "name": f"AFP {i}",
             "dimension_scores": dict(_DIMS, rentabilidad=r, solvencia=s)}
            for i, (r, s) in enumerate([(90, 40), (70, 60), (50, 80), (30, 95)])]
    res = perfil_panel(afps)
    assert res["count"] == 4
    for f in res["perfil"]:
        assert f["requiere_posicion_visible"] is True and f["universo"] == 4
        assert 1 <= f["posicion_ejecucion"] <= 4 and 1 <= f["posicion_resiliencia"] <= 4
    # Las posiciones son independientes por eje: el mejor en uno no es el mejor en el otro.
    mejor_e = min(res["perfil"], key=lambda f: f["posicion_ejecucion"])
    mejor_r = min(res["perfil"], key=lambda f: f["posicion_resiliencia"])
    assert mejor_e["slug"] != mejor_r["slug"]
