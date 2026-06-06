"""Data lineage — every normalized record carries where it came from.

The platform's traceability rule (CLAUDE.md / SPECS_OVERVIEW §calidad) requires
that any emitted figure trace to a sourced variable.  ``Lineage`` is the stamp
attached to each record so that requirement is enforceable end-to-end.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Lineage:
    """Provenance of one data point / series."""

    source: str                          # "BCRD", "SIB", "ONE", "DGA", "DGII", "WGI"
    license: str                         # license/usage terms under which we may use it
    published_at: Optional[date] = None  # when the source published the figure
    fetched_at: Optional[date] = None    # when we ingested it
    url: Optional[str] = None            # citation link
    note: Optional[str] = None           # e.g. "preliminar", "revisado"

    @property
    def publication_lag_days(self) -> Optional[int]:
        """Days between publication and ingestion (None if either is unknown)."""
        if self.published_at is None or self.fetched_at is None:
            return None
        return (self.fetched_at - self.published_at).days
