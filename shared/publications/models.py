"""Persistence for ingested BCRD publications and their AI digests."""
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import JSON

from shared.database.base import Base, UUIDMixin


class Publication(UUIDMixin, Base):
    """One ingested edition of a recurring BCRD report.

    ``digest`` holds the structured AI summary (resumen, hallazgos, cifras,
    riesgos, relevancia por sector). Unique per (report_key, period) so re-runs
    upsert instead of duplicating.
    """

    __tablename__ = "publication"
    __table_args__ = (UniqueConstraint("report_key", "period", name="uq_publication_report_period"),)

    report_key = Column(String(60), nullable=False, index=True)
    report_name = Column(String(200), nullable=False, default="")
    period = Column(String(60), nullable=False, index=True)  # "2025-06" | "Septiembre 2024"
    title = Column(String(300), nullable=False, default="")
    source_url = Column(String(600), nullable=False, default="")
    landing_url = Column(String(600), nullable=False, default="")
    published_at = Column(String(40), nullable=True)  # ISO date if known
    sectors = Column(JSON, nullable=True)             # ["banca","macro"]

    raw_text = Column(Text, nullable=True)            # extracted text (truncated)
    digest = Column(JSON, nullable=True)              # structured AI digest
    status = Column(String(20), nullable=False, default="pending")  # pending|ok|error
    error = Column(Text, nullable=True)
