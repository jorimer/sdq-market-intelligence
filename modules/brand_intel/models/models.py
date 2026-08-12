"""SQLAlchemy models for Brand Intel — the market-context layer over a client's brand tracker.

**This module is the platform's first one holding PRIVATE, per-client data.** Every other
module reads public sources (SIB, BCRD, SIPEN) and serves all subscribers alike. A brand
tracker belongs to ONE client, so ``engagement_id`` is a mandatory isolation key on every
table and every query path filters by it. By owner's decision this module is deliberately
**outside the public product catalog** and is never exposed through the Data API.

Tables:
  - BrandEngagement  — the mandate: client, focal brand, market, research provider.
  - BrandWave        — one tracker wave: period, fieldwork window, nominal sample.
  - BrandEntity      — a brand in the engagement's competitive set.
  - BrandObservation — one measurement: wave x brand x metric x segment, WITH its base.
  - BrandDecision    — the ledger: a client decision with metric, baseline, window, verdict.
  - BrandSalesDaily  — one store-day of sales AND transactions: the only source that
                       separates traffic from ticket, which no survey can do.
  - BrandPlanDocument— a client plan document (agency strategy, media plan) with its text.
  - BrandPlanGoal    — a goal the reader extracted from a plan, pending human adoption.
  - BrandForecast    — a frozen forecast and, later, its score against the actual.

``base_n`` on the observation is not bookkeeping: it is what makes every confidence band
computable. An observation without its base can be displayed but can never sustain a
verdict — the significance engine treats it as unscoreable rather than assuming a base.
"""
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)

from shared.database.base import Base, UUIDMixin


class BrandClient(UUIDMixin, Base):
    """Quien contrata. Un cliente puede tener varios estudios, no solo su tracker.

    Antes el cliente era texto libre dentro del encargo, así que dos estudios del mismo
    cliente no estaban atados por nada y "Operador RD" y "Operador R.D." eran clientes
    distintos. Con código propio, el cliente se elige primero y los estudios cuelgan de él.

    **No es la frontera de aislamiento.** Esa sigue siendo ``BrandEngagement.organization_id``,
    que es lo que gobierna el 404-no-403 y por tanto lo único que no se toca aquí: el
    cliente es una agrupación *dentro* de la organización. Su ``organization_id`` sirve
    para heredarlo al crear un estudio, no para conceder acceso — precisamente porque un
    cliente existe antes de que nadie suyo tenga login, que es el caso de hoy.
    """

    __tablename__ = "brand_clients"
    __table_args__ = (UniqueConstraint("code", name="uq_brand_client_code"),)

    code = Column(String(40), nullable=False)            # "MCD-RD" — llave legible
    name = Column(String(200), nullable=False)           # "Operador RD"
    organization_id = Column(String(64), nullable=True)  # se hereda al crear un estudio
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)


class BrandEngagement(UUIDMixin, Base):
    """A per-client mandate. The isolation boundary for everything else in this module."""

    __tablename__ = "brand_engagements"
    __table_args__ = (UniqueConstraint("slug", name="uq_brand_engagement_slug"),)

    slug = Column(String(60), nullable=False)            # "mcdonalds-rd"
    client_name = Column(String(200), nullable=False)    # who pays for the tracker
    # El cliente al que pertenece el estudio. Nullable mientras haya encargos anteriores
    # a la entidad; `client_name` se conserva porque es lo que el informe imprime y no
    # depende de que el vínculo exista.
    client_id = Column(String, nullable=True)
    focal_brand = Column(String(120), nullable=False)    # the brand the report is about
    market = Column(String(80), nullable=False, default="República Dominicana")
    category = Column(String(80), nullable=True)         # "QSR", "banca minorista", …
    research_provider = Column(String(120), nullable=True)  # "Ipsos Dominicana"
    # Access control: only users of this organization may read the engagement.
    organization_id = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)


class BrandWave(UUIDMixin, Base):
    """One wave of the tracker."""

    __tablename__ = "brand_waves"
    __table_args__ = (
        UniqueConstraint("engagement_id", "code", name="uq_brand_wave_code"),
        Index("ix_brand_wave_engagement", "engagement_id", "sort_order"),
    )

    engagement_id = Column(String, nullable=False)
    code = Column(String(30), nullable=False)            # "2026-03", stable key
    label = Column(String(40), nullable=False)           # "Mar '26"
    sort_order = Column(Integer, nullable=False)         # 1..N, chronological
    period_date = Column(Date, nullable=True)            # reference date (deflator anchor)
    field_start = Column(Date, nullable=True)
    field_end = Column(Date, nullable=True)
    nominal_base = Column(Integer, nullable=True)        # declared n for the wave
    is_projection = Column(Boolean, default=False, nullable=False)  # future wave, no data yet


class BrandEntity(UUIDMixin, Base):
    """A brand in the competitive set of an engagement."""

    __tablename__ = "brand_entities"
    __table_args__ = (
        UniqueConstraint("engagement_id", "slug", name="uq_brand_entity_slug"),
    )

    engagement_id = Column(String, nullable=False)
    slug = Column(String(60), nullable=False)            # "mcdonalds"
    name = Column(String(120), nullable=False)           # "McDonald's"
    is_focal = Column(Boolean, default=False, nullable=False)
    in_category_set = Column(Boolean, default=True, nullable=False)
    # Whether this brand counts toward the category denominator. A brand measured for
    # context but outside the category (an ice-cream chain in a QSR study) is tracked
    # yet excluded from share, so the denominator stays honest.
    sort_order = Column(Integer, default=0, nullable=False)


class BrandMetric(UUIDMixin, Base):
    """A metric this engagement measures, when the study is not a brand tracker.

    The module ships a canonical vocabulary for brand trackers (``engines/metrics.py``)
    and both ingest paths reject anything outside it — which is what stops a misread
    label from inventing an indicator, and is also why a study measuring anything else
    had every one of its figures rejected. An engagement that declares its own metrics
    is validated against those instead; one that declares none keeps using the tracker
    vocabulary, so nothing already loaded changes.

    ``kind`` is the load-bearing field and the reason a person has to approve it. It
    decides which statistics are legitimate: only ``proportion`` admits a binomial
    confidence band, so a metric wrongly typed as one manufactures intervals out of
    nothing. The reading pass proposes a kind with the evidence it saw; when that
    evidence is thin it proposes one that does *not* unlock bands, because the failure
    that matters is the one that invents precision.
    """

    __tablename__ = "brand_metrics"
    __table_args__ = (
        UniqueConstraint("engagement_id", "code", name="uq_brand_metric_code"),
    )

    engagement_id = Column(String, nullable=False)
    code = Column(String(60), nullable=False)            # "nps", "satisfaccion_t2b"
    label = Column(String(160), nullable=False)          # como se imprime en la lámina
    kind = Column(String(20), nullable=False, default="count")
    # proportion | index | currency | count  — ver MetricDef.supports_bands
    is_core = Column(Boolean, default=False, nullable=False)
    # Entra al pronóstico congelado y al panel de vigilancia cada ola.
    higher_is_better = Column(Boolean, default=True, nullable=False)
    category_denominator = Column(Boolean, default=False, nullable=False)
    # Posición en una escalera de conversión, si el estudio tiene una. NULL = no aplica;
    # la invariante de monotonía solo corre sobre las métricas que la declaran.
    funnel_order = Column(Integer, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    description = Column(Text, nullable=True)


class BrandObservation(UUIDMixin, Base):
    """One measurement. ``brand_slug`` NULL = a category/market-level metric.

    ``base_n`` is the effective base of THIS cell — not the wave's nominal n. A brand-level
    attribute measured among "considerers" has a smaller base than the wave, and every
    confidence band depends on getting that right.
    """

    __tablename__ = "brand_observations"
    __table_args__ = (
        UniqueConstraint(
            "engagement_id", "wave_id", "brand_slug", "metric_code", "segment",
            name="uq_brand_observation",
        ),
        Index("ix_brand_obs_lookup", "engagement_id", "metric_code", "segment"),
    )

    engagement_id = Column(String, nullable=False)
    wave_id = Column(String, nullable=False)
    brand_slug = Column(String(60), nullable=True)       # NULL = category-level
    metric_code = Column(String(60), nullable=False)     # see engines/metrics.py
    segment = Column(String(60), nullable=False, default="total")
    value = Column(Float, nullable=False)
    base_n = Column(Integer, nullable=True)              # NULL → unscoreable, never assumed
    unit = Column(String(20), nullable=False, default="pct")
    source = Column(String(200), nullable=True)          # "Ipsos Hot Tracker · lámina 18"
    # Which reading this value is a projection of. `source` is prose for a human to read;
    # this is the registry entry, and it is what makes the current value traceable back
    # to the exact delivery that produced it. See BrandObservationReading.
    source_extraction_id = Column(String, nullable=True)


class BrandObservationReading(UUIDMixin, Base):
    """What one delivery said about one figure. Append-only; nothing here is overwritten.

    A tracker restates its earlier waves in every delivery, and the numbers are not always
    identical: a provider corrects a base, revises a weighting, fixes a chart. With one
    row per figure the second delivery had to overwrite the first, which made the truth
    depend on the order the client happened to upload the files — loading a year of decks
    out of order walked corrected figures backwards, silently.

    So every reading is kept as it was read, tied to the delivery it came from, and
    ``brand_observations`` becomes a *projection*: the reading from the most recent deck
    wins, and the rest stay on the record. That ordering is not an implementation detail —
    it is the answer to "¿esta cifra cambió?", which for a client paying to be told what
    its tracker really says is an output of the product, not bookkeeping.

    Precedence uses the deck's **vintage** (the most recent wave it contains), not the
    upload time: which delivery is newer is a fact about the deck, and a client uploading
    last year's backlog today must not thereby make it authoritative.
    """

    __tablename__ = "brand_observation_readings"
    __table_args__ = (
        UniqueConstraint(
            "extraction_id", "wave_id", "brand_slug", "metric_code", "segment",
            name="uq_brand_reading",
        ),
        Index("ix_brand_reading_key",
              "engagement_id", "wave_id", "brand_slug", "metric_code", "segment"),
    )

    engagement_id = Column(String, nullable=False)
    extraction_id = Column(String, nullable=True)        # NULL = libro Excel del proveedor
    wave_id = Column(String, nullable=False)
    brand_slug = Column(String(60), nullable=True)
    metric_code = Column(String(60), nullable=False)
    segment = Column(String(60), nullable=False, default="total")
    value = Column(Float, nullable=False)
    base_n = Column(Integer, nullable=True)
    unit = Column(String(20), nullable=False, default="pct")
    # Ola más reciente que trae el mazo del que sale esta lectura ("2026-03"). Decide la
    # precedencia; se guarda porque el mazo puede borrarse y la lectura permanece.
    deck_vintage = Column(String(30), nullable=True)
    source = Column(String(200), nullable=True)


class BrandDecision(UUIDMixin, Base):
    """The accountability ledger. The subject is THE CLIENT and its decisions.

    Not the research provider's recommendations: a decision may originate in the tracker,
    the agency or the operation. A decision names its measure, baseline, window and
    threshold — one that cannot is refused before budget is spent on it.

    The measure is EITHER a tracker metric (``metric_code``) OR a declared external
    source (``external_measure``: platform analytics, transactional data…). External
    goals exist because half of a real client plan lives outside the survey — leaving
    them out would make the ledger blind to most of what the client committed to. They
    never enter the sampling arithmetic: the ledger keeps them visible as
    "se mide con {fuente}; el tracker no la evalúa" instead of pretending a verdict.
    """

    __tablename__ = "brand_decisions"
    __table_args__ = (Index("ix_brand_decision_engagement", "engagement_id", "status"),)

    engagement_id = Column(String, nullable=False)
    title = Column(String(300), nullable=False)
    rationale = Column(Text, nullable=True)
    # The measure: tracker metric XOR external source (validated at the API boundary).
    metric_code = Column(String(60), nullable=True)
    external_measure = Column(Text, nullable=True)
    segment = Column(String(60), nullable=False, default="total")
    brand_slug = Column(String(60), nullable=True)
    baseline_wave_id = Column(String, nullable=False)
    baseline_value = Column(Float, nullable=True)        # resolved from observations
    target_wave_id = Column(String, nullable=True)       # the evaluation window
    success_threshold = Column(Float, nullable=True)     # pp of expected movement
    owner = Column(String(120), nullable=True)           # who executes, client-side
    # Verdict, written by the ledger engine when the target wave lands
    status = Column(String(20), nullable=False, default="open")
    # open | achieved | not_detectable | worsened | unevaluable
    verdict_note = Column(Text, nullable=True)
    observed_delta = Column(Float, nullable=True)
    detectable_threshold = Column(Float, nullable=True)  # MDD at 95% for that base


class BrandExtraction(UUIDMixin, Base):
    """One ingested presentation: the staging boundary between a PDF and the data.

    Extraction never writes to ``BrandObservation`` directly. A document lands here with
    its cells (below), gets validated against structural invariants, and only a human
    confirmation promotes the surviving cells into observations.

    The reason is not caution for its own sake: an extraction error that reaches
    observations is invisible afterwards — every chart, share and verdict downstream
    silently inherits it, and nothing in the analysis can tell a mis-read number from a
    real one. Staging is where that is still cheap to catch.
    """

    __tablename__ = "brand_extractions"
    __table_args__ = (
        Index("ix_brand_extraction_engagement", "engagement_id", "status"),
    )

    engagement_id = Column(String, nullable=False)
    document_name = Column(String(300), nullable=False)
    n_pages = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    # queued | reading | validated | confirmed | rejected | error
    model_used = Column(String(60), nullable=True)     # provenance of the vision pass
    method = Column(String(40), nullable=False, default="vision")
    # vision | coordinates | vision+coordinates
    summary = Column(JSON, nullable=True)              # counts by validation outcome
    note = Column(Text, nullable=True)

    # ── el trabajo, no solo su resultado ──────────────────────────────
    # Leer un mazo real son decenas de llamadas de visión: no cabe en una petición HTTP,
    # y la primera versión moría contra el presupuesto de tiempo sin dejar nada. La fila
    # es ahora el trabajo: guarda su propio PDF, cuántas láminas lleva, y se reanuda por
    # donde iba si el proceso muere.
    pages_done = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    report = Column(JSON, nullable=True)               # el IngestReport completo
    # El PDF vive aquí mientras dura el trabajo, y se borra al terminar. En la base y no
    # en un bucket a propósito: es dato privado de un cliente, y `engagement_id` es lo
    # único que gobierna su acceso — un bucket necesitaría su propio control.
    source_pdf = Column(LargeBinary, nullable=True)
    max_pages = Column(Integer, nullable=True)
    confirmed_by = Column(String(120), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)


class BrandExtractionCell(UUIDMixin, Base):
    """One proposed observation, with where it came from and whether it survived checks.

    ``value`` is what was read; ``validation`` is whether an invariant confirmed it. A cell
    that fails or cannot be checked is still stored — the reviewer needs to see what was
    read and why it is doubtful, not an empty space where a number should be.
    """

    __tablename__ = "brand_extraction_cells"
    __table_args__ = (
        Index("ix_brand_cell_extraction", "extraction_id", "validation"),
    )

    extraction_id = Column(String, nullable=False)
    engagement_id = Column(String, nullable=False)
    page_number = Column(Integer, nullable=True)
    chart_label = Column(String(300), nullable=True)   # the slide's own title, as read

    wave_code = Column(String(30), nullable=True)
    brand_slug = Column(String(60), nullable=True)
    metric_code = Column(String(60), nullable=False)
    segment = Column(String(60), nullable=False, default="total")
    value = Column(Float, nullable=False)
    base_n = Column(Integer, nullable=True)
    unit = Column(String(20), nullable=False, default="pct")

    source_method = Column(String(40), nullable=False, default="vision")
    # vision | coordinates | both  ("both" = the two agreed)
    validation = Column(String(30), nullable=False, default="unchecked")
    # passed | failed | unchecked | conflict
    validation_note = Column(Text, nullable=True)
    coordinate_value = Column(Float, nullable=True)    # the second source, when available
    included = Column(Boolean, default=True, nullable=False)  # reviewer's keep/drop


class BrandConclusion(UUIDMixin, Base):
    """Una afirmación que sostiene el estudio del proveedor, con su recibo.

    El resto del módulo guarda **cifras**. Con cifras solo se puede describir, y describir
    es lo que el proveedor ya hizo: repetirlo no se puede cobrar. Lo que SDQ añade es
    explicar por qué pasó lo que el proveedor observó — y para eso su conclusión tiene que
    existir como fila, no como prosa dentro de un PDF.

    **Esta tabla no pasa por confirmación humana, y las observaciones sí.** No es un
    descuido: el portón de confirmación protege a las cifras, porque un número mal leído
    entra en la serie y desde ahí ningún gráfico puede distinguirlo de uno bueno. Una
    conclusión no alimenta aritmética alguna y se comprueba contra su lámina en cualquier
    momento. Lo que la protege es ``claim`` + ``page_number``: el texto literal y dónde
    está escrito. Sin eso, «el proveedor concluye X» sería impublicable.

    ``claim`` es LITERAL a propósito. Un resumen propio pondría en boca del socio palabras
    que no dijo, en un documento que llega a su cliente. El informe del cliente igual lee
    natural: la lámina se guarda aquí y sale en la vista interna y en el documento que se
    discute con el proveedor, no en la prosa.
    """

    __tablename__ = "brand_conclusions"
    __table_args__ = (
        Index("ix_brand_conclusion_engagement", "engagement_id", "kind"),
    )

    engagement_id = Column(String, nullable=False)
    extraction_id = Column(String, nullable=True)      # de qué entrega salió
    page_number = Column(Integer, nullable=False)      # el recibo: dónde está escrita
    claim = Column(Text, nullable=False)               # literal, nunca reescrita

    kind = Column(String(20), nullable=False, default="hallazgo")
    # hallazgo | recomendacion | contexto
    # Las marcas de las que trata, tal como están impresas, y resueltas contra el set.
    # Es una LISTA porque las afirmaciones reales lo son: «Little Caesars, KFC y Wendy's
    # muestran tendencia creciente» habla de tres marcas, y guardarla como una sola la
    # dejaría sin resolver — es decir, sin poder explicarse ni contrastarse.
    subjects = Column(JSON, nullable=True)             # ["Little Caesars", "KFC"]
    subject_slugs = Column(JSON, nullable=True)        # ["little-caesars", "kfc"]
    topic = Column(String(200), nullable=True)
    metric_code = Column(String(60), nullable=True)    # resuelto contra el diccionario
    direction = Column(String(20), nullable=True)      # sube | baja | estable | None
    wave_label = Column(String(60), nullable=True)     # tal como está impresa
    wave_code = Column(String(30), nullable=True)      # resuelta contra las olas
    confident = Column(Boolean, default=True, nullable=False)


class BrandDiscrepancy(UUIDMixin, Base):
    """Un desacuerdo defendible entre las cifras confirmadas y una conclusión del proveedor.

    Existe por una regla de la alianza: **no se audita al proveedor delante de su
    cliente**. Cuando el contraste encuentra que los datos sostienen lo contrario de lo
    que el estudio afirma —con significancia, no con corazonada—, eso no va al informe:
    viene aquí, a una mesa aparte, y se discute con el proveedor primero. El informe del
    cliente solo puede apoyarse en conclusiones sin discrepancia abierta, y esa exclusión
    se garantiza en el ensamblador, no en la buena memoria de quien redacta.

    La conclusión viaja COPIADA (claim, lámina, marcas), no solo referida: las
    conclusiones se reemplazan cuando una entrega se relee, y una discrepancia en
    discusión con el proveedor no puede quedarse apuntando al vacío.

    Estados: ``abierta`` → ``discutida`` → ``acordada`` | ``retirada``. Mientras esté en
    las dos primeras, ninguna explicación del informe puede montarse sobre su conclusión.
    """

    __tablename__ = "brand_discrepancies"
    __table_args__ = (
        Index("ix_brand_discrepancy_engagement", "engagement_id", "status"),
    )

    engagement_id = Column(String, nullable=False)
    conclusion_id = Column(String, nullable=True)      # la fila viva, si aún existe
    claim = Column(Text, nullable=False)               # copia literal: sobrevive relecturas
    page_number = Column(Integer, nullable=False)
    subject_slugs = Column(JSON, nullable=True)
    metric_code = Column(String(60), nullable=False)
    provider_direction = Column(String(20), nullable=False)   # lo que afirma el estudio
    data_note = Column(Text, nullable=False)           # lo que sostienen las cifras y por qué
    per_brand = Column(JSON, nullable=True)            # delta y veredicto por marca

    status = Column(String(20), nullable=False, default="abierta")
    # abierta | discutida | acordada | retirada
    resolution_note = Column(Text, nullable=True)      # qué se acordó, o por qué se retiró
    updated_by = Column(String(120), nullable=True)


class BrandSalesDaily(UUIDMixin, Base):
    """Una jornada de venta de un local, con su comparativo del ejercicio anterior.

    Es la primera tabla del módulo que **no** es percepción. El estudio de mercado
    establece qué percibe el consumidor; esto establece qué hizo. La mayor parte del
    valor analítico del cruce vive en dos columnas: la venta y el CONTEO DE
    TRANSACCIONES (``gc``, guest count). Con ambas, el movimiento de facturación se
    descompone entre afluencia y gasto por visita — la lectura que ninguna encuesta
    puede dar, porque una encuesta no observa transacciones.

    El cheque promedio NO se almacena: se computa como venta ÷ transacciones al leer.
    Guardar un derivado abre la puerta a que la suma de las partes no cuadre con el
    total cuando una fila se corrige.

    ``*_prior`` es el valor de LAS MISMAS FECHAS del ejercicio anterior tal como lo
    entrega el tablero del operador, no una serie propia: el comparativo es del cliente
    y se conserva como lo publica, lo que permite reproducir sus cifras exactamente.
    """

    __tablename__ = "brand_sales_daily"
    __table_args__ = (
        UniqueConstraint("engagement_id", "business_date", "store_id",
                         name="uq_brand_sales_daily"),
        Index("ix_brand_sales_lookup", "engagement_id", "business_date"),
    )

    engagement_id = Column(String, nullable=False)
    business_date = Column(Date, nullable=False)
    store_id = Column(String(40), nullable=False)
    store_name = Column(String(160), nullable=True)
    city = Column(String(80), nullable=True)             # normalizada en la ingesta
    zone = Column(String(80), nullable=True)

    # Totales del local en la jornada.
    sales = Column(Float, nullable=True)
    sales_prior = Column(Float, nullable=True)
    transactions = Column(Integer, nullable=True)        # guest count
    transactions_prior = Column(Integer, nullable=True)

    # Desglose por canal. Un canal ausente en el tablero queda en NULL —jamás en cero—
    # para que el motor distinga "no vendió" de "no se informó".
    sales_drive_thru = Column(Float, nullable=True)
    sales_drive_thru_prior = Column(Float, nullable=True)
    transactions_drive_thru = Column(Integer, nullable=True)
    transactions_drive_thru_prior = Column(Integer, nullable=True)
    sales_delivery = Column(Float, nullable=True)
    sales_delivery_prior = Column(Float, nullable=True)
    transactions_delivery = Column(Integer, nullable=True)
    transactions_delivery_prior = Column(Integer, nullable=True)
    sales_counter = Column(Float, nullable=True)
    sales_counter_prior = Column(Float, nullable=True)
    transactions_counter = Column(Integer, nullable=True)
    transactions_counter_prior = Column(Integer, nullable=True)

    currency = Column(String(8), nullable=False, default="DOP")
    source_file = Column(String(300), nullable=True)     # el tablero del que salió


class BrandPlanDocument(UUIDMixin, Base):
    """Un documento de plan que el cliente compartió, con su texto como recibo maestro.

    Es la puerta de entrada de los planes al ledger: hasta ahora una decisión solo nacía
    tecleada en el formulario, y los documentos reales del cliente (la estrategia de su
    agencia, su plan de medios) se quedaban fuera del sistema. El documento se guarda con
    su capa de texto completa porque cada meta extraída se cita contra él — mismo
    principio del recibo que las conclusiones del proveedor.

    Dato privado del encargo: ``engagement_id`` gobierna el acceso (404, no 403), fuera
    del catálogo y de la Data API, como todo el módulo. Y es contenido NO CONFIABLE:
    de un plan se EXTRAE, jamás se obedece — el lector lo trata como dato.
    """

    __tablename__ = "brand_plan_documents"
    __table_args__ = (
        Index("ix_brand_plan_document_engagement", "engagement_id", "status"),
    )

    engagement_id = Column(String, nullable=False)
    filename = Column(String(300), nullable=False)
    title = Column(String(300), nullable=True)          # del documento, si el lector lo ve
    source_org = Column(String(200), nullable=True)     # agencia/autor declarado en el doc
    uploaded_by = Column(String(120), nullable=True)
    page_count = Column(Integer, nullable=True)         # None para HTML (sin páginas)
    raw_text = Column(Text, nullable=True)              # la capa de texto: recibo maestro
    status = Column(String(20), nullable=False, default="propuesto")
    # propuesto (metas pendientes de revisión) | revisado (todas adoptadas o descartadas)
    note = Column(Text, nullable=True)


class BrandPlanGoal(UUIDMixin, Base):
    """Una meta extraída de un plan del cliente, pendiente de adopción humana.

    El lector PROPONE; solo una persona ADOPTA. A diferencia de las conclusiones del
    proveedor (sin portón, porque no alimentan aritmética), una meta adoptada se vuelve
    una ``BrandDecision``: fija umbral, responsable y sale en el informe del cliente con
    veredicto ola tras ola. Ese portón es el mismo de las cifras, y por el mismo motivo.

    ``claim`` es LITERAL — la meta con las palabras del documento — y ``page_number``
    la ancla. Una meta sin métrica del tracker no se descarta: lleva su fuente externa
    declarada (``measure_source``), porque la mitad de un plan real vive fuera de la
    encuesta y un seguimiento que la ignora queda cojo.
    """

    __tablename__ = "brand_plan_goals"
    __table_args__ = (
        Index("ix_brand_plan_goal_engagement", "engagement_id", "status"),
    )

    engagement_id = Column(String, nullable=False)
    plan_document_id = Column(String, nullable=False)
    claim = Column(Text, nullable=False)                # literal, nunca reescrita
    page_number = Column(Integer, nullable=True)        # None para HTML sin paginación
    kind = Column(String(20), nullable=False, default="meta")
    # meta (con objetivo evaluable) | accion (sin métrica: citable, no evaluable)
    metric_code = Column(String(60), nullable=True)     # mapeada al diccionario, si aplica
    segment = Column(String(60), nullable=False, default="total")
    target_from = Column(Float, nullable=True)          # nivel de partida declarado
    target_to = Column(Float, nullable=True)            # nivel objetivo declarado
    expected_move = Column(Float, nullable=True)        # movimiento esperado (pp o unidad)
    owner_declared = Column(String(200), nullable=True) # a quién el documento la asigna
    measure_source = Column(String(200), nullable=True)
    # "tracker" | fuente externa declarada ("analytics de plataformas", "dato transaccional")
    confident = Column(Boolean, default=True, nullable=False)

    status = Column(String(20), nullable=False, default="propuesta")
    # propuesta | adoptada | descartada
    adopted_decision_id = Column(String, nullable=True)  # FK lógica → BrandDecision
    dismiss_note = Column(Text, nullable=True)


class BrandForecast(UUIDMixin, Base):
    """A frozen forecast, scored when the wave lands. Mirrors the TPM ledger discipline.

    At most one ``pending`` forecast per (engagement, metric, brand, segment): the current
    one. The past is never seeded — that is what the backtest is for.
    """

    __tablename__ = "brand_forecasts"
    __table_args__ = (
        Index("ix_brand_forecast_pending", "engagement_id", "status"),
    )

    engagement_id = Column(String, nullable=False)
    target_wave_id = Column(String, nullable=False)
    brand_slug = Column(String(60), nullable=True)
    metric_code = Column(String(60), nullable=False)
    segment = Column(String(60), nullable=False, default="total")
    point = Column(Float, nullable=False)                # central forecast
    lo = Column(Float, nullable=False)                   # 95% band
    hi = Column(Float, nullable=False)
    rule = Column(String(40), nullable=False)            # winning rule from the backtest
    issued_at_wave_id = Column(String, nullable=False)   # history available when issued
    status = Column(String(20), nullable=False, default="pending")  # pending | scored
    actual = Column(Float, nullable=True)
    inside_band = Column(Boolean, nullable=True)
    abs_error = Column(Float, nullable=True)
