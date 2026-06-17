"""Cross-cutting contracts — structured objects passed between axes.

A *contract* is a shared, versioned data shape that one axis produces and another
consumes, so the consumer never re-derives the producer's domain by hand. Living
in ``shared/`` (not in either module) keeps both sides free of cross-module
imports — they depend on the contract type, not on each other.
"""
from shared.contracts.macro_sector import MacroFactor, MacroSectorContract

__all__ = ["MacroFactor", "MacroSectorContract"]
