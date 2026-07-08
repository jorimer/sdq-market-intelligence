"""Persistencia del track record EN VIVO del modelo de TPM.

Cada vez que se registra un pronóstico de la PRÓXIMA decisión (snapshot), se guarda una
fila ``pending`` con las probabilidades del clasificador XGBoost + la tasa implícita de la
regla de Taylor, congeladas a esa fecha. Cuando el BCRD publica la decisión real, la fila
se PUNTÚA (``scored``): acierto top-1, Brier score y error del nivel implícito.

Es un registro prospectivo (no se puede sembrar el pasado: reconstruir pronósticos viejos
ES el backtest). Empieza vacío y crece ~1 fila por reunión de la Junta Monetaria.
"""
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.types import JSON

from shared.database.base import Base, UUIDMixin


class TpmForecastLog(UUIDMixin, Base):
    """Un pronóstico de TPM congelado + su puntuación cuando se conoce la decisión real."""

    __tablename__ = "tpm_forecast_log"

    as_of = Column(String(10), nullable=False, index=True)   # fecha en que se hizo (YYYY-MM-DD)
    model_version = Column(String(50), nullable=True)
    # Pronóstico del clasificador XGBoost (probabilidades) + decisión más probable.
    prob_cut = Column(Float, nullable=True)
    prob_hold = Column(Float, nullable=True)
    prob_hike = Column(Float, nullable=True)
    predicted_action = Column(String(10), nullable=True)     # cut | hold | hike (argmax)
    # Regla de Taylor.
    implied_rate = Column(Float, nullable=True)
    bias_pp = Column(Float, nullable=True)
    tpm_vigente = Column(Float, nullable=True)               # TPM vigente al pronosticar
    features = Column(JSON, nullable=True)                   # snapshot point-in-time
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending | scored

    # Puntuación (nula hasta que se publica la decisión real).
    matched_article_id = Column(Integer, nullable=True)      # ComunicadoTPM.article_id casado
    realized_action = Column(String(10), nullable=True)
    realized_tpm_level = Column(Float, nullable=True)
    realized_date = Column(String(10), nullable=True)
    correct = Column(Boolean, nullable=True)                 # predicted_action == realized_action
    brier = Column(Float, nullable=True)                     # Brier multiclase (menor = mejor)
    level_abs_error = Column(Float, nullable=True)           # |tasa implícita − nivel real|
    scored_at = Column(DateTime, nullable=True)
