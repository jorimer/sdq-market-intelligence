"""Reusable explainable-index engine (one engine, many axes).

Every SDQMIP composite index (IRMP, IAI, SGPS, banking sub-scores, …) is built
here from an :class:`~shared.indices.config.IndexConfig`.  Modules must NOT
re-implement normalization/weighting/banding — they declare a config and call
:func:`~shared.indices.engine.run_index`.

Pipeline (deterministic, auditable, no black box):
    1. Regional min-max normalization per variable (inverted for risk-increasing).
    2. Each dimension = simple mean of its normalized variables (missing skipped).
    3. Overall = weighted sum of dimensions, clamped to [0, 100].
    4. Map to a qualitative band; emit a full per-variable breakdown.
"""
from shared.indices.config import Band, IndexConfig
from shared.indices.engine import MODEL_VERSION, run_index

__all__ = ["Band", "IndexConfig", "run_index", "MODEL_VERSION"]
