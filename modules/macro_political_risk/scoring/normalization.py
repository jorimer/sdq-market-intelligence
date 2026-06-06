"""IRMP normalization — thin re-export of the shared index normalizer.

The implementation now lives in ``shared/indices/normalization.py`` (one
normalizer for every axis).  Kept here so existing imports keep working.
"""
from shared.indices.normalization import normalize_value, normalize_variable

__all__ = ["normalize_value", "normalize_variable"]
