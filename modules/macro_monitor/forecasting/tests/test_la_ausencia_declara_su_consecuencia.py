"""Una ausencia se declara — y también su CONSECUENCIA sobre las que sí se muestran.

`reconciliar` reparte la brecha contra el agregado entre el peso de las actividades
PROYECTABLES, no entre 1. Cuando alguna cae en `brechas`, las mostradas absorben su
contribución: cada una sube más de lo que subiría si estuvieran todas, y ese exceso no viene
de ninguna señal sobre ellas.

La sección lo declaraba a medias. Listaba las ausentes —bien— pero decía «una actividad con
huecos se declara, **no se rellena**», que es lo contrario de lo que hace la aritmética: el
hueco sí se rellena, repartiéndolo. Y la frase de arriba, «la suma ponderada reconcilia
exactamente con el agregado», seguía siendo cierta sobre las filas mostradas justamente
PORQUE se las infló.

Medido sobre el panel real (18 actividades, la mayor 12,26 %), el exceso va de +0,01 a
+0,18 pp según el peso de la que falte. Es chico —por eso la cura es declarar y no
renormalizar— pero la contradicción de la prosa no depende de la magnitud.

Esta es la rama que hoy NO corre: `brechas` está vacío en producción. Un test que no la
siembre no prueba nada.
"""
import pytest

from modules.macro_monitor import products_forecast as pf


def _payload(*, brechas, sectores, brecha_pp, ajuste_pp):
    return {"sectorial": {"horizonte": "2026-Q3", "brecha_pp": brecha_pp,
                          "ajuste_pp": ajuste_pp, "brechas": brechas,
                          "sectores": sectores}}


def _sector(clave, etiqueta, peso, proy, recon):
    return {"clave": clave, "etiqueta": etiqueta, "peso": peso,
            "crecimiento_sin_reconciliar": proy, "crecimiento": recon,
            "incidencia": peso * recon}


#: El caso real: falta una actividad de peso 12,26 % y las mostradas suman 0,8774.
#: brecha = 1,2936 → ajuste = 1,2936 / 0,8774 = 1,4744 → exceso = +0,1808 pp
_BRECHA, _AJUSTE = 1.2935520533342162, 1.2935520533342162 / 0.8774
_CON_BRECHAS = _payload(
    brechas={"construccion": "la serie tiene 3 trimestre(s) sin dato en el tramo común"},
    sectores=[_sector("comercio", "Comercio", 0.5774, 2.52, 2.52 + _AJUSTE),
              _sector("hoteles", "Hoteles, bares y restaurantes", 0.3000, 7.24,
                      7.24 + _AJUSTE)],
    brecha_pp=_BRECHA, ajuste_pp=_AJUSTE)

_SIN_BRECHAS = _payload(
    brechas={},
    sectores=[_sector("comercio", "Comercio", 0.6, 2.52, 3.81),
              _sector("hoteles", "Hoteles, bares y restaurantes", 0.4, 7.24, 8.53)],
    brecha_pp=_BRECHA, ajuste_pp=_BRECHA)


# ── La rama que hoy no corre ────────────────────────────────────────────────────────


def test_declara_que_la_contribucion_ausente_se_REPARTIO():
    """Se compara contra la frase RENDERIZADA de la constante, no contra la palabra
    «repart»: la prosa permanente ya dice «el reparto es proporcional al PESO», así que la
    primera versión de este test pasaba en verde contra el código que no declaraba nada."""
    s = _CON_BRECHAS["sectorial"]
    md = pf._md_sectorial(_CON_BRECHAS)
    assert pf._CONSECUENCIA_DE_LA_AUSENCIA.split("{")[0] in md, (
        f"no declara la consecuencia de la ausencia:\n{md}")
    assert "se reparte por peso sobre las demás" in md, md
    assert s["ajuste_pp"] != s["brecha_pp"], "la fixture no ejercita la rama"


def test_nombra_la_actividad_ausente_con_su_MOTIVO():
    md = pf._md_sectorial(_CON_BRECHAS)
    assert "Construcción" in md, f"nombra la clave cruda en vez de la etiqueta:\n{md}"
    assert "sin dato en el tramo común" in md, f"no da el motivo:\n{md}"


def test_da_el_PESO_total_ausente():
    """Σpeso de las mostradas es 0,8774, así que falta 12,26 %. Es exacto: los componentes
    del cuadro nominal suman el PIB."""
    md = pf._md_sectorial(_CON_BRECHAS)
    assert "12,26" in md or "12.26" in md, f"no dice cuánto peso falta:\n{md}"


def test_da_el_EXCESO_en_pp_y_es_COMPUTADO():
    """El exceso es `ajuste − brecha`: lo que cada actividad sube de más por cubrir a la que
    falta. Se compara contra el valor calculado del payload, no contra una constante — una
    cifra escrita a mano se desincroniza del cómputo y este test la dejaría pasar."""
    s = _CON_BRECHAS["sectorial"]
    esperado = s["ajuste_pp"] - s["brecha_pp"]
    md = pf._md_sectorial(_CON_BRECHAS)
    assert f"{esperado:+.3f}" in md, (
        f"no publica el exceso computado ({esperado:+.3f} pp):\n{md}")


# ── El contraejemplo: sin brechas la frase NO sale ──────────────────────────────────


def test_sin_brechas_NO_declara_ninguna_redistribucion():
    """Sin esto, una frase impresa siempre pasaría todos los tests de arriba y el informe
    avisaría de un reparto que no ocurrió — hoy `brechas` está vacío en producción.

    Se busca el fragmento DISTINTIVO de la frase nueva y no la palabra «reparto»: la prosa
    permanente habla legítimamente de repartir la brecha, y prohibirla marcaría el texto
    correcto.
    """
    md = pf._md_sectorial(_SIN_BRECHAS)
    assert "se reparte por peso sobre las demás" not in md, (
        f"declaró una redistribución sin actividades ausentes:\n{md}")
    assert "No proyectadas" not in md


# ── La frase permanente ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("p", [_CON_BRECHAS, _SIN_BRECHAS])
def test_la_prosa_ya_no_dice_que_el_hueco_NO_se_rellena(p):
    """Decía «se declara, no se rellena». El hueco sí se rellena: se reparte. Que la prosa
    diga lo que hace la aritmética, en la rama que corre y en la que no."""
    assert "no se rellena" not in pf._md_sectorial(p).lower()


# ── El signo ────────────────────────────────────────────────────────────────────────


def test_la_frase_es_NEUTRA_respecto_del_signo():
    """Con una brecha negativa el ajuste baja, y la primera versión decía «sube −0,008 pp»:
    una frase que afirma una dirección contraria a la del número que la acompaña. Lo destapó
    la muestra curada al reconstruirla —todos mis casos usaban brecha positiva—, que es por
    qué la muestra tiene que cerrar sola y no ser cifras de adorno.
    """
    negativo = _payload(
        brechas={"comunicaciones": "la serie tiene 2 trimestre(s) sin dato"},
        sectores=[_sector("comercio", "Comercio", 0.5774, 2.52, 1.66),
                  _sector("hoteles", "Hoteles, bares y restaurantes", 0.4133, 7.24, 6.38)],
        brecha_pp=-0.8522, ajuste_pp=-0.8601)
    md = pf._md_sectorial(negativo)
    assert "-0.009" in md or "-0.008" in md, md
    for direccion in ("sube", "subiría", "baja", "bajaría"):
        assert f"{direccion} **-" not in md and f"{direccion} **+" not in md, (
            f"la frase afirma una dirección al lado de un número con signo:\n{md}")
