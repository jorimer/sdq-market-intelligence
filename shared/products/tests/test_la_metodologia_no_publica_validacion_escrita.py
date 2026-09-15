"""La metodología de un informe de cliente no afirma nada sobre validación.

**El caso (2026-09-15).** El Deep Dive 2025 de Banco Múltiple Santa Cruz, enviado a un alto
funcionario del banco, cerraba su metodología con «Validación: Eje 1 en producción; metodología
determinista validada. (score de validación 1.00)». Las dos cosas estaban escritas a mano en
`BankingProduct.validation_state()`: el `1.0` es un número de gate declarado, no una medición,
y la frase afirma una validación cuyo veredicto vigente —el que computa la plataforma— dice
otra cosa (concluyente, pero sin ventaja sobre ordenar por tamaño).

La doctrina: ninguna cifra de validación se transcribe, y el veredicto vive en el reporte del
motor (`GET /api/v1/products/credenciales`), con su frescura. El dueño decidió que el PDF no
publique la línea: la validación se afirma en material comercial, desde la tabla computada,
no en cada informe con un texto que envejece.
"""
from shared.products.contract import ValidationState
from shared.products.report_sections import _methodology_md


class _Sig:
    sources = ("SIB", "SIMBAD", "BCRD")
    cadence = "trimestral"
    freshness_days = 3
    coverage = 1.0
    coverage_kind = ""
    detail = None


#: LITERAL de lo que declaraba banca y salió impreso en el PDF del banco.
_VAL_DE_BANCA = ValidationState(approved=True, score=1.0,
                                notes="Eje 1 en producción; metodología determinista validada.")


def test_ni_el_score_declarado_ni_la_nota_llegan_a_la_metodologia():
    md = _methodology_md(_Sig(), _VAL_DE_BANCA, as_of="2025-12-31")
    assert "Fuentes de dato" in md, "la fixture tiene que producir una metodología real"
    assert "score de validación" not in md
    assert "Validación" not in md
    assert "validada" not in md


def test_cualquier_producto_con_estado_de_validacion_tampoco_la_publica():
    """No es banca: la línea salía para TODO producto con `validation_state()`."""
    val = ValidationState(approved=False, score=0.4, notes="backtest parcial")
    md = _methodology_md(_Sig(), val, as_of=None)
    assert "Validación" not in md and "0.40" not in md
