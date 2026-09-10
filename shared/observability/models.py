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


class ToolRun(UUIDMixin, Base):
    """Una corrida de una herramienta comercial: qué se corrió, quién y cuánto tardó.

    **Por qué hace falta una tabla y no alcanza ``llm_calls``.** El ledger del modelo cuenta
    LLAMADAS, y la relación con una corrida no es uno a uno: un informe de marca dispara
    decenas y un score sin narrativa no dispara ninguna. «Cuántas veces se usó Deal Scoring
    este mes» no se puede derivar de ahí sin inventar un criterio de agrupación. Son dos
    preguntas distintas y cada una necesita su fila.

    **Mide, no restringe.** No hay cuota, ni gate, ni tier acá: esta tabla existe para que la
    decisión comercial se tome con números en vez de con una impresión. Es la única capa del
    sistema con costo variable real por corrida, y hoy nadie sabe cuántas corridas hay.

    Se registran también las corridas FALLIDAS (``ok = False``). Una herramienta cara que
    falla la mitad de las veces cuesta igual, y contar solo los éxitos oculta justo eso.
    """

    __tablename__ = "tool_runs"
    __table_args__ = (
        # El uso normal es «cuántas corridas por herramienta en un mes» y «las de este rango».
        Index("ix_tool_runs_periodo_herramienta", "periodo", "herramienta"),
        Index("ix_tool_runs_created", "created_at"),
    )

    #: Clave de la herramienta. Ver ``uso_de_herramientas.HERRAMIENTAS`` para el catálogo.
    herramienta = Column(String(40), nullable=False, index=True)
    #: Qué se corrió DENTRO de la herramienta ("respuesta", "entregable", "score", …). Sin
    #: esto, «marca: 40 corridas» mezcla leer un mazo de 60 láminas con abrir un informe.
    accion = Column(String(60), nullable=False)
    user_id = Column(String, nullable=True, index=True)
    #: Sobre QUÉ se corrió: el encargo, el deal, la pregunta recortada. El sujeto viaja con
    #: el número — un conteo sin sujeto no sostiene una conversación comercial.
    sujeto = Column(String(200), nullable=True)
    #: Período de agregación "AAAA-MM" desnormalizado. Se cuenta por índice sobre esta
    #: columna y no por una función de fecha, que en SQLite y Postgres se escribe distinto
    #: (paridad dev↔prod, misma doctrina que ``data_api_usage.quota_period``).
    periodo = Column(String(7), nullable=False)
    ok = Column(Boolean, nullable=False, default=True)
    latency_ms = Column(Integer, nullable=True)
    detalle = Column(JSON, nullable=True)
