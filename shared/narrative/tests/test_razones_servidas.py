"""Las RAZONES se sirven computadas; el modelo no divide dos cifras por su cuenta.

`comparaciones_vs_referencia` ya servía la DIRECCIÓN y la BRECHA en puntos. Faltaba la
tercera forma de relacionar dos cifras —cuántas VECES una es la otra— y el modelo la seguía
derivando. Defecto real (Deep Dive de banca, 2026-03-31, §12):

    «una rentabilidad sobre activos (0.39%) que TRIPLICA el umbral de alerta respecto al
     promedio de bancos múltiples (1.61%)»

Las dos cifras eran correctas y estaban servidas. La razón es 0.24×, y la §10 del MISMO
informe lo decía bien: «una cuarta parte de la velocidad de sus pares». Ningún chequeo
determinista miraba razones —«triplica» no tiene dígitos que parear—, así que la única red
era el juez semántico, que corrió sobre ese texto y lo dejó pasar.

El caso del CRUCE DE CERO no es un caso residual sino el hallazgo más fuerte, y por eso no
se veta: se declara. Medido en el corte 2026-03 de producción, hay 24 entidades en pérdida
contra una mediana de grupo positiva.
"""
import pytest

from shared.narrative.derived import (PISO_DENOMINADOR, factores_hasta_umbral,
                                      razones_vs_referencia)
from shared.narrative.numeric_guard import deterministic_ratio_errors


def _una(valor, ref, **kw):
    return razones_vs_referencia({"x": valor}, {"x": {"promedio de bancos múltiples": ref}},
                                 **kw)[0]


# ── Las cinco clases de relación ───────────────────────────────────────

def test_ambos_positivos_sirven_razon_y_su_clausula():
    f = _una(0.3926, 1.61)   # el caso literal de §12
    assert f["relacion"] == "razon"
    assert f["razon_vs_referencia"] == 0.24
    assert "una cuarta parte" in f["lectura"]


def test_el_CRUCE_DE_CERO_no_se_oculta_sino_que_se_declara():
    """Caso real: JMMB con ROA −0.26 contra una mediana de +1.52. La razón daría −0.17×, que
    se lee como una diferencia menor cuando es un cambio de signo."""
    f = _una(-0.26, 1.52)
    assert f["relacion"] == "cruce_de_cero" and f["cruza_cero"] is True
    assert "razon_vs_referencia" not in f, "no debe publicarse una razón con signos opuestos"
    assert "SIGNO" in f["lectura"] and "1.78" in f["lectura"], f["lectura"]


def test_el_cruce_de_cero_NO_pierde_la_magnitud():
    """La gravedad la ordena la brecha, no la razón: Banco Activo (−13.76) está mucho peor que
    JMMB (−0.26) y la razón los invertía (−9.04× contra −0.17×)."""
    leve, grave = _una(-0.26, 1.52), _una(-13.76, 1.52)
    assert abs(grave["brecha"]) > abs(leve["brecha"])


def test_ambos_negativos_se_leen_en_clave_de_PERDIDA():
    f = _una(-3.0, -1.3)
    assert f["relacion"] == "razon"
    assert "pierde" in f["lectura"] and "2.31" in f["lectura"], f["lectura"]


def test_denominador_casi_cero_declara_el_motivo():
    f = _una(4.2, PISO_DENOMINADOR / 2)
    assert f["relacion"] == "no_procede" and "cerca de cero" in f["motivo"]


def test_optimo_intermedio_no_recibe_razon():
    """`ltd`, `exposicion_re`, `migracion`: estar al doble del promedio no es mejor ni peor."""
    f = _una(84.31, 82.88, direcciones={"x": "target"})
    assert f["relacion"] == "no_procede" and "óptimo intermedio" in f["motivo"]


# ── La cláusula se redacta para COPIAR ─────────────────────────────────

@pytest.mark.parametrize("razon,esperado", [
    (2.05, "el doble"), (3.0, "el triple"), (0.25, "una cuarta parte"), (0.5, "la mitad"),
])
def test_las_fracciones_familiares_se_nombran(razon, esperado):
    assert esperado in _una(razon * 2.0, 2.0)["lectura"]


def test_la_tolerancia_de_fraccion_es_RELATIVA():
    """Con margen absoluto, un 0.29 se redondeaba a «una cuarta parte» —16% de error en una
    frase que suena exacta—."""
    assert "una cuarta parte" not in _una(0.29 * 10, 10.0)["lectura"]
    assert "una cuarta parte" in _una(0.25 * 10, 10.0)["lectura"]


# ── El umbral es OTRA relación y viaja aparte ──────────────────────────

def test_el_umbral_no_se_mezcla_con_la_referencia():
    """Fundir «dónde deberías estar» con «dónde está el mercado» fue el error literal de §12."""
    (f,) = factores_hasta_umbral({"roa": 0.3926}, {"roa": 1.46}, que_es="umbral")
    assert f["factor_para_alcanzar_umbral"] == 3.72
    assert "promedio" not in f["lectura"], "el umbral no habla del mercado"


# ── El guard: la red por si la directiva no alcanza ────────────────────

_CTX = {"razones": razones_vs_referencia(
    {"roa": 0.3926, "morosidad": 4.2, "roe": -0.26},
    {"roa": {"promedio de bancos múltiples": 1.61},
     "morosidad": {"promedio de bancos múltiples": 2.05},
     "roe": {"promedio de bancos múltiples": 1.52}})}


def test_LA_FRASE_PUBLICADA_se_marca():
    frase = ("una rentabilidad sobre activos (0.39%) que triplica el umbral respecto al "
             "promedio de bancos múltiples (1.61%)")
    assert deterministic_ratio_errors(_CTX, frase)


def test_un_multiplo_sobre_un_par_que_cruza_cero_se_marca_sin_comparar_factores():
    assert deterministic_ratio_errors(
        _CTX, "el ROE de -0.26% es 3 veces el promedio de bancos múltiples (1.52%)")


@pytest.mark.parametrize("frase", [
    "La morosidad de 4.20% duplica el promedio de bancos múltiples (2.05%)",
    "con un ROA de 0.39% contra un promedio de bancos múltiples de 1.61%, rinde una cuarta parte",
])
def test_la_prosa_CORRECTA_no_se_marca(frase):
    assert deterministic_ratio_errors(_CTX, frase) == []


def test_sin_ATRIBUCION_el_guard_se_calla():
    """Contra "el promedio de bancos múltiples" se comparan TODOS los indicadores: la etiqueta
    sola no atribuye. Sin valores citados que identifiquen a uno, no se marca — un falso
    positivo acá VETA un informe correcto."""
    assert deterministic_ratio_errors(
        _CTX, "la cartera creció 3 veces más rápido que el promedio de bancos múltiples") == []


def test_el_chequeo_corre_desde_el_punto_de_entrada_unico():
    """Un guard que hay que acordarse de llamar es el que falta en la otra ruta. Además: el
    `return []` temprano de `deterministic_direction_errors` saltaba los chequeos hermanos
    cuando el contexto no traía indicadores en la forma que reconoce."""
    from shared.narrative.numeric_guard import deterministic_direction_errors

    solo_razones = {"razones": _CTX["razones"]}
    assert deterministic_direction_errors(
        solo_razones, "un ROA (0.39%) que triplica el promedio de bancos múltiples (1.61%)")


# ── La razón también se dice en PORCENTAJE ─────────────────────────────

def test_la_razon_se_sirve_TAMBIEN_como_porcentaje():
    """Un analista escribe indistintamente «1.32 veces» y «el 132% del promedio». El guard
    compara contra los números del contexto, y ahí solo estaba el 1.32: un Deep Dive REAL
    (Asociación Bonao, 2025-03-31) se vetó por un «132%» que era exactamente la razón
    servida — su apalancamiento, 26.84 contra una mediana de sistema de 20.33."""
    f = _una(26.8415, 20.33)
    assert f["razon_vs_referencia"] == 1.32
    assert f["razon_como_pct_del_referente"] == 132.0


def test_las_DOS_formas_pasan_el_guard():
    from shared.narrative.numeric_guard import deterministic_uncited_figures

    ctx = {"razones": razones_vs_referencia(
        {"leverage": 26.8415}, {"leverage": {"promedio del sistema": 20.33}})}
    for frase in ("es 1.32 veces el promedio del sistema",
                  "alcanza el 132% del promedio del sistema"):
        assert deterministic_uncited_figures(ctx, f"El apalancamiento {frase}.") == []


def test_un_porcentaje_INVENTADO_se_sigue_marcando():
    """La cura sirve el número, no afloja el guard: aceptar cualquier valor ×100 dejaría pasar
    un «500%» porque el contexto tiene un 5.0 en cualquier parte."""
    from shared.narrative.numeric_guard import deterministic_uncited_figures

    ctx = {"razones": razones_vs_referencia(
        {"leverage": 26.8415}, {"leverage": {"promedio del sistema": 20.33}})}
    assert deterministic_uncited_figures(
        ctx, "El apalancamiento alcanza el 180% del promedio del sistema.")


def test_el_cruce_de_cero_NO_recibe_porcentaje():
    """Donde no hay razón que publicar tampoco hay porcentaje: sería reintroducir por la
    ventana el número que la clase entera existe para no dar."""
    f = _una(-0.26, 1.52)
    assert "razon_como_pct_del_referente" not in f
