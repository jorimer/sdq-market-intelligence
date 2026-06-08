"""Tests for the SIB indicator matcher — accent-insensitive + exact mode.

The SIB names carry accents (Índice, Crédito); the old matcher was accent-
sensitive and silently failed to map morosidad/margen/etc., leaving them N/D.
"""
from modules.banking_score.external.sib_data_client import SIBDataClient, _norm

fv = SIBDataClient._find_value_in_records


def test_norm_strips_accents():
    assert _norm("Índice de Crédito") == "INDICE DE CREDITO"
    assert _norm("Margen de Intermediación Neto") == "MARGEN DE INTERMEDIACION NETO"


def test_accent_insensitive_substring_match():
    recs = [{"indicador": "Margen de Intermediación Neto", "valor": 7.8}]
    # accent-free keyword still matches the accented SIB name
    assert fv(recs, ["MARGEN DE INTERMEDIACION"]) == 7.8


def test_exact_avoids_near_duplicate_variant():
    recs = [
        {"indicador": "Índice de Morosidad mayor a 90 días (Capital)", "valor": 2.1},
        {"indicador": "Índice de Morosidad mayor a 90 días", "valor": 2.5},
    ]
    # exact match returns the plain index, not the "(Capital)" variant
    assert fv(recs, ["Indice de Morosidad mayor a 90 dias"], exact=True) == 2.5
    # substring would ambiguously match the first; exact disambiguates
    assert fv(recs, ["Indice de Morosidad mayor a 90 dias (Capital)"], exact=True) == 2.1
