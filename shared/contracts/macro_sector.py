"""Macro→sectorial contract — the structured macro context a sector report consumes.

Produced by Eje 2 (``macro_monitor``) from real BCRD series; consumed by the
§2 "Contexto macro" of the sectorial report (Eje 3) so it reads the macro
environment instead of re-deriving it by hand (plan maestro §3, diagnóstico §3-4
punto 5).

Each :class:`MacroFactor` is one macro reading turned into a sector-facing
signal: its current value, a *direction* (favorable / adverso / neutral for the
broad economy), a *magnitude*, and which sectors/agents it most affects. The
mapping (which series, the thresholds, the impacted sectors) is house doctrine
(`shared/doctrine/macro_sector.yaml`), never hardcoded.

Pure data types — no I/O, no domain logic. ``None``/``"n/d"`` means "not
available", never a fabricated reading.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# AppSetting key under which macro_monitor persists the latest contract, so
# cross-module consumers (sector_intel) read it without importing the producer.
APP_SETTING_KEY = "macro_sector_contract"


def load_macro_contract(db) -> Dict[str, Any]:
    """Read the latest macro→sectorial contract from the shared AppSetting
    (written by ``macro_monitor``). Empty dict if none yet.

    Centraliza el patrón de lectura para que cualquier consumidor (sector_intel,
    banking) lea el contrato SIN importar el módulo productor — depende solo de
    este contrato compartido. Nunca fabrica: sin contrato → ``{}`` (el consumidor
    degrada declaradamente).
    """
    import json

    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == APP_SETTING_KEY).first()
    if row is None or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return {}

# Allowed direction / magnitude values (kept as plain strings for JSON transport).
FAVORABLE = "favorable"
ADVERSO = "adverso"
NEUTRAL = "neutral"
ND = "n/d"


@dataclass(frozen=True)
class MacroFactor:
    """One macro reading mapped to its sector impact."""

    key: str
    label: str
    value: Optional[float]
    unit: Optional[str]
    direction: str                     # favorable | adverso | neutral | n/d
    magnitude: str                     # alto | moderado | bajo | n/d
    reading: str                       # short human phrase ("5.35%, sobre meta")
    impacted_sectors: List[Dict[str, str]] = field(default_factory=list)  # [{slug,name}]
    impacted_agents: List[str] = field(default_factory=list)
    trend: Optional[str] = None        # momentum trend, when available
    series_code: Optional[str] = None
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "direction": self.direction,
            "magnitude": self.magnitude,
            "reading": self.reading,
            "impacted_sectors": self.impacted_sectors,
            "impacted_agents": self.impacted_agents,
            "trend": self.trend,
            "series_code": self.series_code,
            "rationale": self.rationale,
        }


# Per-sector macro exposure: how the current macro factors hit one sector.
_EXPOSURE_MAGNITUDE = {"alto": 10.0, "moderado": 6.0, "bajo": 3.0}
_EXPOSURE_DIRECTION = {FAVORABLE: 1.0, ADVERSO: -1.0, NEUTRAL: 0.0, ND: 0.0}


def sector_macro_exposure(factors: List[Dict[str, Any]], slug: str, base: float = 50.0) -> float:
    """A 0-100 macro score for one sector from the contract's factors.

    Starts neutral (50) and is nudged by each factor that impacts *slug*: a
    favorable factor lifts it, an adverse one lowers it, scaled by magnitude. A
    sector no factor touches stays 50. This is what makes the IAI *macro*
    dimension discriminate sectors (an economy-wide value would normalize flat).
    *factors* are the dicts from :meth:`MacroSectorContract.to_dict`.
    """
    score = base
    for f in factors:
        if any(s.get("slug") == slug for s in f.get("impacted_sectors", [])):
            score += _EXPOSURE_DIRECTION.get(f.get("direction"), 0.0) * \
                _EXPOSURE_MAGNITUDE.get(f.get("magnitude"), 0.0)
    return round(max(0.0, min(100.0, score)), 2)


@dataclass(frozen=True)
class MacroSectorContract:
    """The macro context for a period: the set of macro→sector factors."""

    period: Optional[str]
    factors: List[MacroFactor] = field(default_factory=list)
    generated_from: str = "macro_monitor"
    doctrine_version: Optional[str] = None

    @property
    def available_count(self) -> int:
        """Factors with real data (not n/d)."""
        return sum(1 for f in self.factors if f.direction != ND)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "factors": [f.to_dict() for f in self.factors],
            "factor_count": len(self.factors),
            "available_count": self.available_count,
            "generated_from": self.generated_from,
            "doctrine_version": self.doctrine_version,
        }
