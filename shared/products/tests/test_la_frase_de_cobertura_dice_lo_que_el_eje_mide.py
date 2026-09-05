"""La frase de cobertura afirmaba «dato real medido» en un informe de PRONÓSTICO.

El informe de proyecciones del 2026-09-05 publicó esto en §8, con cuatro líneas de distancia
entre las dos frases, y las dos COMPUTADAS:

    Cobertura: 100% del índice se construye sobre dato real medido en la fuente.
    Procedencia por variable: 0% del peso de este índice se sostiene en dato real con fuente
    citable; … pib_real · 2026-Q3 no tiene dato en este período y se reporta como brecha.

Se contradicen, y en un eje de pronóstico la primera es falsa por construcción: el docstring
del propio producto dice que «acá el índice del eje **ES** la proyección». Una proyección no
es dato real medido en la fuente.

**Eran dos defectos.**

1. El producto contestaba otra pregunta. `coverage=1.0 if vig else 0.0` responde «¿hay alguna
   proyección vigente?»; `DataHealth.coverage` declara responder «¿qué fracción del peso de mi
   índice está anclada a dato real?». Estado medido en producción: UNA proyección vigente que
   **no pasa el gate** de admisibilidad, y aun así `cobertura=1.00`.

2. **La frase de metodología ignoraba `coverage_kind`.** El mecanismo ya existía —
   `provenance.coverage_sentence()` rutea entre la frase de índice y la de instrumento — y el
   comentario que lo justifica dice que la frase de índice en el eje de leyes es «sencillamente
   falsa» y que «salía en la Metodología del informe». El arreglo se hizo en `provenance.py` y
   **no** en `report_sections._methodology_md`, así que el eje de leyes seguía publicando
   «47% del índice se construye sobre dato real medido en la fuente» — la frase exacta que el
   repositorio ya había declarado falsa para él. Familia «un guard existe en un motor y falta
   en el otro».

Lo que este archivo fija: **la frase de cobertura habla en los términos de lo que ESE eje
mide, en TODAS sus superficies**, y ningún `coverage_kind` puede caer al default en silencio.
"""
import pytest

from shared.products.contract import DataHealth
from shared.products.report_sections import _methodology_md
from shared.registry.signals import COVERAGE_INDEX, COVERAGE_INSTRUMENT, COVERAGE_KINDS


def _linea_de_cobertura(dh: DataHealth) -> str:
    md = _methodology_md(dh, None, as_of="2026-09-05")
    lineas = [x for x in md.split("\n\n") if x.startswith("**Cobertura")]
    assert lineas, f"la metodología no trae línea de cobertura:\n{md}"
    return lineas[0]


def test_un_eje_de_INSTRUMENTO_no_dice_del_indice_en_la_metodologia():
    """El eje de leyes no arma un índice: mide cuántas metas de la ley tienen dato.

    El repositorio ya lo había decidido para la frase de procedencia y la de metodología
    quedó atrás. Este test es el que impide que vuelvan a separarse.
    """
    linea = _linea_de_cobertura(
        DataHealth(coverage=0.47, coverage_kind=COVERAGE_INSTRUMENT, cadence="annual"))
    assert "del índice" not in linea, (
        f"el eje de instrumento publica la frase de ÍNDICE en su metodología: {linea!r}")
    assert "dato real medido" not in linea, linea
    assert "47" in linea


def test_un_eje_de_PROYECCION_no_dice_dato_real_medido():
    """El índice de este eje ES la proyección; llamarla «dato real medido» es falso."""
    from shared.registry.signals import COVERAGE_PROJECTION

    linea = _linea_de_cobertura(
        DataHealth(coverage=0.5, coverage_kind=COVERAGE_PROJECTION, cadence="quarterly"))
    assert "dato real medido en la fuente" not in linea, (
        f"un eje de pronóstico publica «dato real medido»: {linea!r}")
    assert "50" in linea


def test_un_eje_de_INDICE_conserva_su_frase():
    """El arreglo no puede cambiarle la frase a los ejes que sí arman un índice de dato real."""
    linea = _linea_de_cobertura(DataHealth(coverage=0.92, coverage_kind=COVERAGE_INDEX))
    assert "del índice se construye sobre dato real medido en la fuente" in linea
    assert "92" in linea


def test_un_eje_SIN_coverage_kind_se_comporta_como_indice():
    """El default no cambia: los ejes que no declaran nada siguen leyéndose igual."""
    assert _linea_de_cobertura(DataHealth(coverage=0.92)) == \
        _linea_de_cobertura(DataHealth(coverage=0.92, coverage_kind=COVERAGE_INDEX))


@pytest.mark.parametrize("kind", COVERAGE_KINDS)
def test_TODO_coverage_kind_tiene_frase_en_las_DOS_superficies(kind):
    """Agregar una semántica sin su frase no puede heredar la de índice en silencio.

    Es el modo de falla que produjo el defecto: el vocabulario creció, una superficie
    aprendió a rutear y la otra se quedó con el literal cableado. Un default silencioso
    convierte «me falta una frase» en «publico una frase falsa».
    """
    from shared.products.report_sections import FRASE_COBERTURA_METODOLOGIA
    from shared.registry.provenance import FRASES_COBERTURA_PROCEDENCIA

    assert kind in FRASE_COBERTURA_METODOLOGIA, (
        f"{kind!r} no tiene frase de METODOLOGÍA y caería en la de índice")
    assert kind in FRASES_COBERTURA_PROCEDENCIA, (
        f"{kind!r} no tiene frase de PROCEDENCIA y caería en la de índice")


def test_el_vocabulario_de_cobertura_NO_esta_vacio():
    """Un `parametrize` vacío sale SKIPPED, no FAILED: el barrido lleva su testigo."""
    assert len(COVERAGE_KINDS) >= 3, COVERAGE_KINDS


# ── las dos frases hablan del MISMO producto: no pueden dar números distintos ────────

def test_metodologia_y_procedencia_dan_el_MISMO_numero(monkeypatch):
    """Es el defecto original en su forma general: dos cifras de cobertura en una página.

    El informe publicó «Cobertura: 100%» y «Procedencia por variable: 0%» a cuatro líneas de
    distancia, las dos computadas. Arreglar solo la redacción deja el mismo defecto más
    chico: dos números bajo la misma palabra. Las dos frases describen el mismo producto y
    tienen que salir del mismo cómputo.
    """
    import app.main  # noqa: F401
    from modules.macro_monitor import products_forecast as pf
    from shared.registry.provenance import coverage_sentence
    from shared.registry.signals import AxisRegistry, ProjectionMeta

    flaca = ProjectionMeta(
        model_id="m.v1", target_series="pib_real", horizon="2027-Q1", as_of="2026-09-01",
        revision=0, point=3.0, intervals=((0.80, 2.0, 4.0),), backtest_id="b",
        oos_error=0.5, error_metric="rmse", n_oos=2, n_oos_overlapping=False)
    monkeypatch.setattr(pf.MacroForecastProduct, "_vigentes", lambda self: [flaca])
    monkeypatch.setattr(pf.MacroForecastProduct, "_determinadas", lambda self: 1)
    monkeypatch.setattr(pf.MacroForecastProduct, "_puntuados", lambda self: [])
    monkeypatch.setattr(pf, "_seguro",
                        lambda db, fn, defecto: {"pib_real": flaca}
                        if defecto == {} else defecto)

    prod = pf.MacroForecastProduct(db=object())
    raw = prod.variable_signals()
    eje = AxisRegistry(sector_key="macro_forecast", display_name="x", source="y",
                       implemented=True, signals=tuple(raw["signals"]),
                       coverage_kind=raw.get("coverage_kind") or COVERAGE_INDEX)

    del_metodo = _linea_de_cobertura(prod.data_signals())
    de_procedencia = coverage_sentence(eje)
    assert "50%" in del_metodo and "50%" in de_procedencia, (
        f"las dos frases del mismo informe dan números distintos:\n"
        f"  metodología: {del_metodo}\n  procedencia: {de_procedencia}")


def test_la_cifra_DETERMINADA_existe_en_el_registro(monkeypatch):
    """Si no viaja al registro, la procedencia no la ve y las dos cifras se separan de nuevo."""
    import app.main  # noqa: F401
    from modules.macro_monitor import products_forecast as pf
    from shared.registry.signals import REAL

    monkeypatch.setattr(pf.MacroForecastProduct, "_determinadas", lambda self: 1)
    monkeypatch.setattr(pf, "_seguro", lambda db, fn, defecto: defecto)
    señales = pf.MacroForecastProduct(db=object()).variable_signals()["signals"]
    reales = [s for s in señales if s.state == REAL]
    assert len(reales) == 1, (
        "la cifra determinada —una identidad aritmética sobre dato publicado— no llega al "
        f"registro: señales={[(s.key, s.state) for s in señales]}")


def test_una_proyeccion_ADMISIBLE_cuenta_en_la_frase_de_procedencia():
    """El caso que separa `coverage_real` de `coverage_anclada`, y sin el cual el guard es ciego.

    Con una proyección que SÍ pasa el gate, `coverage_real` es 0 —una proyección nunca es
    REAL, ni en este eje— y `coverage_anclada` es 1. Si la frase leyera la primera diría 0%
    de un eje cuyo único pronóstico ancla perfectamente. Lo detectó una prueba de rotura: el
    test anterior usaba un caso donde las dos coberturas coinciden y no probaba nada.
    """
    from shared.registry.provenance import coverage_sentence
    from shared.registry.signals import (
        AxisRegistry, COVERAGE_PROJECTION, PROJECTED, VariableSignal,
    )

    eje = AxisRegistry(
        sector_key="macro_forecast", display_name="x", source="y", implemented=True,
        coverage_kind=COVERAGE_PROJECTION,
        signals=(VariableSignal(key="p", label="pib_real · 2027-Q1", state=PROJECTED,
                                weight=1.0, source="bvar"),))
    assert eje.coverage_real == 0.0, "una proyección no es dato real, ni en este eje"
    assert eje.coverage_anclada == pytest.approx(1.0)
    assert "100%" in coverage_sentence(eje), (
        f"la frase lee la cobertura equivocada: {coverage_sentence(eje)!r}")
