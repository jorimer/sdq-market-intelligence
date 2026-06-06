"""Compatibility shim — SIB client now lives in ``shared/data`` (Fase 0).

Kept so existing imports (`modules.banking_score.external.sib_client`) keep
working.  New code should import from ``shared.data.sib_client``.
"""
from shared.data.sib_client import (  # noqa: F401
    CACHE_TTL,
    DEFAULT_BENCHMARKS,
    SuperintendenciaBancosClient,
    sib_client,
)

__all__ = [
    "SuperintendenciaBancosClient",
    "sib_client",
    "DEFAULT_BENCHMARKS",
    "CACHE_TTL",
]
