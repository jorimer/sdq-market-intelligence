"""Persistencia de los Comunicados de Política Monetaria del BCRD (decisiones de TPM)."""
from sqlalchemy import Column, Float, Integer, String, Text
from sqlalchemy.types import JSON

from shared.database.base import Base, UUIDMixin


class ComunicadoTPM(UUIDMixin, Base):
    """Un comunicado de decisión de TPM del BCRD, con la decisión estructurada + digest IA.

    El sentido de la decisión (``action``) y el nivel resultante (``tpm_level``) se derivan
    de forma DETERMINISTA del titular/cuerpo (nunca de la IA); ``digest`` guarda la
    interpretación IA del racional (resumen, hallazgos, riesgos). Único por ``article_id``
    (id del artículo en el CMS del BCRD) para que las re-corridas hagan upsert.
    """

    __tablename__ = "comunicado_tpm"

    article_id = Column(Integer, nullable=False, unique=True, index=True)
    string_id = Column(String(200), nullable=False, default="")
    title = Column(String(300), nullable=False, default="")
    decision_date = Column(String(10), nullable=True, index=True)  # YYYY-MM-DD del comunicado
    action = Column(String(10), nullable=True)    # hold | cut | hike
    tpm_level = Column(Float, nullable=True)       # nivel resultante de la TPM (%)
    bps_change = Column(Integer, nullable=True)    # magnitud del cambio (puntos básicos)
    source_url = Column(String(600), nullable=False, default="")
    body_text = Column(Text, nullable=True)        # racional (texto plano, truncado)
    digest = Column(JSON, nullable=True)           # digest IA estructurado
    status = Column(String(20), nullable=False, default="pending")  # ok | error
    error = Column(Text, nullable=True)
