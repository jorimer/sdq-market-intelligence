"""Inteligencia de Fuentes — sugerencias de fuentes/información/sectores nuevos.

Transversal (vive en ``shared/``, no en un módulo de sector). El sistema propone (agente
IA leyendo las brechas del readiness) o una persona sugiere; el sistema evalúa y
andamía; el dueño decide e integra. Doctrina: el sistema propone, el dueño dispone.

PK UUID, parity SQLite↔Postgres (String acotado, JSON para la evaluación/plan).
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, JSON, String, Text

from shared.database.base import Base, UUIDMixin

# Tipo de sugerencia.
KIND_SOURCE = "source"        # una fuente de datos concreta (un portal, un boletín)
KIND_INFO = "info_type"       # un tipo de información / variable que falta
KIND_SECTOR = "sector"        # un eje/sector nuevo para el catálogo
KINDS = (KIND_SOURCE, KIND_INFO, KIND_SECTOR)

# Ciclo de vida (autogestión del flujo). El build de integración real es manual (compuerta
# del dueño): el sistema llega a "approved" + plan andamiado; "integrating"/"integrated"
# los marca quien ejecuta el build.
STATUS_PROPOSED = "proposed"
STATUS_EVALUATING = "evaluating"
STATUS_EVALUATED = "evaluated"
STATUS_APPROVED = "approved"
STATUS_INTEGRATING = "integrating"
STATUS_INTEGRATED = "integrated"
STATUS_REJECTED = "rejected"
STATUS_DEFERRED = "deferred"
STATUSES = (STATUS_PROPOSED, STATUS_EVALUATING, STATUS_EVALUATED, STATUS_APPROVED,
            STATUS_INTEGRATING, STATUS_INTEGRATED, STATUS_REJECTED, STATUS_DEFERRED)

ORIGIN_MANUAL = "manual"
ORIGIN_AGENT = "agent"


class SourceSuggestion(UUIDMixin, Base):
    """Una sugerencia en el tablero de Inteligencia de Fuentes."""

    __tablename__ = "source_suggestions"

    kind = Column(String(20), nullable=False)          # source | info_type | sector
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    origin = Column(String(20), nullable=False, default=ORIGIN_MANUAL)  # manual | agent
    proposed_by = Column(String, ForeignKey("users.id"), nullable=True)

    # A qué brecha apunta: el eje (sector_key) y el gate que cerraría. Nulos para un
    # sector nuevo (no apunta a un eje existente).
    target_axis = Column(String(40), nullable=True)
    target_gate = Column(String(8), nullable=True)     # g1..g5

    status = Column(String(20), nullable=False, default=STATUS_PROPOSED)
    # Evaluación del sistema: {score, criteria{}, gate_closed, rationale, plan}. La llena
    # el evaluador (Increment 2); en la fundación queda None hasta evaluar.
    evaluation = Column(JSON, nullable=True)
    decision_note = Column(Text, nullable=True)        # nota del dueño al aprobar/rechazar

    __table_args__ = (
        Index("ix_source_suggestions_status", "status"),
        Index("ix_source_suggestions_axis", "target_axis"),
    )
