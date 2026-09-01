"""SQLAlchemy models for the Sector Intel module (Eje 3).

Tables:
  - Sector      — a sector in scope (anchor sectors first).
  - SectorScore — computed IAI + SGPS for a sector and period.

El panel de insumos crudos (``SectorVariable`` / ``si_variables``) YA NO vive acá: es un
registro nacional que también leen el perfil sectorial de `shared/` y los ejes que lo
consumen, así que se mudó a ``shared/reference/sector_variables.py``. Importalo de ahí.
"""
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    JSON,
    String,
    Index,
    UniqueConstraint,
)

from shared.database.base import Base, UUIDMixin


class Sector(UUIDMixin, Base):
    """A sector in scope for IAI/SGPS."""
    __tablename__ = "si_sectors"

    code = Column(String(40), unique=True, nullable=False)   # "turismo"
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class SectorScore(UUIDMixin, Base):
    """Computed IAI + SGPS for a sector and period."""
    __tablename__ = "si_scores"
    __table_args__ = (
        UniqueConstraint("sector_code", "period", name="uq_si_sector_period"),
        Index("ix_si_scores_sector_period", "sector_code", "period"),
    )

    sector_code = Column(String(40), nullable=False)
    period = Column(String(10), nullable=False)
    iai_score = Column(Float, nullable=True)
    iai_band = Column(String(20), nullable=True)
    sgps_score = Column(Float, nullable=True)
    iai_breakdown = Column(JSON, nullable=True)
    sgps_breakdown = Column(JSON, nullable=True)
    model_version = Column(String(10), default="1.0", nullable=False)
