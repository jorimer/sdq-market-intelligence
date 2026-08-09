"""Base contract for every external data source.

Mixed-source strategy (decision 2026-06-06): each client declares a ``mode`` —
``"live"`` (hits a real API) or ``"fixture"`` (reads versioned local data) —
behind the same interface, so switching a source from fixture to live never
touches the modules that consume it.

Rules enforced here:
  * License must be verified before any ingestion (``check_license``).
  * Missing data stays ``None`` — never interpolated silently.
  * Every record is normalized to ``Record`` with a :class:`Lineage` stamp.
"""
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data")

Mode = Literal["live", "fixture"]

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class LicenseError(RuntimeError):
    """Raised when a source's data cannot be legally ingested."""


@dataclass(frozen=True)
class Record:
    """One normalized observation: a series value for a period, with provenance."""

    series: str
    period: str                  # e.g. "2025", "2025-Q4", "2025-12"
    value: Optional[float]       # None = missing, never interpolated
    lineage: Lineage
    unit: Optional[str] = None
    dimension: Optional[str] = None  # optional disaggregation (sex, region, …)
    # POR QUÉ falta el valor, cuando ``value is None``. El nulo honesto ya era la regla;
    # sin la razón, el consumidor no puede distinguir "la fuente no lo publica" de "lo
    # medimos y la muestra no alcanza" — dos cosas que se actúan distinto. Mismo campo
    # que ``shared.products.contract.SeriesObservation.reason``, en la capa de ingesta.
    reason: Optional[str] = None


class SourceClient(ABC):
    """Abstract read-only client for one external source."""

    #: Human/source identifier used in lineage stamps.
    source: str = "UNKNOWN"
    #: License/usage terms; must be set to a permitted value to ingest.
    license: str = "unknown"
    #: Whether the configured license permits ingestion into our corpus.
    license_ok: bool = False

    def __init__(self, mode: Mode = "fixture") -> None:
        self.mode: Mode = mode

    # ── License gate ──────────────────────────────────────────────
    def check_license(self) -> None:
        """Raise :class:`LicenseError` unless ingestion is permitted."""
        if not self.license_ok:
            raise LicenseError(
                f"Fuente '{self.source}': licencia '{self.license}' no permite ingesta"
            )

    # ── Fixture helpers ───────────────────────────────────────────
    def _load_fixture(self, filename: str) -> Dict[str, Any]:
        path = _FIXTURES_DIR / filename
        if not path.exists():
            logger.warning("Fixture ausente para %s: %s", self.source, path.name)
            return {}
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def _records_from_fixture(
        self,
        fixture: Dict[str, Any],
        series: Optional[str],
        period: Optional[str],
        lineage: Lineage,
    ) -> List[Record]:
        """Turn a fixture dict into ``Record``s, preserving ``None`` (missing).

        Fixture shape::

            {"<series>": {"unit": "%", "dimension": "sexo",
                          "observations": {"2025-Q1": 4.5, "2025-Q2": null}}}
        """
        out: List[Record] = []
        for s_name, s in fixture.items():
            if series and s_name != series:
                continue
            unit = s.get("unit")
            dimension = s.get("dimension")
            for p, v in s.get("observations", {}).items():
                if period and p != period:
                    continue
                out.append(
                    Record(
                        series=s_name,
                        period=p,
                        value=None if v is None else float(v),
                        lineage=lineage,
                        unit=unit,
                        dimension=dimension,
                    )
                )
        return out

    # ── Source-specific implementations ───────────────────────────
    @abstractmethod
    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        """Return normalized records for *series* (optionally a single *period*).

        Implementations must call :meth:`check_license` before ingesting and
        stamp every record with a :class:`Lineage`.
        """
        raise NotImplementedError


class FixtureBackedClient(SourceClient):
    """A source whose ``live`` mode is pending; ``fixture`` mode reads local data.

    Concrete connectors set ``source``/``license``/``license_ok``,
    ``fixture_file`` and ``live_phase`` and inherit a working ``fetch``.
    """

    fixture_file: str = ""
    live_phase: str = "fase futura"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            raise NotImplementedError(
                f"Conector {self.source} en modo 'live' pendiente ({self.live_phase})"
            )
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        return self._records_from_fixture(fixture, series, period, lineage)
