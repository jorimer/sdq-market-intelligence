"""Gate-E sectorial backtest: does the IAI in T predict employment growth in T+1?

Mirrors :mod:`modules.trade_intel.validation`. Reads the persisted IAI
(``SectorScore``) and ENCFT employment from the DB, aggregates the per-slug index
to the 10 ONE activity branches (the outcome's real resolution) weighted by sector
size, and correlates IAI_T with Δemployment_{T+1} (Spearman, bootstrap CI),
controlling for sector_growth_T to bound the serial-inertia circularity.
"""
