"""Almacén regional de banca, a nivel de SISTEMA nacional.

Deliberadamente separado de `BankingData`: distinto sujeto (un sistema bancario entero, no
una entidad), distinta semántica y distinta norma contable. Así el motor dominicano queda
literalmente intacto y el test de no-regresión es trivial, porque no hay nada que regresar.

**Nunca se puntúan entidades individuales fuera de RD.** El motor de `banking_score` está
calibrado contra el panel dominicano de 46 entidades y no es transferible; el boletín
tampoco lo necesita.
"""
from sqlalchemy import Column, Date, Float, Index, String, UniqueConstraint
from sqlalchemy.types import JSON

from shared.database.base import Base, UUIDMixin


class CountryBankingAggregate(UUIDMixin, Base):
    """Una métrica bancaria de un sistema nacional: (país, corte, métrica) → valor."""

    __tablename__ = "rb_country_aggregates"

    iso_code = Column(String(3), nullable=False)      # ISO3: "DOM", "COL", "BRA", "CHL"
    period_end = Column(Date, nullable=False)         # el CORTE, no una etiqueta de período
    metric = Column(String(60), nullable=False)
    value = Column(Float, nullable=True)              # None = ausente, jamás interpolado

    # ── Procedencia. Viaja POR FILA y no en una tabla aparte porque el boletín atribuye
    # emisor por emisor: si la licencia no está en la fila, la atribución hay que
    # reconstruirla desde afuera del dato, que es como se desincroniza.
    source = Column(String(30), nullable=False)
    license = Column(String(255), nullable=False)     # sin licencia no se publica: fail-closed
    fetched_at = Column(Date, nullable=True)

    # ── Lo que impide un ranking por accidente tres ediciones después.
    # La norma bajo la que el país computó la métrica. Sin este campo el guard de
    # no-comparabilidad (T-BR-9) no tiene sobre qué operar: "solvencia" en Colombia (CUIF)
    # y en Brasil (Res. CMN 4966) NO son la misma medición, y la propia SECMCA declara por
    # escrito que los indicadores bancarios de su región "no están armonizados".
    norma_contable = Column(String(80), nullable=False)

    meta = Column(JSON, nullable=True)

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
