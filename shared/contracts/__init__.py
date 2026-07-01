"""Cross-cutting contracts — structured objects passed between axes.

A *contract* is a shared, versioned data shape that one axis produces and another
consumes, so the consumer never re-derives the producer's domain by hand. Living
in ``shared/`` (not in either module) keeps both sides free of cross-module
imports — they depend on the contract type, not on each other.
"""
from shared.contracts.macro_sector import (
    APP_SETTING_KEY,
    MacroFactor,
    MacroSectorContract,
    load_macro_contract,
    sector_macro_exposure,
)

__all__ = ["APP_SETTING_KEY", "MacroFactor", "MacroSectorContract",
           "load_macro_contract", "sector_macro_exposure"]
