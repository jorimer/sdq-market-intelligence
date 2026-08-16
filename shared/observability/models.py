"""Tabla del registro de gasto del modelo — infraestructura de plataforma.

Una fila por llamada al modelo, con quién la disparó. Ver ``llm_ledger`` para el porqué:
el costo se calculaba y se tiraba, y sin él una fuga de gasto solo se puede investigar,
no consultar.
"""
from sqlalchemy import Boolean, Column, Float, Index, Integer, JSON, String

from shared.database.base import Base, UUIDMixin


class LLMCall(UUIDMixin, Base):
    """Una llamada al modelo: qué la pidió, para qué, y cuánto costó.

    ``trigger_kind`` y ``trigger_detail`` son la razón de ser de la tabla. Sin ellos hay
    un total y ninguna forma de saber a quién cobrárselo: la auditoría que originó esto
    tuvo que leer código y logs para descubrir que una tarea diaria generaba 203 informes
    que nadie había pedido.

    Los HIT de caché se registran con ``cost_usd = 0``. Omitirlos haría invisible la
    demanda que la caché absorbe, que es justo lo que justifica tenerla.
    """

    __tablename__ = "llm_calls"
    __table_args__ = (
        # El uso normal es «gasto por disparador en un rango» y «gasto por módulo».
        Index("ix_llm_calls_created_trigger", "created_at", "trigger_detail"),
        Index("ix_llm_calls_created_module", "created_at", "module"),
    )

    #: narrativa | guard_numerico | vision | digest | extraccion | otro
    purpose = Column(String(30), nullable=False, index=True)
    model = Column(String(60), nullable=False)

    cost_usd = Column(Float, nullable=False, default=0.0)
    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    cache_hit = Column(Boolean, nullable=False, default=False)

    #: Eje o módulo que consume (banking_score, brand_intel, …). Nulo si no aplica.
    module = Column(String(60), nullable=True)
    template = Column(String(80), nullable=True)

    #: operacion | endpoint | script | desconocido
    trigger_kind = Column(String(20), nullable=False, default="desconocido")
    #: Nombre de la operación o ruta del endpoint. Es la columna que se agrupa.
    trigger_detail = Column(String(160), nullable=False, default="desconocido")
    user_id = Column(String, nullable=True)

    #: Todo lo que no merece columna propia (ámbito, nivel, idioma, período).
    detail = Column(JSON, nullable=True)
