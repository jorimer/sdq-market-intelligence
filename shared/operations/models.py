"""Operation console models — platform infra (shared across modules).

Recurring admin operations (rescore, prune-future, wgi-sync, …) are triggerable,
monitorable and schedulable from the UI. These tables back that console: run
history for audit, and durable schedules for the in-app scheduler (survives
restarts since the next-run lives in the DB, not memory).

Moved from modules/banking_score/models so the console is cross-module without
violating module independence. Table names are unchanged (no migration).
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text

from shared.database.base import Base, UUIDMixin


class OperationRun(UUIDMixin, Base):
    """One execution of a console operation — audit trail."""
    __tablename__ = "operation_runs"

    operation = Column(String(50), nullable=False, index=True)
    origin = Column(String(20), nullable=False, default="manual")  # manual | schedule | api
    triggered_by = Column(String, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), nullable=False, default="running")  # running | completed | error | skipped
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    summary = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)


class OperationSchedule(UUIDMixin, Base):
    """Durable cadence for a console operation (in-app scheduler)."""
    __tablename__ = "operation_schedules"

    operation = Column(String(50), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, nullable=False, default=False)
    interval_hours = Column(Integer, nullable=False, default=168)  # default weekly
    params = Column(JSON, nullable=True)  # e.g. {"period": "2025-12"}
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
