"""Almacén regional de banca, a nivel de SISTEMA nacional.

Deliberadamente separado de `BankingData`: distinto sujeto (un sistema bancario entero, no
una entidad), distinta semántica y distinta norma contable. Así el motor dominicano queda
literalmente intacto y el test de no-regresión es trivial, porque no hay nada que regresar.

**Nunca se puntúan entidades individuales fuera de RD.** El motor de `banking_score` está
calibrado contra el panel dominicano de 46 entidades y no es transferible; el boletín
tampoco lo necesita.
"""
import datetime as dt
from typing import Any, Dict, Optional

from sqlalchemy import Date, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from shared.database.base import Base, UUIDMixin


class CountryBankingAggregate(UUIDMixin, Base):
    """Una métrica bancaria de un sistema nacional: (país, corte, métrica) → valor."""

    __tablename__ = "rb_country_aggregates"

    iso_code: Mapped[str] = mapped_column(String(3))          # ISO3: "DOM", "COL", "CHL"
    period_end: Mapped[dt.date] = mapped_column(Date)         # el CORTE, no una etiqueta
    metric: Mapped[str] = mapped_column(String(60))
    value: Mapped[Optional[float]] = mapped_column(Float)     # None = ausente, jamás interpolado

    # ── Procedencia. Viaja POR FILA y no en una tabla aparte porque el boletín atribuye
    # emisor por emisor: si la licencia no está en la fila, la atribución hay que
    # reconstruirla desde afuera del dato, que es como se desincroniza.
    source: Mapped[str] = mapped_column(String(30))
    license: Mapped[str] = mapped_column(String(255))         # sin licencia no se publica
    fetched_at: Mapped[Optional[dt.date]] = mapped_column(Date)

    # ── Lo que impide un ranking por accidente tres ediciones después.
    # La norma bajo la que el país computó la métrica. Sin este campo el guard de
    # no-comparabilidad (T-BR-9) no tiene sobre qué operar: "solvencia" en Colombia (CUIF)
    # y en Brasil (Res. CMN 4966) NO son la misma medición, y la propia SECMCA declara por
    # escrito que los indicadores bancarios de su región "no están armonizados".
    norma_contable: Mapped[str] = mapped_column(String(80))

    meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    __table_args__ = (
        # `source` va en la clave a propósito. Sin él, la misma métrica traída de dos
        # emisores colapsa en una fila y uno pisa al otro — y como cada emisor trae su
        # propia `norma_contable`, lo que se pierde no es un duplicado sino una medición
        # distinta. Es el caso real de RD, que llega por EMFA (armonizado, junto a otros
        # siete países) y también por la SB.
        UniqueConstraint("iso_code", "period_end", "metric", "source",
                         name="uq_rb_pais_periodo_metrica"),
        Index("ix_rb_pais_periodo", "iso_code", "period_end"),
    )
