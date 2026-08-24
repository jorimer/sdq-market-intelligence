"""El VEREDICTO de una comparación se computa; no lo une el modelo.

El contexto servía los dos hechos POR SEPARADO —"por debajo del promedio en 3.70 pp" en un
lado, "un valor MÁS ALTO es MEJOR" en otro— y dejaba que el modelo los UNIERA para saber si
la posición era fortaleza o debilidad. Esa unión es una derivación, que es exactamente la
operación que este módulo existe para evitar.

Huella del defecto en un informe REAL (Deep Dive de banca, 2026-03-31, §7): con patrimonio /
activos en 7.41% contra una mediana de grupo de 11.11% —segundo desde abajo entre 16, percentil
5— la sección escribió que «SUPERA en 3.70 puntos porcentuales al promedio de su grupo» y dos
líneas después que el margen de absorción es «estructuralmente MÁS DELGADO que el del par
típico». No es un desliz de una palabra: son DOS uniones distintas del mismo par de hechos, una
bien y otra al revés. Un error de tipeo no se comporta así.

El veredicto es INTERNO: orienta al modelo, y él redacta con su criterio. Por eso NO va dentro
de `lectura`, que el prompt manda a copiar literal — ahí terminaría impreso en el informe.
"""
import pytest

from shared.narrative.derived import comparaciones_vs_referencia


def _v(valor, ref, direccion):
    return comparaciones_vs_referencia(
        {"x": valor}, {"x": {"promedio de bancos múltiples": ref}},
        direcciones={"x": direccion})[0]


# ── El veredicto ───────────────────────────────────────────────────────

@pytest.mark.parametrize("valor,ref,direccion,esperado", [
    (7.4058, 11.11, "higher", "desfavorable"),   # EL CASO DE §7: patrimonio / activos
    (15.0, 11.11, "higher", "favorable"),
    (4.2, 2.05, "lower", "desfavorable"),        # morosidad por encima del grupo
    (49.38, 54.87, "lower", "favorable"),        # cost-to-income por debajo: es bueno
])
def test_la_posicion_se_une_con_el_sentido_de_la_escala(valor, ref, direccion, esperado):
    assert _v(valor, ref, direccion)["veredicto"] == esperado


def test_el_optimo_intermedio_NO_tiene_veredicto_contra_el_promedio():
    """`ltd`, `exposicion_re`, `migracion`: la vara es el óptimo, no el promedio. Estar por
    encima del grupo no es mejor ni peor — decirlo sería inventar una lectura."""
    f = _v(84.31, 82.88, "target")
    assert f["veredicto"] == "no_aplica"
    assert "óptimo" in f["veredicto_por_que"]


def test_sin_sentido_de_escala_declarado_se_dice_que_no_aplica():
    """Un campo ausente se lee como que nadie miró; el motivo se declara."""
    f = _v(7.4058, 11.11, None)
    assert f["veredicto"] == "no_aplica" and "no se declaró" in f["veredicto_por_que"]


def test_una_brecha_inmaterial_no_recibe_lado():
    assert _v(10.0, 10.02, "higher")["veredicto"] == "en línea"


# ── Que sea INTERNO ────────────────────────────────────────────────────

@pytest.mark.parametrize("direccion", ["higher", "lower", "target"])
def test_el_veredicto_NO_contamina_la_clausula_que_se_copia(direccion):
    """`lectura` es lo que el prompt manda copiar literal. Si el veredicto viviera ahí, la
    palabra 'desfavorable' saldría impresa en el informe del cliente."""
    f = _v(7.4058, 11.11, direccion)
    for palabra in ("favorable", "desfavorable", "no_aplica"):
        assert palabra not in f["lectura"], f["lectura"]


def test_el_veredicto_viaja_en_su_propio_campo():
    f = _v(7.4058, 11.11, "higher")
    assert {"veredicto", "veredicto_por_que"} <= set(f)


# ── El cableo de banca, de punta a punta ───────────────────────────────

def test_banca_sirve_el_veredicto_con_el_sentido_del_REGISTRO():
    """El sentido sale de `INDICATOR_META`, no de una lista paralela que se desincronice."""
    from modules.banking_score.reports.narrative import _comparaciones_resueltas

    ind = {k: {"raw": v, "score": 50.0, "available": True} for k, v in
           {"patrimonio_activos": 7.4058, "morosidad": 4.2, "ltd": 84.3129}.items()}
    bm = {"sector_averages": {"patrimonio_activos": 11.11, "npl": 2.05, "ltd": 82.88},
          "peer_groups": {}}
    por_ind = {c["indicador"]: c["veredicto"]
               for c in _comparaciones_resueltas(ind, bm, "banca_multiple")}
    assert por_ind["patrimonio_activos"] == "desfavorable", "el caso de §7"
    assert por_ind["morosidad"] == "desfavorable"
    assert por_ind["ltd"] == "no_aplica"


def test_el_prompt_prohibe_transcribir_el_veredicto():
    """Si la directiva no lo dice, el modelo escribe 'desfavorable' como etiqueta y el
    andamiaje interno termina en el documento de cliente."""
    from shared.narrative.cerebro import build_system

    system = build_system("banking", "inversionista", "detailed")
    assert "VEREDICTO DE CADA COMPARACIÓN" in system
    assert "NO lo transcribas" in system
