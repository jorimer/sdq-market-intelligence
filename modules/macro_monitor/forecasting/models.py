"""El ledger de pronósticos: cada proyección emitida, y su puntuación cuando llega el dato.

**El track record es parte del producto, no un subproducto.** Por eso el ledger se escribe
antes que cualquier modelo: sin él, un pronóstico es una afirmación sin consecuencias.

Dos decisiones de esquema que existen porque hay una forma concreta de reescribir la
historia sin querer:

**`revision` está en la CLAVE.** Con una clave de cuatro campos —modelo, serie, horizonte,
corte— una corrección de un pronóstico ya emitido no se puede escribir, colisiona, y el
único camino queda ser actualizar la fila original. Eso es reescribir la historia. Con
`revision` la corrección entra como fila nueva y las dos quedan.

**`status` y linaje son dos ejes distintos, en dos columnas distintas.** Un primer diseño
ponía `superseded` como valor de `status`, y eso reabría el maquillaje por otra puerta: el
track record se computa sobre `revision = 0` en estado `scored`, así que marcar la revisión 0
como superseded la sacaba del cómputo — corregir un pronóstico habría borrado el original del
historial, que es exactamente lo que `revision` viene a impedir. `status` es solo el ciclo de
vida de la puntuación; el linaje vive en `superseded_by`.

`tpm_forecast_log` no tiene `UniqueConstraint` alguno. Este ledger no repite esa omisión: sin
ella un rerun duplica pronósticos y el track record se maquilla sin que nadie lo note, que es
peor que maquillarlo a propósito.
"""
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.types import JSON

from shared.database.base import Base, UUIDMixin


class ForecastLog(UUIDMixin, Base):
    """Un pronóstico congelado + su puntuación cuando se conoce el observado."""

    __tablename__ = "mm_forecast_log"
    __table_args__ = (
        # Los CINCO campos. Ver el docstring del módulo: sin `revision` acá, corregir un
        # pronóstico obliga a pisar el original.
        UniqueConstraint("model_id", "target_series", "horizon", "as_of", "revision",
                         name="uq_mm_forecast_log_key"),
    )

    #: Modelo, variante y versión en un solo identificador (`bridge_imae_pib.m2.v1`). Sin un
    #: `model_version` aparte: versionar dos veces admite que se contradigan.
    model_id = Column(String(80), nullable=False, index=True)
    #: El `series_code` OBSERVABLE contra el que se va a puntuar — el que existe en
    #: `mm_series`. No el nombre que el modelo le da a su variable: el BVAR llamaba
    #: `"pib_real"` a la suya y esa fila no se podía puntuar contra nada, nunca.
    target_series = Column(String(255), nullable=False, index=True)
    horizon = Column(String(16), nullable=False)          # "2026-Q4"
    #: Horizonte RELATIVO en trimestres (1 = el próximo). Es la clave del CONJUNTO sobre el
    #: que se computa el track record, y la distinción no es cosmética: con el trimestre
    #: calendario como clave, cada conjunto tiene una sola observación y `n_oos` nunca llega
    #: al mínimo del gate — medido, tres años de operación perfecta dan n_oos = 1. La
    #: pregunta que el track record responde es «¿qué tan bien pronosticamos a UN trimestre
    #: vista?», y eso se acumula A LO LARGO de los trimestres.
    #: Nullable porque las filas anteriores a la migración no lo tienen; `track_record` las
    #: excluye en vez de adivinarles un horizonte.
    h = Column(Integer, nullable=True, index=True)
    as_of = Column(String(10), nullable=False)            # corte point-in-time
    revision = Column(Integer, nullable=False, default=0)  # 0 = como se publicó

    point = Column(Float, nullable=False)
    #: **En qué medida está `point`** — `medida.LEVEL` | `medida.DLOG_PCT`. Sin esto la
    #: puntuación suponía que el punto era directamente comparable con el valor de
    #: `target_series`, y no lo es: los dos motores emiten un Δlog en % (~0,4) contra una
    #: serie que es el índice de volumen del PIB (~133). El error habría salido ≈ 132,75 y
    #: eso se publica como RMSE. Es la misma cura que `shared/data/series_nature.py` un
    #: nivel más arriba: la magnitud se DECLARA junto al dato, no se adivina al leerlo.
    #: Nullable porque las filas anteriores a la migración no la traen; la puntuación las
    #: SALTEA en vez de suponerles «nivel», y `ledger.no_puntuables` las lista.
    measure = Column(String(16), nullable=True)
    #: ``[[nivel, lo, hi], …]`` — la misma estructura que `ProjectionMeta.intervals`.
    intervals = Column(JSON, nullable=False)
    # Denormalizados para consultar sin abrir el JSON. Derivados de `intervals`, nunca al
    # revés: si difieren, el JSON es el que vale.
    lo_80 = Column(Float, nullable=True)
    hi_80 = Column(Float, nullable=True)
    lo_90 = Column(Float, nullable=True)
    hi_90 = Column(Float, nullable=True)

    #: SOLO el ciclo de vida de la puntuación: `pending` | `scored`.
    status = Column(String(10), nullable=False, default="pending", index=True)
    #: Linaje, en su propia columna: id de la revisión que reemplaza a ésta.
    superseded_by = Column(String(36), nullable=True)

    # ── Puntuación (nula hasta que llega el observado) ──
    realized = Column(Float, nullable=True)
    realized_period_end = Column(String(10), nullable=True)
    abs_error = Column(Float, nullable=True)
    sq_error = Column(Float, nullable=True)
    #: ¿El observado cayó dentro del intervalo? Se puntúan LOS DOS niveles: un modelo cuyo
    #: intervalo del 80% acierta el 45% de las veces está mal calibrado aunque su error medio
    #: sea bajo, y quien dimensiona riesgo con él se equivoca.
    interval_hit_80 = Column(Boolean, nullable=True)
    interval_hit_90 = Column(Boolean, nullable=True)
    scored_at = Column(DateTime, nullable=True)
