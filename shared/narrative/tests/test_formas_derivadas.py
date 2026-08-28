"""El guard entiende que una razón se dice de varias maneras — y solo en ranuras tipadas.

Caso real que lo motiva: un Deep Dive de Asociación Bonao al 2025-03-31 se vetó por
«risk_assessment: 132 %». El 132 % era exactamente la razón servida —apalancamiento 26,8415
contra la mediana del sistema 20,33 = 1,32— dicha como porcentaje del referente.

Estos tests fijan las DOS mitades del trato, porque una sola no sirve de nada:

- las formas equivalentes de una magnitud relacional pasan;
- una cifra inventada se sigue marcando, y en particular las coincidencias que una regla
  general (×100 contra CUALQUIER número del contexto) habría dejado colar.
"""
import pytest

from shared.narrative.numeric_guard import (
    CORRECTION_NOTICE, FORMAS_POR_CLAVE, deterministic_uncited_figures, formas_derivadas,
    valores_relacionales,
)


def _ctx_razon(valor=26.8415, referencia=20.33):
    """El contexto REAL del caso Bonao, tal como lo arma `razones_vs_referencia`."""
    from shared.narrative.derived import razones_vs_referencia
    return {
        "entity_name": "Asociación Bonao de Ahorros y Préstamos",
        "period": "2025-03-31",
        "razones": razones_vs_referencia(
            {"leverage": valor}, {"leverage": {"promedio del sistema": referencia}},
            direcciones={"leverage": "higher"}),
    }


# ── Las formas equivalentes ────────────────────────────────────────────

@pytest.mark.parametrize("frase", [
    # El «132 %» del caso original ya lo cubre `razon_como_pct_del_referente`, servido en
    # #947: este caso NO prueba el mecanismo nuevo, lo protege de una regresión. Verificado
    # apagando las formas derivadas — sigue pasando.
    "el apalancamiento se ubica en 132% del promedio del sistema",
    # Estas dos SÍ son del mecanismo nuevo: con las formas derivadas apagadas, fallan.
    "el apalancamiento es un 32% mayor que el promedio del sistema",
    "la entidad está al 76% del nivel que igualaría al promedio",
])
def test_las_formas_de_la_MISMA_razon_pasan(frase):
    assert deterministic_uncited_figures(_ctx_razon(), frase) == []


def test_la_razon_en_su_forma_servida_sigue_pasando():
    assert deterministic_uncited_figures(
        _ctx_razon(), "es 1,32 veces el promedio del sistema") == []


def test_formas_derivadas_conoce_la_unidad_de_cada_clave():
    """Un múltiplo se lleva a porcentaje; un porcentaje, a múltiplo. No al revés."""
    assert 132.0 in formas_derivadas("razon_vs_referencia", 1.32)
    assert 32.0 in formas_derivadas("razon_vs_referencia", 1.32)
    assert 1.32 in formas_derivadas("razon_como_pct_del_referente", 132.0)
    # Una clave desconocida no genera nada: la unidad no se adivina.
    assert formas_derivadas("brecha_pp", 3.5) == set()


def test_solo_se_recogen_las_claves_TIPADAS():
    """El valor del indicador y el de la referencia NO son magnitudes relacionales."""
    ctx = _ctx_razon()
    recogidos = {v for _, v in valores_relacionales(ctx)}
    assert 26.8415 not in recogidos, "el valor del indicador no admite forma derivada"
    assert 20.33 not in recogidos, "el valor de la referencia tampoco"
    assert 1.32 in recogidos


# ── Lo que se sigue marcando (los dientes) ─────────────────────────────

def test_un_porcentaje_INVENTADO_se_sigue_marcando():
    marcas = deterministic_uncited_figures(
        _ctx_razon(), "el apalancamiento se ubica en 512,7% del promedio del sistema")
    assert marcas and "512,7%" in marcas[0]


@pytest.mark.parametrize("inventada", ["150", "250", "1000"])
def test_las_coincidencias_que_una_regla_GENERAL_dejaria_colar(inventada):
    """×100 contra CUALQUIER número del contexto deja pasar estas tres.

    Medido sobre el contexto real de una sección de riesgo: un «150 %», un «250 %» y un
    «1000 %» calzaban con un 1,5, un 2,4999 y un 10,0 servidos que no son razón de nada. La
    regla por-clave no los admite porque esos valores no viven en una ranura relacional.
    """
    ctx = _ctx_razon()
    ctx["trayectoria"] = [{"periodo": "2024-12", "valor": 1.5},
                          {"periodo": "2025-03", "valor": 2.4999},
                          {"periodo": "2025-06", "valor": 10.0}]
    assert deterministic_uncited_figures(ctx, f"un {inventada}% del promedio")


def test_sin_ranura_relacional_el_guard_no_afloja():
    """Prueba negativa del mecanismo: sin `razones`, el 132 % vuelve a marcarse."""
    ctx = {"entity_name": "X", "indicadores": {"leverage": 26.8415},
           "referencia": {"promedio del sistema": 20.33}}
    assert deterministic_uncited_figures(ctx, "se ubica en 132% del promedio")


def test_el_cruce_de_cero_NO_recibe_forma_derivada():
    """Esa clase existe para NO dar un múltiplo; una forma derivada lo devolvería."""
    ctx = _ctx_razon(valor=-1.2, referencia=3.4)
    fila = ctx["razones"][0]
    assert fila["relacion"] == "cruce_de_cero"
    assert not any(k in fila for k in FORMAS_POR_CLAVE)


# ── El aviso de reparación (punto 1) ───────────────────────────────────

def test_el_aviso_pide_ANCLAR_y_no_ordena_borrar():
    """La versión vieja afirmaba «NO están en el contexto» y mandaba a no darlas.

    Era falso cuando la cifra era real, y la orden borraba una observación verdadera sin
    producir ningún error visible. El aviso tiene que ofrecer la rama de anclarla.
    """
    aviso = CORRECTION_NOTICE.format(bad="132%")
    assert "anclar" in aviso.lower() or "ANCLARLA" in aviso
    assert "DERIVADO" in aviso, "tiene que admitir que la cifra puede ser una derivación"
    assert "no borres" in aviso.lower()
    assert "NO están en el contexto" not in aviso, "esa afirmación era falsa"


def test_la_marca_dice_QUE_se_intento():
    """«no aparece» se lee como «el modelo inventó», y dos veces estuvo equivocado."""
    marcas = deterministic_uncited_figures(_ctx_razon(), "un 512,7% del promedio")
    assert "forma derivada" in marcas[0]


# ── El fragmento: cómo usó el modelo la cifra marcada ──────────────────

def test_el_fragmento_muestra_la_frase_de_la_cifra():
    from shared.narrative.numeric_guard import fragmento_alrededor

    texto = ("La entidad sostiene una posición adecuada. La eficiencia operativa se ubica "
             "en 38% de los ingresos recurrentes, por debajo de sus pares. El apalancamiento "
             "acompaña esa lectura y no compromete la solvencia declarada.")
    f = fragmento_alrededor(texto, "38%: no coincide con ningún valor servido")
    assert "38%" in f and "eficiencia operativa" in f
    assert "solvencia declarada" not in f, "recorta a una ventana, no guarda la sección entera"


def test_el_fragmento_no_corta_palabras_por_la_mitad():
    from shared.narrative.numeric_guard import fragmento_alrededor

    texto = "palabra " * 40 + "un 38% aquí " + "palabra " * 40
    f = fragmento_alrededor(texto, "38%: x").strip("…").strip()
    assert not f.startswith("abra") and not f.endswith("pala"), f"cortó una palabra: {f!r}"


def test_una_marca_del_JUEZ_que_no_calza_literal_no_devuelve_vacio():
    """El juez semántico reformula: media oración es más que nada."""
    from shared.narrative.numeric_guard import fragmento_alrededor

    assert fragmento_alrededor("Prosa cualquiera sin esa cifra.", "99,9% — reformulado")


def test_sin_texto_no_inventa_fragmento():
    from shared.narrative.numeric_guard import fragmento_alrededor

    assert fragmento_alrededor("", "38%: x") == ""


# ── El CONTENEDOR: cuando la clave es el sujeto y no la magnitud ───────

def _ctx_pesos():
    """Los pesos REALES de la rúbrica para una AAyP, tal como los sirve el contexto."""
    return {"entity_name": "Asociación Bonao de Ahorros y Préstamos",
            "pesos_sub_componentes": {"solidez": 0.38, "calidad": 0.34, "eficiencia": 0.13,
                                      "liquidez": 0.1, "diversificacion": 0.05}}


def test_el_peso_de_la_rubrica_dicho_en_PORCENTAJE_pasa():
    """El caso real, capturado con la frase que el modelo escribió.

    «La dimensión de mayor peso en el modelo (solidez de capital, ponderación 38%) sostiene la
    calificación con 82.32 puntos». El 0,38 estaba servido; el guard lo marcó como inventado
    porque los pesos viajan como `{componente: peso}` —la clave es el SUJETO, no la magnitud—
    y el detector solo miraba filas con una clave tipada.
    """
    frase = ("la dimensión de mayor peso en el modelo (solidez de capital, ponderación 38%) "
             "sostiene la calificación")
    assert deterministic_uncited_figures(_ctx_pesos(), frase) == []


@pytest.mark.parametrize("cita,ok", [("34", True), ("13", True), ("5", True), ("27", False)])
def test_cada_peso_servido_pasa_y_uno_que_no_existe_no(cita, ok):
    marcas = deterministic_uncited_figures(_ctx_pesos(), f"con una ponderación de {cita}%")
    assert (marcas == []) is ok


def test_sin_el_contenedor_declarado_el_guard_no_afloja():
    """Prueba negativa: el mecanismo es el nombre del contenedor, no «cualquier dict»."""
    ctx = {"entity_name": "X", "otros_coeficientes": {"solidez": 0.38}}
    assert deterministic_uncited_figures(ctx, "una ponderación de 38%")


# ── Las TASAS del modelo de propensión ─────────────────────────────────

#: Frase LITERAL del registro de marcas del 2026-08-27. No la redacté yo: la escribió el
#: modelo, y fue una de las DOS marcas con capa registrada tras la regla de dos capas — o sea,
#: el primer hueco que el instrumento nuevo encontró por su cuenta.
FRASE_DE_LA_TASA_BASE = (
    "El modelo de propensión ubica a la entidad en 1.96%, prácticamente en línea con la tasa "
    "base del sistema (1.82% sobre activos —dato derivado de la tasa base del modelo, "
    "0,01819, expresada como porcentaje—)")

_CTX_PROPENSION = {"propension_quiebra": {
    "tasa_base": 0.01819, "propension": 0.01964, "veces_la_base": 1.08}}


def test_la_tasa_base_dicha_en_PORCENTAJE_tiene_respaldo():
    """0,01819 → «1.82 %». El propio repo la formatea así en su resumen del modelo
    (`tasa base {m.tasa_base*100:.2f}%`): el modelo hizo lo mismo y el guard lo marcó."""
    assert deterministic_uncited_figures(_CTX_PROPENSION, FRASE_DE_LA_TASA_BASE) == []


def test_la_propension_de_la_ENTIDAD_también():
    """Las dos claves tienen la misma forma. Declarar solo una dejaría la mitad del hueco —
    y la mitad que queda siempre es la que aparece después."""
    assert deterministic_uncited_figures(
        _CTX_PROPENSION, "la propensión de la entidad se ubica en 1.96%") == []


def test_el_MÚLTIPLO_sigue_funcionando():
    """«1.08 veces la base» ya andaba: el arreglo no puede romperlo."""
    assert deterministic_uncited_figures(
        _CTX_PROPENSION, "1.08 veces la tasa base del sistema") == []


def test_una_cifra_REALMENTE_inventada_se_sigue_marcando():
    """Declarar un contenedor no es aflojar el guard: es darle el dato que le faltaba."""
    assert deterministic_uncited_figures(
        _CTX_PROPENSION, "la morosidad cerró el año en 7.77%") != []
