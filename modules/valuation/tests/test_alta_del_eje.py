"""El alta del eje `valuation` — y lo que tiene que seguir siendo cierto mientras no haya motor.

**La confusión que este eje existe para no cometer.** `banking_score` responde «qué tan sana
está» y este responde «cuánto vale». Son preguntas distintas, y **ninguna salida del score se
convierte en un valor**: una entidad puede estar sólida y destruir valor, y una rentable puede
valer menos que su libro. Si alguien alguna vez usa el score como proxy de precio, el error no
va a fallar — va a salir firmado.

**Está dado de alta y NO puede entregar, a propósito.** `has_engine()` devuelve False hasta que
existan el costo de capital y el Excess Return, así que ningún nivel alcanza su umbral y nada
se activa. El alta y la capacidad de entregar son dos cosas; confundirlas es cómo se publica
una vidriera vacía.

**La muestra usa una entidad FICTICIA.** El framework exige que todo producto del catálogo se
pueda mostrar, pero enseñar una valuación de un banco real que todavía no podemos computar
sería fabricar una cifra financiera sobre una empresa que existe — y eso no se arregla con una
marca de agua.
"""
import pytest

from shared.products import ProductTier
from shared.products.registry import PRODUCT_CATALOG, get_product, is_implemented

SECTOR = "valuation"


@pytest.fixture(scope="module", autouse=True)
def _registrado():
    import app.main  # noqa: F401 — registra los productos


def test_el_eje_esta_en_el_catalogo():
    assert any(e.sector_key == SECTOR for e in PRODUCT_CATALOG)
    assert is_implemented(SECTOR)


def test_NO_tiene_motor_y_lo_declara():
    """Sin esto, un eje vacío se vería igual que uno operativo con datos faltantes."""
    p = get_product(SECTOR)
    assert p.has_engine() is False
    assert p.validation_state().approved is False
    assert "motor" in p.data_signals().detail.lower()


def test_pedirle_un_snapshot_falla_con_el_motivo_escrito():
    """No devuelve un esqueleto con ceros: un motor sin su entrada no falla, DESAPARECE, y
    evaluar contra un diccionario vacío produce prosa sobre una entidad que nadie midió."""
    with pytest.raises(ValueError, match="motor de valuación"):
        get_product(SECTOR).snapshot(ProductTier.insight, "", scope="x")


def test_la_muestra_usa_una_entidad_FICTICIA_y_lo_dice():
    from modules.valuation.products import _ENTIDAD_FICTICIA

    assert "ilustrativa" in _ENTIDAD_FICTICIA.lower() or "ejemplo" in _ENTIDAD_FICTICIA.lower()
    snap = get_product(SECTOR).sample_snapshot(ProductTier.insight)
    assert snap.entity_name == _ENTIDAD_FICTICIA
    assert snap.payload.get("es_ilustrativo") is True


def test_el_pulse_de_la_muestra_no_nombra_entidad():
    """Doctrina no negociable del framework: Pulse jamás nombra entidades."""
    assert get_product(SECTOR).sample_snapshot(ProductTier.pulse).entity_name is None


def test_la_muestra_ensena_el_caso_INCOMODO():
    """El valor que cambia de signo dentro del rango de Ke ES el hallazgo del eje. Una
    muestra que solo enseña casos limpios vende un producto que no existe."""
    from modules.valuation.products import _SAMPLE_PAYLOAD

    alto, bajo = _SAMPLE_PAYLOAD["spread_pp"][0], _SAMPLE_PAYLOAD["spread_pp"][-1]
    assert alto * bajo < 0, "la muestra no enseña un spread que cruce el cero"
    assert _SAMPLE_PAYLOAD["cambia_de_signo"] is True


def test_la_muestra_NO_entra_como_evidencia():
    """Una muestra al lado de dato real en el ledger de una investigación sería una cifra
    ficticia con la misma jerarquía que una medida."""
    from shared.research.data_pull import _valuation_summary
    from modules.valuation.products import _SAMPLE_PAYLOAD

    assert _valuation_summary("x", _SAMPLE_PAYLOAD, "2025-12-31", "s") == []


def test_una_valuacion_real_SI_emite_evidencia_y_abre_por_el_spread():
    """El contraejemplo: sin él, un summarizer que devolviera siempre `[]` pasaría el test
    de arriba. Y el orden importa — el spread es la lectura, el valor es la consecuencia."""
    from shared.research.data_pull import _valuation_summary

    real = {"spread_pp": [0.8, -1.7], "valor_rango": [1.0e9, 1.2e9]}
    ev = _valuation_summary("x", real, "2025-12-31", "s")
    assert len(ev) == 2
    assert ev[0].variable == "spread_roe_ke", "la evidencia no abre por el spread"
    assert "CAMBIA" in ev[0].text, "no declara que el signo cruza dentro del rango"


def test_declara_su_doctrina_y_sus_audiencias():
    from shared.narrative.cerebro import AUDIENCE_FRAMES, AXIS_DOCTRINE

    assert SECTOR in AXIS_DOCTRINE
    doctrina = AXIS_DOCTRINE[SECTOR]
    # Las dos afirmaciones que el eje no puede perder.
    assert "no es un proxy de precio" in doctrina.lower() or "NO es un proxy" in doctrina
    assert "RANGO" in doctrina
    assert AUDIENCE_FRAMES.get(SECTOR), "sin audiencias declaradas la primera no puede ser el default"


@pytest.mark.parametrize("pregunta", [
    "¿Cuál es el score de solidez de Banreservas?",
    "¿Qué tan sano está el sistema bancario?",
    "¿Cómo cerró la inflación el mes pasado?",
])
def test_no_invade_las_preguntas_de_otros_ejes(pregunta):
    from shared.research.resolve import detect_axes

    assert SECTOR not in detect_axes(pregunta)


def test_pero_si_atiende_las_de_valor():
    from shared.research.resolve import detect_axes

    for q in ("¿Cuánto vale Banreservas?", "¿Qué múltiplo P/B tiene el sistema?"):
        assert SECTOR in detect_axes(q), f"no atendió «{q}»"
