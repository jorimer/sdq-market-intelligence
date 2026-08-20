"""Persistencia de la watchlist: qué vigila cada usuario.

Transversal (``shared/``), PK UUID, parity SQLite↔Postgres: ``String`` acotado y ``JSON``
para las listas; **ningún ENUM de base**. Un ENUM de Postgres vive en un namespace global de
tipos y una migración que lo recrea pasa verde en CI (SQLite lo ignora) y tumba el deploy —
este repo ya lo pagó. Los vocabularios se validan en `shared.alerts.service`.

Declarado con el estilo TIPADO de SQLAlchemy 2.0 (``Mapped`` / ``mapped_column``), como
``shared/data_api/models.py`` y a diferencia del resto del repo: con ``Column`` el checker ve
``Column[str]`` donde el código usa un ``str`` y cada asignación suma ruido al baseline (que
ya carga ~1300 de esos). Código nuevo no debería sumar deuda que ya se está pagando.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base, UUIDMixin

# Sentinela de "todo el eje" para ``subject``. NO se usa NULL, y no es cosmético: en
# SQLite y en Postgres dos NULL son DISTINTOS entre sí, así que un UNIQUE que incluya una
# columna nullable no impide dos filas «todo el eje» del mismo usuario para el mismo eje —
# y cada una entregaría su propia copia de cada alerta. Con sentinela, el UNIQUE muerde
# (lo prueba ``test_la_base_RECHAZA_dos_vigilancias_iguales``).
#
# La API expone ``null``, que es lo natural en JSON, y traduce en el borde; ver
# ``service._normalizar_subject`` y ``service.serializar``.
TODO_EL_EJE = ""


class AlertSubscription(UUIDMixin, Base):
    """Una vigilancia: (usuario, eje, sujeto) + cómo y cuándo quiere enterarse.

    **No confundir con ``shared.products.models.Subscription``**, que es la suscripción de
    COBRO (concede un ``AccessTier``). Esto es contenido: qué le interesa al cliente. Dos
    cosas distintas con el mismo nombre en el mismo repo es cómo se escribe el bug de
    acceso, y por eso el nombre y el módulo son otros.
    """

    __tablename__ = "alert_subscriptions"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    # Clave de ``shared.products.registry.PRODUCT_CATALOG``.
    sector_key: Mapped[str] = mapped_column(String(40), nullable=False)
    # Sujeto vigilado, tal como lo acepta ``snapshot(scope=…)``: entity_key, ISO3, provincia
    # o expediente según el eje. ``TODO_EL_EJE`` ("") = el sistema entero, sin nombrar.
    subject: Mapped[str] = mapped_column(String(120), nullable=False, default=TODO_EL_EJE)
    # Códigos de disparador que le interesan; NULL = todos los del eje.
    rule_codes: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    min_severity: Mapped[str] = mapped_column(String(10), nullable=False, default="media")
    channels: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(10), nullable=False, default="inmediato")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                         server_default=true(), default=True)
    # Por qué está suspendida (p.ej. "acceso_revocado"). La vigilancia NO se borra cuando
    # cae el acceso: si el cliente renueva, vuelve a lo que ya había elegido.
    suspended_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "sector_key", "subject",
                         name="uq_alert_subscription_user_sector_subject"),
        Index("ix_alert_subscriptions_user", "user_id"),
        Index("ix_alert_subscriptions_sector", "sector_key"),
    )


class AlertEventRow(UUIDMixin, Base):
    """Un evento juzgado por el gate — **publicado o vetado**, los dos se guardan.

    **Por qué se persiste lo vetado.** Un veto silencioso se lee como que el eje no tenía
    nada que avisar, que es la lectura opuesta a la verdadera. Guardarlo con su motivo hace
    que ``GET /alerts/events`` pueda decir «3 señales retenidas por frescura del dato» en vez
    de no decir nada, y da la serie histórica para saber qué veto muerde más.

    **Por qué el evento es GLOBAL y la entrega es por-usuario.** El hecho —«la cobertura de
    este banco cayó»— es uno solo; a cuántas bandejas llega depende de quién lo vigilaba.
    Duplicar la fila por suscriptor haría que la misma condición se contara N veces en
    cualquier lectura agregada.
    """

    __tablename__ = "alert_events"

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    sector_key: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(120), nullable=False, default=TODO_EL_EJE)
    periodo: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    severidad: Mapped[str] = mapped_column(String(10), nullable=False, default="media")
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    relaciones: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    valores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    procedencia: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Tres estados, no dos: None = indeterminado, y no publica. Ver `gate.veto_frescura`.
    frescura: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    publicada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    veto_motivo: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    veto_detalle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Identidad de la CONDICIÓN (sin período): es la clave con la que el dedup evita
    # re-avisar lo mismo trimestre tras trimestre. Ver ``reglas.AlertEvent.clave_dedup``.
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # A cuántas bandejas llegó. 0 con ``publicada=True`` es un dato, no un error: significa
    # que el gate lo dejó pasar y nadie lo estaba vigilando.
    entregas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_alert_events_sector_subject", "sector_key", "subject"),
        Index("ix_alert_events_dedup", "dedup_key"),
    )
