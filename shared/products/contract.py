"""Contrato uniforme que cada sector implementa — ``Protocol`` ``SectorProduct``.

Anti-Frankenstein: el framework (``shared/products``) nunca importa un módulo de
sector. Cada sector implementa este ``Protocol`` y se lo entrega al ensamblador y
al monitor de readiness. Onboarding del sector #11 = implementar este contrato +
su manifiesto + sus señales, **sin tocar el framework ni el motor genérico**.

Las señales (``DataHealth``, ``ValidationState``) son valores livianos que el
monitor de readiness (P1) consume para los gates G1 y G5. Se definen aquí —junto
al contrato que las produce— y no acoplan a ninguna DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable

from shared.products.manifest import SectorProductManifest
from shared.products.tiers import ProductTier


# ─── Señales de readiness (consumidas por el monitor en P1) ────────────


@dataclass(frozen=True)
class DataHealth:
    """Salud de la ingesta de la fuente autoritativa (alimenta G1 · Data).

    ``coverage`` y ``freshness`` se normalizan a [0,1] en el monitor; aquí se
    reportan crudos para trazabilidad (linaje hacia la señal real).
    """

    coverage: float                       # cobertura [0,1] de la fuente esperada
    freshness_days: Optional[int] = None  # antigüedad del dato más reciente (días)
    sources: Tuple[str, ...] = ()         # fuentes que respaldan el dato
    detail: str = ""                      # nota legible (trazabilidad)
    # Cadencia de publicación de la fuente — escala los umbrales de frescura del
    # monitor. Default "quarterly" = comportamiento histórico (banking/trade). Las
    # fuentes anuales rezagadas por naturaleza (ND-GAIN, WGI, cuentas nacionales)
    # declaran "annual" para no ser falsamente penalizadas como obsoletas.
    cadence: str = "quarterly"            # "monthly" | "quarterly" | "annual"

    # ── Qué PREGUNTA responde `coverage` ──────────────────────────────────────────────
    # Hasta que entró el eje de evaluación de leyes, todos los ejes respondían la misma:
    # «¿qué fracción del PESO de mi índice está anclada a dato real?» — una pregunta sobre
    # NUESTRO cableado, y por eso el gate podía castigarla sin más. El eje de leyes responde
    # otra: «¿cuántas de las metas que la LEY se fijó estamos midiendo?», que es una pregunta
    # sobre la ley. Con la primera lectura, cuanto peor redactada esté la norma menos «listo»
    # parece nuestro producto: el eje quedaba castigado por su propio hallazgo, y su techo
    # real —48 de 90 indicadores, porque 35 no los puede medir nadie— caía por debajo del
    # umbral de publicación. El eje no podía cruzar a Insight NUNCA.
    #
    # El vocabulario ya existía en `shared/registry/signals.py`, donde el resumen del
    # registro aprendió a no promediar las dos semánticas. El gate nunca se enteró.
    coverage_kind: str = "fraccion_real_del_indice"

    # Solo con `coverage_kind` de instrumento: la cobertura sobre lo MEDIBLE, que es la que
    # puntúa. Excluye del denominador las unidades que ningún esfuerzo nuestro puede medir
    # porque el impedimento está en el instrumento evaluado.
    #
    # Lo excluido NO desaparece: `coverage` sigue reportando la cobertura cruda sobre el
    # universo entero, las dos viajan al detalle del gate, y el informe LISTA lo excluido.
    # Un descuento silencioso sería peor que el castigo que vino a corregir.
    coverage_efectiva: Optional[float] = None
    # El desglose, para que el linaje del gate se pueda escribir y nadie tenga que creerlo.
    universo: Optional[int] = None                    # unidades que el instrumento fija
    medidas: Optional[int] = None                     # las que este producto mide
    imposibles_por_el_instrumento: Optional[int] = None


# Obstáculos por los que un eje NO puede tener backtest de discriminación. Son categorías
# estructurales —no estados del dato de hoy—, así que no envejecen con una corrida.
OBSTACULOS_BACKTEST = (
    # El índice tiene UN solo sujeto (el país): no hay corte transversal que ordenar, y un
    # Gini o un IC de rango necesitan algo que rankear. Es el caso de los índices nacionales
    # de un sector (turismo, energía, telecom, construcción, zonas francas).
    "sin_corte_transversal",
    # El desenlace es lo que el propio eje mide, así que compararlos no valida nada.
    "autoreferencial",
    # Habría desenlace y habría corte, pero falta el dato. `dato_que_falta` lo nombra.
    "dato_pendiente",
)


@dataclass(frozen=True)
class EstadoBacktest:
    """Qué puede afirmar el eje sobre su validación retrospectiva, y POR QUÉ.

    Declara los hechos de DISEÑO, no el veredicto de la última corrida: si el eje tiene o no
    motor, contra qué desenlace se mide (o se mediría) y, cuando no lo tiene, qué se lo
    impide. El veredicto —concluyente, no concluyente, invertido— vive en el reporte y se
    lee de ahí; ponerlo acá lo congelaría, que es el defecto que este plan vino a cerrar.

    Un eje sin motor y sin obstáculo declarado no es «pendiente»: es un hueco, y el test
    estructural lo rechaza.
    """

    tiene_motor: bool
    motivo: str                              # por qué no lo tiene, o cómo se lee el que tiene
    desenlace: Optional[str] = None          # contra qué se mide (o se mediría)
    obstaculo: Optional[str] = None          # uno de OBSTACULOS_BACKTEST cuando no hay motor
    dato_que_falta: Optional[str] = None     # obligatorio si obstaculo == "dato_pendiente"
    eje_motor: Optional[str] = None          # clave en shared.validation.frescura.MOTORES


@dataclass(frozen=True)
class ValidationState:
    """Estado de validación/QA + doctrina del sector (alimenta G5 · Validación)."""

    approved: bool                # doctrina firmada / QA aprobado
    score: float = 0.0            # [0,1] — fuerza de la validación (backtest, outcomes)
    notes: str = ""
    # Estado ESTRUCTURAL de la validación retrospectiva. Opcional en el tipo para no romper
    # a quien construya un ValidationState suelto; obligatorio en los productos del catálogo,
    # donde lo exige `shared/products/tests/test_estado_de_validacion.py`.
    backtest: Optional[EstadoBacktest] = None


@dataclass(frozen=True)
class CanonicalSeries:
    """Descriptor de UNA serie canónica normalizada que el sector publica.

    Es el átomo de la Data API (docs/SPEC_API_DATOS_PROPIETARIOS.md §3): el manifiesto
    de exposición recorre el catálogo pidiendo ``canonical_series()`` y publica lo que
    encuentre — por eso una serie nueva se expone sin tocar la capa API.

    ``license`` es OBLIGATORIO en la práctica: una serie sin licencia declarada queda en
    **cuarentena** (no se sirve). Es deliberado y conservador — misma doctrina que
    ``normalize_state``, que asume GAP ante lo desconocido: no se redistribuye lo que no
    consta que se pueda redistribuir.
    """

    code: str                             # clave estable, p.ej. "gdp_growth"
    label: str                            # etiqueta legible
    unit: Optional[str] = None
    frequency: str = "unknown"            # monthly | quarterly | annual | unknown
    source: str = ""                      # emisor: "BCRD", "SIB", "SIPEN"…
    license: Optional[str] = None         # None ⇒ cuarentena (no se expone)
    # QUÉ es el valor respecto de la fuente. Decide si servirlo es redistribuir o no:
    #   "verbatim" — el valor del emisor, normalizado (período canónico, unidad, linaje).
    #                Servirlo ES redistribuir → lo alcanza la licencia de la fuente.
    #   "derived"  — cálculo de casa sobre uno o más insumos (índice, score, tasa
    #                deflactada, brecha). Es obra propia: una restricción no-comercial
    #                del insumo no impide servir el RESULTADO, aunque sí obliga a citar.
    # Default "verbatim" a propósito: ante la duda se asume lo más restrictivo, igual
    # que ``normalize_state`` asume GAP.
    derivation: str = "verbatim"
    # ¿Es una serie CURADA —elegida, nombrada y validada por un analista— o un volcado
    # masivo de planilla? Las dos son dato real; solo una es citable en un informe a
    # cliente. Sin esta distinción, un consumidor no puede saber cuál de dos series
    # parecidas es la autoritativa, y termina citando la ruta de una hoja de cálculo.
    curated: bool = False
    # QUÉ TIPO DE MAGNITUD mide: flow | stock | rate | index | unknown. Decide qué
    # transformación es válida — una serie `rate` ya es un porcentaje y su variación se
    # mide en PUNTOS, no en porcentaje sobre porcentaje. Sin esto, el consumidor adivina.
    nature: str = "unknown"
    period_first: Optional[str] = None
    period_latest: Optional[str] = None
    n_obs: int = 0
    note: str = ""


@dataclass(frozen=True)
class SeriesObservation:
    """Una observación de una serie canónica, con su linaje mínimo."""

    period: str                           # "2025", "2025-Q1", "2025-01"
    value: Optional[float]                # None = falta el dato (NUNCA se imputa)
    unit: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[str] = None    # ISO date de publicación del emisor
    reason: Optional[str] = None          # por qué falta, cuando ``value`` es None


@dataclass(frozen=True)
class CanonicalScore:
    """Descriptor de UN score/índice propietario que el sector publica por la Data API.

    Cubre tanto el score de entidad (ISA de un banco) como el índice de país en panel
    (IRMP, IRC): la diferencia es el ``subject_kind``. Los scores son cálculo de casa —
    obra propia — así que NO llevan licencia de emisor: su "licencia" es la de SDQ, y la
    cuarentena del manifiesto les aplica solo activación + readiness.
    """

    code: str                             # "irmp" · "irc" · "isa"
    label: str                            # "Índice de Riesgo Macro-Político"
    subject_kind: str = "entity"          # "entity" | "country" | "sector" | "system"
    direction: str = ""                   # "mayor score = menor riesgo" (¡obligatoria en la práctica!)
    scale: str = "0-100"
    method_version: Optional[str] = None
    subjects: Tuple[str, ...] = ()        # sujetos con score persistido ("DOM", "PER"…)
    period_latest: Optional[str] = None
    # Períodos con score persistido, ascendentes. Declararlos hace VISIBLE la
    # discontinuidad: sin esto, un consumidor que grafica la tendencia no puede
    # distinguir "ese año no existe dato" de "ese año no se computó todavía", y
    # dibuja una línea continua sobre un hueco. La misma doctrina del nulo honesto,
    # aplicada al eje del tiempo.
    periods: Tuple[str, ...] = ()
    n_obs: int = 0
    note: str = ""


@dataclass(frozen=True)
class ScoreObservation:
    """Un score computado para un sujeto y período, con su desglose dimensional."""

    subject: str                          # ISO3 / entity_key / sector slug
    period: str
    score: Optional[float]
    band: Optional[str] = None
    # ``{dimension: {score, weight, contribution}}`` — el desglose explicable. Nunca se
    # sirve la narrativa (esa es el producto de reporte); el desglose numérico sí.
    dimensions: Optional[Dict] = None
    model_version: Optional[str] = None
    reason: Optional[str] = None          # por qué falta, cuando ``score`` es None
    # Tamaño del panel contra el que se normalizó. En un índice panel-relativo (min-max
    # contra el conjunto de pares) el score DEPENDE de con quién se comparó: dos períodos
    # calculados sobre paneles distintos NO son comparables entre sí, aunque ambos se vean
    # como un número en la misma escala. Declararlo es lo que permite detectarlo.
    peer_set_size: Optional[int] = None


@dataclass(frozen=True)
class CanonicalForecast:
    """Descriptor de UN modelo de pronóstico que el sector publica, con su track record.

    Es el activo más defendible del catálogo: el acierto es **verificable** — cada
    pronóstico se congela ANTES del hecho y se puntúa contra el resultado publicado por
    la fuente oficial. Por eso el descriptor lleva las métricas acumuladas: un cliente
    debe poder juzgar el modelo antes de usarlo, no después.
    """

    code: str                             # "tpm"
    label: str                            # "Decisión de política monetaria (TPM)"
    target: str = ""                      # qué se pronostica, en prosa llana
    horizon: str = ""                     # "próxima reunión de la Junta Monetaria"
    classes: Tuple[str, ...] = ()         # ("cut", "hold", "hike") si es clasificador
    model_version: Optional[str] = None
    n_scored: int = 0                     # pronósticos ya puntuados (la muestra viva)
    hit_rate: Optional[float] = None      # aciertos / puntuados
    brier: Optional[float] = None         # Brier medio multiclase (menor = mejor)
    baseline: Optional[str] = None        # con qué compararlo para que la cifra signifique algo
    note: str = ""


@dataclass(frozen=True)
class ForecastObservation:
    """Un pronóstico congelado y —si ya ocurrió— su resultado real.

    ``status`` distingue el pronóstico VIGENTE (``pending``, aún sin resolver) del
    histórico puntuado (``scored``). Nunca se reescribe un pronóstico viejo: ese es el
    punto de un track record honesto.
    """

    as_of: str                            # fecha en que se emitió (ISO)
    status: str = "pending"               # "pending" | "scored"
    predicted: Optional[str] = None
    probabilities: Optional[Dict] = None  # {clase: prob}
    implied_level: Optional[float] = None # lectura continua (p.ej. tasa de la regla de Taylor)
    realized: Optional[str] = None        # lo que efectivamente ocurrió
    realized_level: Optional[float] = None
    realized_date: Optional[str] = None
    correct: Optional[bool] = None
    brier: Optional[float] = None
    level_abs_error: Optional[float] = None
    model_version: Optional[str] = None


@dataclass(frozen=True)
class SignalItem:
    """Una señal determinista (alerta temprana / precursor) emitida por el motor.

    Es la salida del motor de reglas, no juicio de IA — por eso es exportable: el
    veredicto numérico-determinista viaja; la lectura narrativa queda en el reporte.
    """

    key: str                              # identificador estable de la regla
    label: str                            # legible: "Aceleración de deuda pública"
    severity: str = "info"                # "info" | "watch" | "alert"
    period: Optional[str] = None
    subject: Optional[str] = None
    detail: str = ""                      # dato que la disparó (determinista, citable)


@dataclass(frozen=True)
class ProductSnapshot:
    """Datos ya calculados que un nivel necesita para narrar y renderizar.

    Estructura deliberadamente abierta (``payload``) porque cada sector tiene su
    propia forma de scoring; lo común es el sobre: granularidad, período y, para
    Insight/Deep Dive, la entidad nombrada. Para Pulse (``system``) ``entity_name``
    DEBE ser ``None`` y el ``payload`` no debe contener identificadores (lo verifica
    el sensor de anonimización en el ensamblador).
    """

    tier: ProductTier
    period: str
    payload: Dict
    entity_name: Optional[str] = None
    # Roster de entidades del sector — el sensor de anonimización Pulse lo usa para
    # verificar que ningún nombre se filtró al agregado de sistema.
    entity_roster: Tuple[str, ...] = field(default=())


@runtime_checkable
class SectorProduct(Protocol):
    """Lo que cada módulo de sector expone al framework de productos.

    El ensamblador genérico (``assembler.assemble_product_report``) orquesta usando
    SOLO estos métodos; nunca conoce el sector concreto.
    """

    sector_key: str  # "banking", "macro", ...

    def product_manifest(self) -> SectorProductManifest:
        """Manifiesto declarativo de los 3 niveles del sector."""
        ...

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth: ...
    def has_engine(self) -> bool: ...
    def validation_state(self) -> ValidationState: ...

    # ── Producción de reporte por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        """Datos del nivel: agregado anonimizado (Pulse) o entidad nombrada.

        Invariante del contrato: ``period`` vacío (``""``) o no resoluble significa
        "último período disponible" (la entrega comercial pasa ``""`` cuando el cliente
        no especifica). Un ``scope`` ausente en un nivel nombrado debe lanzar
        ``ValueError`` (español); el ensamblador lo traduce a 422.
        """
        ...

    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        """``{section_key: texto}`` para las secciones del nivel (vía el motor compartido)."""
        ...

    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None,
                     fmt: str = "pdf") -> str:
        """Renderiza el reporte del nivel y devuelve el path. ``fmt`` = "pdf" | "docx"
        (misma anatomía de marca, ver docs/REPORT_STANDARD.md). Reusa building blocks."""
        ...

    # ── Muestra de conversión (OPCIONAL) ──
    # Un sector PUEDE implementar ``sample_snapshot(tier) -> ProductSnapshot`` con datos
    # demo SINTÉTICOS (sin DB, sin entidad real) para la muestra descargable watermarked.
    # No está en el Protocol como obligatorio: ``assembler.supports_sample`` lo detecta y
    # los sectores que aún no lo implementan simplemente no ofrecen muestra.

    # ── Entidades elegibles de los niveles nombrados (OPCIONAL) ──
    # Un sector con un sujeto ELEGIBLE en sus niveles nombrados (Insight / Deep Dive) PUEDE
    # implementar ``scope_options() -> List[ScopeOption]`` para alimentar el selector del
    # catálogo. Cada opción es ``{"value": <lo que acepta snapshot(scope=…)>, "label":
    # <visible>, "group": <agrupador key, p.ej. tipo o región>}``. No está en el Protocol
    # como obligatorio: el catálogo lo detecta por ``getattr``. Un producto de sujeto FIJO
    # (sector/país nacional único) NO lo implementa → su nivel nombrado carga directo.
    #
    # ``scope_kind() -> str`` (OPCIONAL, default "entity") declara QUÉ se elige, para el
    # rótulo correcto del catálogo: "entity" (banco) o "country" (país de un panel: macro/ESG,
    # índices de riesgo-país). El catálogo lo detecta por ``getattr``.

    # ── Señal por-variable para el Data Registry (OPCIONAL) ──
    # Un producto PUEDE implementar ``variable_signals() -> {"period": str|None,
    # "signals": List[VariableSignal]}`` (o directamente ``List[VariableSignal]``) para
    # exponer su procedencia POR-VARIABLE (estado real/rúbrica/brecha + peso + fuente +
    # cadencia) al Data Registry del motor de research (``shared/registry``). Se detecta
    # por ``getattr``; un producto que no lo implemente degrada con honestidad a su
    # ``data_signals`` a-nivel-producto. Construir las señales con los helpers de
    # ``shared/registry/builders`` (``pattern_a_signals`` para paneles con mapa
    # ``sources``; ``pattern_b_signals`` para índices con ``breakdown.provenance``) —
    # NO duplicar la normalización. Ver docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.1.

    # ── Series canónicas para la Data API (OPCIONAL) ──
    # Un producto PUEDE implementar el par:
    #   ``canonical_series() -> Iterable[CanonicalSeries]``
    #   ``series_observations(code, *, start=None, end=None, limit=None)
    #        -> Iterable[SeriesObservation]``
    # para publicar sus series normalizadas por la Data API. Se detecta por ``getattr``;
    # un producto que no lo implemente simplemente no aporta series (brecha honesta, no
    # error). Implementar SIEMPRE los dos: un descriptor sin lector es una serie que el
    # catálogo anuncia y nadie puede leer, y el manifiesto lo trata como cuarentena.
    # Ver docs/SPEC_API_DATOS_PROPIETARIOS.md §3.

    # ── Scores y señales para la Data API (OPCIONAL — Fase 2) ──
    # Análogo al par de series, con la misma regla (implementar descriptor Y lector):
    #   ``canonical_scores() -> Iterable[CanonicalScore]``
    #   ``score_observations(code, *, subject=None, start=None, end=None, limit=None)
    #        -> Iterable[ScoreObservation]``
    #   ``canonical_signals(limit=None) -> Iterable[SignalItem]``   (independiente)
    #   ``canonical_forecasts() -> Iterable[CanonicalForecast]``     (Fase 3)
    #   ``forecast_observations(code, *, limit=None) -> Iterable[ForecastObservation]``
    # El desglose dimensional numérico SÍ viaja; la narrativa NUNCA (es el producto de
    # reporte). Un producto que no los implemente no aporta scores/señales — brecha
    # honesta, no error.


def required_signal_methods() -> List[str]:
    """Métodos que un sector debe implementar para el monitor (test de contrato)."""
    return ["product_manifest", "data_signals", "has_engine", "validation_state",
            "snapshot", "narratives", "render"]
