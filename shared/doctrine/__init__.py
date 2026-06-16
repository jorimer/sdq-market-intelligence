"""Versioned house doctrine — the control document for every index.

Each axis has a ``{axis}.yaml`` here owning its weights, variable mapping,
risk-increasing flags and bands.  Code reads doctrine via :func:`load_doctrine`;
it never hardcodes weights.  A weight change is a doctrine PR, not a code edit.
"""
from shared.doctrine.loader import available_axes, load_doctrine, load_doctrine_raw

__all__ = ["load_doctrine", "load_doctrine_raw", "available_axes"]
