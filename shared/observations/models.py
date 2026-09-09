"""Tabla transversal de observaciones — una fila por (eje, serie, período, dimensión).

**Por qué transversal y no una por eje.** El mismo esquema estaba copiado tres veces
—``mm_series``, ``insurance_series``, ``pension_series``— y los demás ejes ni siquiera tienen
tabla de series. Un feed mensual por eje con la copia número cuatro garantiza que las cuatro
diverjan. Las tres existentes NO se migran: conviven, y esta sirve a lo nuevo.

**La forma sale de ``mm_series``, que es la probada**, con dos agregados:

* ``sector_key`` — porque la tabla es de todos los ejes.
* las dimensiones que el microdato ya trae y hasta ahora se descartaban al agregar
  (``provincia``, ``tipologia``). Es la diferencia entre «el sector creció 4 %» y «tal
  provincia concentra el 31 % de los m² licenciados de uso turístico».

**``nature`` no es decorativa: es la que elige la línea base.** Un FLUJO se compara contra el
mismo período del año anterior (única forma de no confundir estación con tendencia) y una
TASA se mueve en puntos, no en porcentaje. Sin ella cada consumidor adivina, y adivinar una
sola transformación para todas es un error de categoría en el 37 % del catálogo — la lección
ya está escrita en ``shared/data/series_nature.py`` y acá se persiste, no se re-deduce.

**Las dimensiones son NOT NULL con centinela vacío, no NULL.** En PostgreSQL dos NULL son
distintos, así que una restricción de unicidad que las incluya NO impide duplicar la fila
nacional — ``insurance_series`` tiene exactamente ese agujero. Se sigue el patrón de
``ProductReportCache.scope``: cadena vacía con ``server_default``, y la unicidad funciona.

**Declarada con el estilo TIPADO de SQLAlchemy 2.0** (``Mapped``/``mapped_column``), como
``shared/data_api/models.py`` y a diferencia del resto del repo. Con ``Column`` el checker ve
``Column[str]`` donde el código usa un ``str`` y cada lectura genera ruido de tipos: el
baseline del repo carga ~1.300 de esos, y declarar esta tabla al estilo viejo sumaba 17 más.
Código nuevo no debería sumar deuda que ya se está pagando.
"""
from datetime import date
from typing import Optional

from sqlalchemy import Date, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base, UUIDMixin


class SectorObservation(UUIDMixin, Base):
    """Una observación sub-anual de un eje, con su procedencia y su naturaleza."""

    __tablename__ = "sector_observations"
    __table_args__ = (
        UniqueConstraint("sector_key", "series_code", "period", "provincia", "tipologia",
                         name="uq_sector_observations_punto"),
        Index("ix_sector_observations_eje_serie_periodo",
              "sector_key", "series_code", "period"),
        Index("ix_sector_observations_eje_periodo", "sector_key", "period"),
    )

    sector_key: Mapped[str] = mapped_column(String(40), nullable=False)
    # 255 como `mm_series`: los códigos jerárquicos del motor de planillas del BCRD llegan a
    # 73 caracteres y PostgreSQL SÍ aplica el largo de un VARCHAR (SQLite no). Un tope corto
    # pasa dev y tests enteros y revienta en producción con StringDataRightTruncation.
    series_code: Mapped[str] = mapped_column(String(255), nullable=False)
    #: "2025-07" | "2025-Q3" | "2025"
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    #: NULL = falta. Jamás 0.0 ni interpolado.
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)  # "m2", "conteo"
    #: monthly | quarterly | annual
    frequency: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    #: flow | stock | rate | index | unknown — ver `shared/data/series_nature.py`.
    nature: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)

    # ── Dimensiones del microdato ──
    # "" = la observación es del agregado, no de una demarcación/tipología. Centinela y no
    # NULL para que la unicidad de arriba valga en PostgreSQL (dos NULL son distintos).
    provincia: Mapped[str] = mapped_column(
        String(80), nullable=False, default="", server_default="")
    tipologia: Mapped[str] = mapped_column(
        String(80), nullable=False, default="", server_default="")

    # ── Linaje ──
    source: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)   # "MIVHED"
    published_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
