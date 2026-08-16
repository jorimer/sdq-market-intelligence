"""El guard determinista estaba atado a la forma del contexto de banca.

**La prueba negativa que lo destapó.** Sobre el contexto real de una sección de marca en
producción, un texto con el 61 % donde el dato dice 84 %, un error de 2,3 % donde dice
7,4 % y un local inexistente pasaba con CERO banderas. `guard_flags=0` no decía «las
cifras están bien», decía «no se verificó nada» — y esa distinción no se ve sin una prueba
que le dé al guard algo falso a propósito.

`deterministic_uncited_figures` no conoce ninguna forma: extrae los números del contexto,
sea cual sea su estructura, y exige que toda cifra citada esté entre ellos.

Los umbrales de este archivo salieron de medir, no de elegir. Cada uno tiene su cifra en
el test que lo fija, para que quien los mueva sepa qué está pagando.
"""
import math

from shared.narrative.numeric_guard import (
    context_figures,
    deterministic_uncited_figures,
    deterministic_unsupported,
    guard_coverage,
)


# ─────────────────────────────────────────────────────────────────────────────
# La prueba negativa: el defecto que esto vino a cerrar
# ─────────────────────────────────────────────────────────────────────────────

CONTEXTO_MARCA = {
    "pct_incertidumbre_venta_que_aporta_el_trafico": 84,
    "error_medio_trafico_pct": 7.41,
    "error_medio_cheque_pct": 3.62,
    "error_de_la_vara_trafico_pct": 12.94,
    "locales_proyectables": 28,
    "locales_en_el_panel": 30,
    "locales": [
        {"label": "Nuñez de Caceres", "error_medio_pct": 3.8,
         "banda_lo_pct": -6.0, "banda_hi_pct": 8.2},
        {"label": "CDP La Vega", "error_medio_pct": 17.0,
         "banda_lo_pct": -19.5, "banda_hi_pct": 31.9},
    ],
    "nota_motor": "El 84% de la incertidumbre de la venta viene del tráfico.",
}


def test_el_guard_de_banca_no_ve_nada_en_otra_forma_de_contexto():
    """Se fija el defecto, no solo la cura: si algún día `deterministic_unsupported`
    empezara a cubrir esta forma, este test avisa y la regla genérica podría revisarse."""
    inventado = ("El tráfico concentra el 61% de la incertidumbre y el error es de 2,3%, "
                 "frente al 44,8% sin modelo.")
    assert deterministic_unsupported(CONTEXTO_MARCA, inventado) == []


def test_la_regla_generica_si_caza_las_cifras_inventadas():
    inventado = ("El tráfico concentra el 61% de la incertidumbre y el error es de 2,3%, "
                 "frente al 44,8% sin modelo. El sesgo alcanza el 73% de las jornadas.")
    flags = deterministic_uncited_figures(CONTEXTO_MARCA, inventado)
    assert len(flags) == 4
    assert all(any(c in f for c in ("61", "2,3", "44,8", "73")) for f in flags)


def test_el_texto_fiel_no_produce_hallazgos():
    fiel = ("El tráfico concentra el 84% de la incertidumbre; el error medio de tráfico es "
            "7,4% frente al 12,9% de la vara, y el de cheque 3,6%. CDP La Vega opera con "
            "17,0% de error.")
    assert deterministic_uncited_figures(CONTEXTO_MARCA, fiel) == []


def test_la_cobertura_distingue_verificado_de_no_mirado():
    """`[]` con cobertura vacía es un modo de falla silencioso, distinto de «está limpio»."""
    cob = guard_coverage(CONTEXTO_MARCA)
    assert cob["cifras_del_contexto"] is True
    assert not cob["score"] and not cob["pares"]      # la forma de banca no está
    assert guard_coverage({})["cifras_del_contexto"] is False


def test_sin_numeros_en_el_contexto_no_inventa_verificacion():
    """Sin insumo no hay verificación, y fingirla sería el mismo modo de falla."""
    assert deterministic_uncited_figures({"nota": "sin cifras"}, "Creció un 40%.") == []


# ─────────────────────────────────────────────────────────────────────────────
# Las decisiones medidas
# ─────────────────────────────────────────────────────────────────────────────

def test_no_mira_puntos_porque_banca_los_deriva_legitimamente():
    """«3,77 puntos por encima de la mediana» es score − mediana, y es correcto.

    Con «puntos» dentro, esta regla marcaba el 30 % de los casos limpios del corpus de
    banca. La aritmética de esas derivaciones ya la verifican los chequeos que sí conocen
    la forma de banca; duplicarla acá solo agregaba ruido.
    """
    ctx = {"score_global": 86.42, "pares": {"entity_type": {"median_score": 82.65}}}
    assert deterministic_uncited_figures(ctx, "Queda 3,77 puntos sobre la mediana.") == []


def test_acepta_redondeo_y_truncacion_a_un_decimal():
    """El informe real escribió «5,4%» de un 5,47 del contexto.

    No es una cifra inventada, es otra convención de redondeo; marcarla costaría una
    regeneración por un decimal. Medido: aceptarla sube el escape de 11,3 % a 11,6 %.
    """
    ctx = {"brecha_pct": 5.47}
    assert deterministic_uncited_figures(ctx, "Una brecha de 5,4%.") == []   # truncado
    assert deterministic_uncited_figures(ctx, "Una brecha de 5,5%.") == []   # redondeado
    assert deterministic_uncited_figures(ctx, "Una brecha de 5,9%.")         # ninguna de las dos


def test_el_signo_no_importa_para_el_respaldo():
    """El contexto guarda −19,5 y el texto cita «19,5 %» como magnitud. Es la misma cifra."""
    ctx = {"banda_lo_pct": -19.5}
    assert deterministic_uncited_figures(ctx, "La banda baja llega a 19,5%.") == []


def test_lee_las_cifras_incrustadas_en_las_glosas():
    """El motor sirve prosa con números dentro y el modelo la cita con todo derecho."""
    ctx = {"nota_motor": "La cobertura real fue de 80,0% contra 80% nominal."}
    assert deterministic_uncited_figures(ctx, "La cobertura alcanzó 80,0%.") == []


def test_recorre_la_estructura_sin_conocerla():
    anidado = {"a": [{"b": {"c": [42.5]}}], "d": ("texto con 13,1%",)}
    figs = context_figures(anidado)
    assert 42.5 in figs and 13.1 in figs


def test_los_booleanos_no_son_cifras():
    """``True`` es 1 en Python. Sin este corte, el contexto respaldaría cualquier «1%»."""
    assert 1.0 not in context_figures({"available": True, "otro": False})


def test_nunca_lanza_ante_un_contexto_raro():
    class Raro:
        def __repr__(self):  # pragma: no cover — solo para que el walk lo ignore
            return "raro"

    assert deterministic_uncited_figures({"x": Raro()}, "Un 5% cualquiera.") is not None


# ─────────────────────────────────────────────────────────────────────────────
# El poder de detección, medido
# ─────────────────────────────────────────────────────────────────────────────

def test_el_poder_de_deteccion_sobre_un_contexto_denso():
    """Con 156 números —el contexto más denso del repo— una cifra inventada en 0-100 no
    debe escapar más de ~1 de cada 6 veces. Si esto se degrada, el guard se volvió
    decorativo y hay que saberlo antes de confiar en un `guard_flags=0`.
    """
    import random
    denso = {"locales": [
        {"e": round(3.0 + i * 0.47, 2), "lo": -round(5.0 + i * 0.31, 2),
         "hi": round(8.0 + i * 0.53, 2), "n": 70, "otro": round(i * 1.7, 2)}
        for i in range(30)
    ]}
    figs = context_figures(denso)
    assert len(figs) > 100, "el contexto de prueba tiene que ser denso de verdad"
    rng = random.Random(7)
    escapes = sum(
        1 for _ in range(4000)
        if not deterministic_uncited_figures(denso, f"Un {round(rng.uniform(0, 100), 1)}%.")
    )
    assert escapes / 4000 < 0.20


def test_la_truncacion_no_duplica_el_agujero():
    """Redondeo y truncación de un mismo valor coinciden salvo en la mitad de los casos."""
    figs = context_figures({"x": 5.47})
    assert round(5.47, 1) in figs
    assert math.floor(5.47 * 10) / 10 in figs
    assert len(figs) == 2
