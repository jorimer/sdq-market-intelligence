"""Los caveats/titular del producto de pensiones se adaptan al estado REAL del ISA.

Con la solvencia incorporada (banda absoluta) el reporte NO debe declarar que faltan
estados financieros ni que las bandas están diferidas; sin ella, conserva el encuadre
relativo/parcial. Bloquea la regresión de la contradicción original (dato con banda +
texto que la niega).
"""
from modules.pension_intel.products import (
    _limitations_for,
    _named_headline_caveat,
    _solvency_incorporated,
)


def _rating(absolute: bool):
    return {
        "name": "AFP Popular", "overall_score": 61.9,
        "score_kind": "absolute" if absolute else "relative_partial",
        "band": "Adecuada" if absolute else None,
        "coverage": 1.0 if absolute else 0.65,
        "dimensions": [
            {"key": "solvencia", "present": absolute, "raw": 0.8435 if absolute else None,
             "score": 63.4 if absolute else None},
            {"key": "rentabilidad", "present": True, "raw": 7.69, "raw_real": 2.2, "score": 49.7},
        ],
    }


def test_solvency_incorporated_flag():
    assert _solvency_incorporated(_rating(True)) is True
    assert _solvency_incorporated(_rating(False)) is False
    assert _solvency_incorporated(None) is False
    assert _solvency_incorporated({"score_kind": "absolute", "band": None}) is False  # band req.


def test_limitations_absolute_state_does_not_claim_missing_statements():
    txt = _limitations_for(_rating(True))
    assert "banda absoluta" in txt.lower()
    assert "incorporada" in txt.lower() or "integra" in txt.lower()
    # The defining regression: must NOT say solvency will be added later / is unavailable.
    assert "se incorporará" not in txt
    assert "aún no está incorporada" not in txt


def test_limitations_partial_state_keeps_gap_language():
    txt = _limitations_for(_rating(False))
    assert "relativa y parcial" in txt.lower()
    assert "reserva" in txt.lower()


def test_headline_absolute_shows_band_not_relativo_parcial():
    headline, caveat = _named_headline_caveat({"rating": _rating(True), "sharpe": 1.79})
    assert "Adecuada" in headline
    assert "(relativo, parcial)" not in headline
    assert "Sharpe 1.79" in headline
    assert "integra la solvencia" in caveat
    assert "se incorporará" not in caveat


def test_headline_partial_keeps_relativo_parcial():
    headline, caveat = _named_headline_caveat({"rating": _rating(False)})
    assert "(relativo, parcial)" in headline
    assert "se incorporará" in caveat


def test_no_rating_returns_none():
    assert _named_headline_caveat({"rating": {}}) == (None, None)
