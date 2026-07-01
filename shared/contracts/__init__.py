"""Cross-cutting contracts — structured objects passed between axes.

A *contract* is a shared, versioned data shape that one axis produces and another
consumes, so the consumer never re-derives the producer's domain by hand. Living
in ``shared/`` (not in either module) keeps both sides free of cross-module
imports — they depend on the contract type, not on each other.
"""
from shared.contracts.macro_sector import (
    APP_SETTING_KEY,
    INFLATION_SERIES_CODE,
    INFLATION_SERIES_KEY,
    TPM_SERIES_CODE,
    TPM_SERIES_KEY,
    MacroFactor,
    MacroSectorContract,
    load_inflation_series,
    load_macro_contract,
    load_tpm_series,
    sector_macro_exposure,
)

__all__ = ["APP_SETTING_KEY", "INFLATION_SERIES_CODE", "INFLATION_SERIES_KEY",
           "TPM_SERIES_CODE", "TPM_SERIES_KEY", "MacroFactor", "MacroSectorContract",
           "load_inflation_series", "load_macro_contract", "load_tpm_series",
           "sector_macro_exposure"]
