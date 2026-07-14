"""Persistencia del padrón de contribuyentes activos DGII, agregado por subclase CIIU.

Un snapshot por fecha de corte (``corte``) → la columna da historia multi-corte: cada
descarga nueva de DGII suma un corte, sin pisar los anteriores. Grano = subclase (no las
190k filas crudas por provincia/municipio). Consulta estructurada directa (por subclase,
por corte) además de alimentar los pasajes del motor de research (``shared/knowledge``).
"""
from sqlalchemy import Column, Date, Index, Integer, String, UniqueConstraint

from shared.database.base import Base, UUIDMixin


class DgiiContribuyenteSubclase(UUIDMixin, Base):
    """Contribuyentes activos de una subclase CIIU en un corte del padrón DGII."""

    __tablename__ = "dgii_contribuyente_subclase"
    __table_args__ = (
        UniqueConstraint("corte", "subclase", name="uq_dgii_contrib_corte_subclase"),
        Index("ix_dgii_contrib_corte", "corte"),
    )

    corte = Column(Date, nullable=False)              # fecha de corte del snapshot DGII
    subclase = Column(String(12), nullable=False)     # código CIIU rev.3, p.ej. "552118"
    descripcion = Column(String(255), nullable=True)  # etiqueta de la subclase
    activos = Column(Integer, nullable=False, default=0)
    activos_fisica = Column(Integer, nullable=True)   # split por tipo de persona
    activos_juridica = Column(Integer, nullable=True)

    # Lineage (mismo criterio que MacroSeries): de dónde salió cada cifra.
    source = Column(String(40), nullable=True)        # "DGII"
    source_url = Column(String(600), nullable=True)
    license = Column(String(200), nullable=True)
