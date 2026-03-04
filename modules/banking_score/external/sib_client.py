"""Superintendencia de Bancos (SIB) client with 3-level fallback.

Fallback order:  in-memory cache (24 h TTL) → local JSON file → hardcoded defaults.
Extracted from financial-analysis-agent/backend/app/external/sb_api_client.py.
"""
import json
import logging
import os
import time
from typing import Dict, List, Optional

from shared.config.settings import settings

logger = logging.getLogger(__name__)

# ── Hardcoded defaults (Level 3 fallback) ────────────────────────

DEFAULT_BENCHMARKS: Dict = {
    "sector_averages": {
        "car": 16.5,
        "npl": 1.8,
        "roa": 2.1,
        "roe": 18.5,
        "nim": 5.8,
        "cost_to_income": 52.0,
        "liquidity_ratio": 28.5,
        "leverage_ratio": 11.2,
        "coverage_ratio": 185.0,
        "ltd": 78.0,
    },
    "peer_groups": {
        "large_banks": {
            "members": ["BPD", "BHD León", "Popular", "Reservas"],
            "car_avg": 15.8,
            "npl_avg": 1.5,
            "roa_avg": 2.3,
            "roe_avg": 20.1,
            "cost_to_income_avg": 48.0,
        },
        "medium_banks": {
            "members": ["Scotiabank", "Santa Cruz", "Caribe", "Promerica"],
            "car_avg": 17.2,
            "npl_avg": 2.1,
            "roa_avg": 1.8,
            "roe_avg": 15.5,
            "cost_to_income_avg": 55.0,
        },
    },
    "regulatory_limits": {
        "car_minimum": 10.0,
        "car_required_basel_iii": 10.5,
        "npl_warning": 3.0,
        "npl_critical": 5.0,
        "liquidity_ratio_minimum": 15.0,
        "leverage_ratio_maximum": 20.0,
    },
}

CACHE_TTL = 86_400  # 24 hours


class SuperintendenciaBancosClient:
    """Read-only client for SIB sector benchmarks with offline fallback."""

    def __init__(self):
        self._cache: Dict = {}
        self._cache_ts: float = 0.0
        self._local_path = os.path.join(
            os.path.dirname(settings.MODELS_DIR), "sib_benchmarks.json"
        )

    # ── Core data access ──────────────────────────────────────────

    def get_sector_benchmarks(self) -> Dict:
        """Return sector benchmarks using 3-level fallback."""
        # Level 1: In-memory cache
        if self._cache and (time.time() - self._cache_ts) < CACHE_TTL:
            return self._cache

        # Level 2: Local JSON file
        if os.path.exists(self._local_path):
            try:
                with open(self._local_path) as f:
                    data = json.load(f)
                self._cache = data
                self._cache_ts = time.time()
                logger.info("SIB benchmarks loaded from local JSON")
                return data
            except Exception as e:
                logger.warning("Failed to load local SIB data: %s", e)

        # Level 3: Hardcoded defaults
        logger.info("Using hardcoded SIB benchmarks")
        self._cache = DEFAULT_BENCHMARKS
        self._cache_ts = time.time()
        return DEFAULT_BENCHMARKS

    # ── Peer comparison ───────────────────────────────────────────

    def get_peer_comparison(
        self, bank_name: str, metrics: Dict[str, float],
    ) -> Dict:
        """Compare a bank's metrics against sector averages and its peer group."""
        benchmarks = self.get_sector_benchmarks()
        peer_groups = benchmarks.get("peer_groups", {})

        # Identify peer group
        bank_group: Optional[str] = None
        for group_name, group_data in peer_groups.items():
            if bank_name in group_data.get("members", []):
                bank_group = group_name
                break

        sector = benchmarks.get("sector_averages", {})
        comparison: Dict[str, Dict] = {}
        for metric, value in metrics.items():
            sector_val = sector.get(metric)
            if sector_val is not None:
                diff = value - sector_val
                comparison[metric] = {
                    "value": value,
                    "sector_avg": sector_val,
                    "difference": round(diff, 2),
                    "relative_pct": (
                        round((diff / sector_val) * 100, 2)
                        if sector_val else 0
                    ),
                }

        return {
            "bank": bank_name,
            "peer_group": bank_group,
            "comparison": comparison,
        }

    # ── Regulatory compliance ─────────────────────────────────────

    def validate_regulatory_compliance(
        self, metrics: Dict[str, float],
    ) -> Dict:
        """Check metrics against SIB regulatory limits.

        Returns dict with ``compliant`` bool, ``violations``, and ``warnings``.
        """
        benchmarks = self.get_sector_benchmarks()
        limits = benchmarks.get("regulatory_limits", {})

        violations: List[Dict] = []
        warnings: List[Dict] = []

        # CAR
        car = metrics.get("car", metrics.get("solvencia"))
        if car is not None:
            if car < limits.get("car_minimum", 10.0):
                violations.append({
                    "metric": "CAR",
                    "value": car,
                    "limit": limits["car_minimum"],
                    "severity": "critical",
                })
            elif car < limits.get("car_required_basel_iii", 10.5):
                warnings.append({
                    "metric": "CAR",
                    "value": car,
                    "limit": limits["car_required_basel_iii"],
                    "severity": "warning",
                })

        # NPL
        npl = metrics.get("npl", metrics.get("morosidad"))
        if npl is not None:
            if npl > limits.get("npl_critical", 5.0):
                violations.append({
                    "metric": "NPL",
                    "value": npl,
                    "limit": limits["npl_critical"],
                    "severity": "critical",
                })
            elif npl > limits.get("npl_warning", 3.0):
                warnings.append({
                    "metric": "NPL",
                    "value": npl,
                    "limit": limits["npl_warning"],
                    "severity": "warning",
                })

        # Liquidity
        liq = metrics.get("liquidity_ratio", metrics.get("liquidez_inmediata"))
        if liq is not None and liq < limits.get("liquidity_ratio_minimum", 15.0):
            violations.append({
                "metric": "Liquidity",
                "value": liq,
                "limit": limits["liquidity_ratio_minimum"],
                "severity": "critical",
            })

        # Leverage
        lev = metrics.get("leverage_ratio", metrics.get("leverage"))
        if lev is not None and lev > limits.get("leverage_ratio_maximum", 20.0):
            warnings.append({
                "metric": "Leverage",
                "value": lev,
                "limit": limits["leverage_ratio_maximum"],
                "severity": "warning",
            })

        return {
            "compliant": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
        }

    # ── Sector comparison (indicator-level) ───────────────────────

    def compare_to_sector(
        self, indicator_scores: Dict[str, float],
    ) -> Dict[str, Dict]:
        """Compare individual indicator values against sector benchmarks.

        Maps scoring-engine indicator names to SIB benchmark keys.
        """
        benchmarks = self.get_sector_benchmarks()
        sector = benchmarks.get("sector_averages", {})

        # Indicator name → sector benchmark key
        mapping = {
            "solvencia": "car",
            "morosidad": "npl",
            "roa": "roa",
            "roe": "roe",
            "margen_financiero": "nim",
            "cost_to_income": "cost_to_income",
            "liquidez_inmediata": "liquidity_ratio",
            "leverage": "leverage_ratio",
            "cobertura_provisiones": "coverage_ratio",
            "ltd": "ltd",
        }

        comparisons: Dict[str, Dict] = {}
        for indicator, sector_key in mapping.items():
            if indicator in indicator_scores and sector_key in sector:
                value = indicator_scores[indicator]
                sector_val = sector[sector_key]
                comparisons[indicator] = {
                    "score": value,
                    "sector_benchmark": sector_val,
                    "vs_sector": round(value - sector_val, 2),
                }

        return comparisons


# Singleton
sib_client = SuperintendenciaBancosClient()
