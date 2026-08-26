"""El guard verifica una cita A LA PRECISIÓN QUE ELLA DECLARA, no a una fija.

El defecto real (prod, 2026-08-24, Deep Dive de Banco Múltiple Caribe Internacional al
2026-03-31): el informe se vetó ENTERO por `{'eficiencia_rentabilidad': ['69%: no aparece en
el contexto servido']}`. Pero la trayectoria de `cost_to_income` servida en ese mismo contexto
traía 69,1344% (jun-2024) y 69,4575% (dic-2024). Había un 69 real y citable: el guard comparaba
siempre a UN decimal, "veía" 69,1 y 69,4, y la cita redondeada a entero (69,0) no matcheaba.

Costo del falso positivo: 157 s de generación y ~US$1 de modelo para un error genérico en
pantalla, con el producto sin entregar. Vetar prosa correcta no es "ser estricto".

Contrapartida DECLARADA (y aceptada a sabiendas): un entero inventado pasa si el contexto tiene
algo en su banda de redondeo. Éste es el filtro mecánico y barato, y nunca fue el único — el
juez semántico del motor corre aparte y ve lo que éste no.
"""
import pytest

from shared.narrative.numeric_guard import (context_figures, context_values,
                                            deterministic_uncited_figures)

#: Contexto REAL del caso de prod: la trayectoria de cost-to-income al corte.
_CTX = {
    "indicadores": {"cost_to_income": {"raw": 49.3813, "score": 81.24}},
    "amplitud_indicadores": {"cost_to_income": {"trayectoria": [
        {"period_end": "2024-06-30", "raw": 69.1344, "score": 41.73},
        {"period_end": "2024-12-31", "raw": 69.4575, "score": 41.08},
        {"period_end": "2026-03-31", "raw": 49.3813, "score": 81.24},
    ]}},
}


def test_el_caso_de_prod_ya_no_se_veta():
    """La frase que el veto habría bloqueado es VERDADERA y está respaldada."""
    texto = "El cost-to-income mejoró desde 69% en 2024 hasta 49,4% en el corte."
    assert deterministic_uncited_figures(_CTX, texto) == []


@pytest.mark.parametrize("cita", ["69%", "69,1%", "69,13%", "69,4%", "69,46%", "69,5%"])
def test_toda_forma_legitima_de_acortar_69_1344_o_69_4575_pasa(cita):
    """Redondeo y truncación, a cualquier profundidad de decimales."""
    assert deterministic_uncited_figures(_CTX, f"Se ubicó en {cita} al cierre.") == []


@pytest.mark.parametrize("cita", ["85%", "103,1%", "69,9%", "68,4%", "50,2%"])
def test_una_cifra_que_el_contexto_no_sostiene_se_sigue_marcando(cita):
    """La prueba de que el aflojamiento no vació el guard. `69,9%` es el caso fino: cae dentro
    del entero 69 pero fuera de toda lectura de 69,1344 / 69,4575 a un decimal."""
    flags = deterministic_uncited_figures(_CTX, f"Se ubicó en {cita} al cierre.")
    assert flags, f"'{cita}' debería marcarse: el contexto no la sostiene"


def test_una_cita_MAS_precisa_que_el_contexto_ya_no_se_cuela():
    """La regla corta en las DOS direcciones, y por eso hubo que bumpear `GUARD_VERSION`.

    El código viejo redondeaba la CITA a un decimal antes de comparar: "69,08%" se volvía 69,1
    y matcheaba un contexto de 69,14 — dejaba pasar una cifra que el contexto no dice. Verificar
    a la precisión declarada lo cierra. Como el guard nuevo puede marcar texto que el viejo
    aceptaba, una narrativa YA CACHEADA podría no cumplir la regla nueva: la huella de receta
    tiene que rotar."""
    assert deterministic_uncited_figures({"x": 69.14}, "Se ubicó en 69,08% al cierre.")


def test_guard_version_declara_la_regla_vigente():
    """El único bump manual irreducible de la huella de caché: un cambio en la LÓGICA de este
    módulo no toca ningún prompt y pasaría inadvertido."""
    from shared.narrative.numeric_guard import GUARD_VERSION

    assert GUARD_VERSION == "11", (
        "Si cambiaste la lógica del guard, bumpeá GUARD_VERSION y actualizá este test: si no, "
        "la caché sigue sirviendo texto que la regla nueva evaluaría distinto.")


def test_sin_numeros_en_el_contexto_no_se_marca_nada():
    """Sin insumo no hay verificación, y fingirla sería el modo de falla que la regla cierra."""
    assert deterministic_uncited_figures({"texto": "sin cifras"}, "Alcanzó el 42%.") == []


def test_context_values_devuelve_los_valores_CRUDOS():
    """Fijar la precisión al recolectar fue lo que produjo el falso positivo: quien compara
    tiene que poder elegirla."""
    vals = context_values(_CTX)
    assert 69.1344 in vals and 69.4575 in vals, sorted(vals)


def test_context_figures_sigue_sirviendo_a_la_cobertura():
    """`guard_coverage` la usa para responder «¿hay cifras?»; no se rompe su contrato."""
    figs = context_figures(_CTX)
    assert 69.1 in figs and 69.5 in figs, sorted(figs)
