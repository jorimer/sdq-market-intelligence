"""La muestra curada tiene que satisfacer las identidades del propio método.

Una vidriera con un número que el motor no produce enseña a desconfiar del motor. La casa ya
lo tiene escrito para los productos —«la muestra tiene que ser producible por el motor»— y
`test_la_muestra_curada_se_renderiza` solo comprueba que el PDF pesa más de 5 KB: que renderice
no dice nada de si los números cierran entre sí.

Lo que la muestra de `macro_forecast` publicaba, medido:

* `ajuste_pp = −0,4713` cuando la aritmética de `reconciliar` da `brecha / Σpeso = −0,8369`
  y, si estuvieran todas, `= brecha = −0,4178`. No es ninguno de los dos: es un número que
  no sale de ningún cómputo.
* `Σ peso = 0,4992` con `brechas: {}` — la mitad del cuadro ausente y declarada completa.
* `Σ incidencia = 2,0090` contra un titular de 3,41: la sección abre afirmando que «la suma
  ponderada **reconcilia exactamente** con el agregado» y su propia muestra la desmiente por
  1,40 pp.

Las tres son la misma familia que el Ke de la muestra de valuación.
"""
import pytest

from modules.macro_monitor.products_forecast import _SAMPLE_PAYLOAD

_SECT = _SAMPLE_PAYLOAD["sectorial"]
_TOL = 5e-3          # las cifras de la muestra van a 2-3 decimales


def test_hay_muestra_sectorial_que_revisar():
    """Prueba NEGATIVA: sin sectores no hay identidad que violar y todo pasa en verde."""
    assert len(_SECT["sectores"]) >= 5


def test_los_pesos_suman_el_cuadro_COMPLETO_cuando_no_hay_brechas():
    """Con `brechas` vacío, el cuadro está entero: los componentes nominales del BCRD suman
    el PIB. Mostrar la mitad y declarar que no falta nada es la contradicción."""
    sp = sum(s["peso"] for s in _SECT["sectores"])
    if not _SECT["brechas"]:
        assert abs(sp - 1.0) < _TOL, (
            f"la muestra declara `brechas: {{}}` y sus pesos suman {sp:.4f}: o falta "
            "declarar las ausentes, o faltan actividades en la tabla")


def test_el_ajuste_es_el_QUE_LA_ARITMETICA_DA():
    """`ajuste = brecha / Σpeso`. Un ajuste que no sale de ahí es una cifra inventada en la
    vidriera del producto."""
    sp = sum(s["peso"] for s in _SECT["sectores"])
    esperado = _SECT["brecha_pp"] / sp if sp > 0 else 0.0
    assert abs(_SECT["ajuste_pp"] - esperado) < _TOL, (
        f"la muestra publica ajuste_pp={_SECT['ajuste_pp']:+.4f} y la aritmética da "
        f"{esperado:+.4f} (brecha {_SECT['brecha_pp']:+.4f} ÷ Σpeso {sp:.4f})")


def test_la_suma_ponderada_RECONCILIA_como_la_seccion_afirma():
    """La sección abre diciendo que reconcilia exactamente. Si la muestra no lo cumple, el
    texto y la tabla se contradicen en la misma página."""
    g = _SAMPLE_PAYLOAD["proyecciones"][0]["punto"]
    si = sum(s["incidencia"] for s in _SECT["sectores"])
    assert abs(si - g) < _TOL, (
        f"Σ incidencia = {si:.4f} contra un agregado de {g}: difieren {si - g:+.4f} pp")


@pytest.mark.parametrize("s", _SECT["sectores"], ids=lambda s: s["etiqueta"][:24])
def test_cada_incidencia_es_su_peso_por_su_crecimiento(s):
    assert abs(s["peso"] * s["crecimiento"] - s["incidencia"]) < _TOL, (
        f"{s['etiqueta']}: {s['peso']:.4f} × {s['crecimiento']} = "
        f"{s['peso']*s['crecimiento']:.4f}, publicado {s['incidencia']}")


def test_el_ajuste_es_la_DIFERENCIA_entre_las_dos_columnas():
    """Las dos columnas existen para que el ajuste se vea. Si no es su diferencia, la tabla
    enseña un ajuste que no ocurrió entre las cifras que muestra."""
    for s in _SECT["sectores"]:
        crudo = s.get("crecimiento_sin_reconciliar")
        if crudo is None:
            continue
        assert abs((s["crecimiento"] - crudo) - _SECT["ajuste_pp"]) < _TOL, (
            f"{s['etiqueta']}: {crudo} → {s['crecimiento']} es "
            f"{s['crecimiento']-crudo:+.4f} pp, y el ajuste declarado es "
            f"{_SECT['ajuste_pp']:+.4f}")
