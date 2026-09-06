"""Esquema normalizado de la señal por-variable + helpers de construcción.

El vocabulario del sistema tiene HOY dos dialectos (ver docstring del paquete):
mapas ``sources`` con "live"/"rubric" (paneles) y ``breakdown.provenance`` con
"real"/"brecha" (índices). Aquí se unifican en tres estados canónicos —los mismos
tres que el REPORT_STANDARD y el §4 del spec del motor exigen declarar:

    REAL   — dato real con lineage (fuente + fecha).           ("live" | "real")
    RUBRIC — rúbrica declarada (juicio de casa, no dato).      ("rubric")
    GAP    — brecha declarada (sin dato ni rúbrica hoy).       ("brecha" | ausente)

``real_fraction`` guarda la verdad cuantitativa cuando una variable de PANEL es real
para unos sujetos y no para otros (p.ej. rentabilidad ENAE cubre ~9/17 sectores): el
estado sigue siendo REAL —está anclado a dato— pero la fracción lo declara sin
maquillar. El gate de honestidad de la Fase 4 pondera con esa fracción, no solo con
la categoría.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# ─── Estados canónicos ────────────────────────────────────────────────
REAL = "real"       # dato real con lineage
RUBRIC = "rubric"   # rúbrica declarada
#: Proyección DECLARADA con backtest. El cuarto estado, entre «tengo el dato» y «declaro la
#: brecha»: existe para que una pregunta prospectiva pueda anclarse en un pronóstico
#: puntuado en vez de morir en brecha. Ancla SOLO si pasa `registry.projection`; si no, se
#: degrada a GAP con el motivo escrito. Y no suma a `coverage_real`: ver `coverage_projected`.
PROJECTED = "projected"
GAP = "gap"         # brecha declarada

#: Los cuatro, en orden de fuerza epistémica.
STATES = (REAL, RUBRIC, PROJECTED, GAP)

# ─── Alcance de la medición (ver ``VariableSignal.scope``) ────────────
PER_SUBJECT = "per_subject"   # se mide por sujeto → diferencia entre ellos
NATIONAL = "national"         # dato real de alcance país → igual para todos los sujetos

# ─── Qué MIDE la cobertura de un eje (ver ``AxisRegistry.coverage_kind``) ────────────
#
# Hasta que entró el eje de evaluación de leyes, todos los ejes respondían la misma
# pregunta: «¿qué fracción del PESO de mi índice está anclada a dato real?». El eje de
# leyes responde otra: «¿cuántos de los indicadores que la LEY se fijó estamos midiendo?».
# Las dos son fracciones entre 0 y 1 y ninguna es más honesta que la otra — pero
# promediarlas produce un número que no significa nada, y ese número alimentaba el
# resumen del registro.
#
# Es la doctrina de «solo se ordena lo comparable» aplicada a los ejes en vez de a un
# panel de pares: el promedio se computa sobre los comparables, y los de otra semántica
# NO se ocultan (eso los haría desaparecer sin aviso) — van aparte y marcados.
COVERAGE_INDEX = "fraccion_real_del_indice"
COVERAGE_INSTRUMENT = "indicadores_medidos_del_instrumento"
#: El eje PROSPECTIVO responde una tercera pregunta, y tampoco es más ni menos honesta
#: que las otras dos: «¿qué fracción de lo que publico está sostenida por un pronóstico
#: ADMISIBLE o por una cifra determinada?». Su índice no está hecho de dato medido —ES
#: la proyección—, así que la frase de índice le hace decir algo falso: el informe del
#: 2026-09-05 publicó «100% del índice se construye sobre dato real medido en la fuente»
#: cuatro líneas antes de declarar, computado, que el 0% se sostiene en dato real.
COVERAGE_PROJECTION = "fraccion_proyectada_admisible"
#: El eje de VALUACIÓN responde una cuarta: «¿qué fracción de los insumos del modelo está
#: presente en la fuente al corte?». No arma un índice —arma un valor— y su insumo central,
#: el costo de capital, es en parte supuesto declarado (beta y prima de riesgo). La frase de
#: índice le hacía decir «100 % dato real» en la misma página en que declaraba, computado, que
#: el 37 % del Ke es rúbrica (Deep Dive de Banco Popular, 2026-09-06).
COVERAGE_INPUTS = "insumos_presentes_del_modelo"
COVERAGE_KINDS = (COVERAGE_INDEX, COVERAGE_INSTRUMENT, COVERAGE_PROJECTION, COVERAGE_INPUTS)

_STATE_ALIASES = {
    "live": REAL, "real": REAL,
    "rubric": RUBRIC, "rúbrica": RUBRIC,
    "brecha": GAP, "gap": GAP, "": GAP, "absent": GAP, "missing": GAP,
    "projected": PROJECTED, "proyeccion": PROJECTED, "proyección": PROJECTED,
    "forecast": PROJECTED, "nowcast": PROJECTED,
}


def normalize_state(raw: Optional[str]) -> str:
    """Mapea cualquiera de los dialectos ("live"/"rubric"/"brecha"/…) al canónico.

    Desconocido o ``None`` → ``GAP`` (conservador: si no sabemos que hay dato, se
    declara brecha; nunca se asume real por omisión — esa es la regla dura del §4)."""
    if raw is None:
        return GAP
    return _STATE_ALIASES.get(str(raw).strip().lower(), GAP)


@dataclass(frozen=True)
class ProjectionMeta:
    """Lo que una proyección tiene que declarar para poder anclar algo.

    Opcional en el tipo y OBLIGATORIO en el gate: una señal puede no traerla, pero una señal
    `PROJECTED` sin esto no ancla nada. Lo que está acá es lo mínimo para que un lector pueda
    juzgar el pronóstico en vez de creerle.

    **Un solo campo de versión.** `model_id` lleva modelo, variante y versión juntos
    (`bridge_imae_pib.m2.v1`). Un `model_version` aparte versionaría lo mismo dos veces y
    admitiría que se contradigan; y la variante de un nowcast ES un modelo distinto, con su
    propio backtest.

    **`interval_coverage` no es opcional.** Un modelo cuyo intervalo del 80% acierta el 45%
    de las veces está mal calibrado aunque su RMSE sea bajo. Sin este campo la calibración no
    tiene cómo llegar al informe.

    **`as_of` tampoco es decorativo.** Sin corte point-in-time no se distingue un pronóstico
    de un ajuste hecho con información posterior — que es la diferencia entre un track record
    y un autoengaño.

    **Y `measure` tampoco.** `target_series` dice CONTRA QUÉ se va a puntuar el punto;
    `measure`, en qué unidad está. Son dos declaraciones distintas y hacen falta las dos: un
    pronóstico de la VARIACIÓN de un índice es una tasa sobre una serie de nivel, y sin la
    segunda cada consumidor vuelve a adivinar.
    """

    model_id: str            # modelo + variante + versión, en un solo identificador
    target_series: str       # series_code proyectado
    horizon: str             # "2026-Q4" | "+1T" | "+4T"
    as_of: str               # corte point-in-time de la información usada
    revision: int            # 0 = como se publicó; 1+ = corrección posterior
    point: float             # la estimación central
    #: **En qué medida están `point` y los `intervals`** — el vocabulario lo declara
    #: `shared.data.medida_de_pronostico` (`level` | `dlog_pct`). No tiene default a
    #: propósito: el ledger ya aprendió que suponer la unidad de un punto cuesta caro
    #: —comparó un Δlog en % (~0,4) contra un índice de volumen (~133) y el error salió
    #: 132,75—, y un default reintroduce la suposición un salto más adelante. Sin esto, la
    #: señal proyectada llegaba al registro como «bcrd.xls.pib_2018.serie_original_indice ·
    #: proyección 2026-Q3 = 0,38»: una TASA rotulada con el nombre de una serie de NIVEL.
    measure: str
    #: ``((nivel, lo, hi), …)`` — p.ej. ``((0.80, 3.1, 4.7), (0.90, 2.6, 5.2))``
    intervals: Tuple[Tuple[float, float, float], ...]
    #: La clave del CONJUNTO de pronósticos comparables. La arma `backtest_id()`, unas
    #: líneas más abajo — no se compone a mano en ningún lado.
    backtest_id: str
    oos_error: float         # error fuera de muestra del backtest citado
    error_metric: str        # "rmse" | "mae" — nombrada, nunca inferida
    n_oos: int               # observaciones fuera de muestra que sostienen ese error
    #: ¿Las ventanas del backtest se solapan? Doce pronósticos a ocho trimestres tomados
    #: trimestre a trimestre comparten información y no son doce observaciones
    #: independientes. No se corrige el conteo con una fórmula inventada: se DECLARA. El
    #: gate exige que esté seteado — ``None`` es rechazo.
    n_oos_overlapping: Optional[bool]
    #: ``((nivel, cobertura_observada, n), …)`` — la calibración empírica del intervalo.
    interval_coverage: Tuple[Tuple[float, float, int], ...] = ()


def backtest_id(model_id: str, target_series: str, measure: str,
                h: Optional[int]) -> str:
    """La clave del conjunto sobre el que se computa el error de un modelo.

    **Un solo constructor, y vive acá.** Había dos —el ledger y el motor del BVAR— armando la
    misma cadena por su cuenta; una copia a mano de un serializador ya borró la tasa de 38
    entidades en este repo, y si estas dos divergen la meta apunta a un conjunto vacío y la
    proyección no ancla nunca. Vive en `shared/` y no en el módulo porque `ProjectionMeta`
    —el tipo que la transporta— vive acá.

    Los cuatro campos, y cada uno está porque su ausencia rompió algo:

    * **`h` es el horizonte RELATIVO**, no el trimestre calendario. Con el calendario, cada
      conjunto tiene UNA observación —un trimestre se pronostica una vez a cada distancia— y
      `n_oos` nunca llega al mínimo del gate. Medido: doce trimestres emitidos a un trimestre
      vista y puntuados dan `n_oos = 1` con el calendario y **12** con el relativo.
    * **`measure`**, porque un modelo puede cambiar de unidad y partir su propio track record
      en dos poblaciones. Pasó: el bloque del BVAR pasó de variación trimestral a interanual
      el 2026-09-05, y sin este campo el pronóstico de esa mañana (trimestral) y los de esa
      tarde (interanuales) caían en el mismo conjunto. Medido sobre dos filas con errores de
      0,50 y 4,00, el RMSE publicado era **2,850** — que no es el error de ninguno de los
      dos. Es «solo se ordena lo comparable» sobre el eje del tiempo.

    Con *h* en ``None`` abarca TODOS los horizontes de ese modelo y esa medida, que mezcla
    pronósticos de dificultad distinta: sirve para un total, no para juzgar calibración.
    Mezclar dificultades es una decisión declarada; mezclar unidades es un error, y por eso
    la medida NO tiene comodín.

    ``h is not None``, no ``if h``: el nowcast apunta al trimestre EN CURSO y su horizonte
    relativo es CERO, que es falsy. Con ``if h`` habría caído al comodín y su track record se
    habría mezclado con el de los horizontes largos.
    """
    paso = f"+{h}T" if h is not None else "*"
    return f"{model_id}|{target_series}|{measure}|{paso}"


@dataclass(frozen=True)
class VariableSignal:
    """La señal atómica del registro: una variable de un eje y su procedencia real.

    ``weight`` es el peso de la variable dentro del índice del eje [0,1] (de la
    doctrina versionada); ``0.0`` si el eje no expone pesos por-variable. ``value``
    es indicativo (para un panel multi-sujeto suele ser ``None`` — el valor es
    per-sujeto, no del eje). Lo que importa para el motor de research es
    ``state`` + ``source`` + ``cadence`` + ``real_fraction``.
    """

    key: str                         # clave de la variable, p.ej. "regulatory_quality"
    label: str                       # etiqueta legible
    state: str                       # REAL | RUBRIC | GAP
    dimension: str = ""              # dimensión/grupo del índice al que pertenece
    weight: float = 0.0              # peso en el índice [0,1] (doctrina)
    source: str = ""                 # lineage: fuente que respalda el dato real
    cadence: str = "unknown"         # monthly | quarterly | annual | unknown
    value: Optional[float] = None    # valor indicativo (None en paneles multi-sujeto)
    # Período AL QUE PERTENECE ``value``, cuando no es el del eje. Un eje publica UN
    # período, pero no todas sus variables se actualizan a la vez: la razón de ocupación
    # femenina/masculina traía 2025 y el eje social iba por 2024, así que el registro
    # servía un valor de 2025 rotulado 2024. Para un informe que juzga contra la meta de
    # un año concreto, eso no es un detalle de metadatos: es la cifra equivocada.
    # ``None`` = el del eje, que es el caso de la mayoría y no obliga a nadie a declararlo.
    period: Optional[str] = None
    # SERIE COMPLETA `[(período, valor)]` ascendente, cuando el eje puede servirla.
    # Vacía = el eje publica un punto y nada más; NO significa que la serie no exista.
    #
    # ⛔ Solo para señales de alcance NATIONAL. La historia de una variable por-sujeto sería
    # la de UN sujeto, y eso es el defecto de `sample_value` repetido sobre el eje del
    # tiempo — peor, porque un punto suelto se compara contra una meta y ya, mientras que
    # una trayectoria falsa afirma una DIRECCIÓN: «mejora», «retrocede». El consumidor que
    # lee «retrocede» no tiene forma de sospechar que es una región y no el país.
    #
    # El último par tiene que coincidir con ``value``/``period``: son la misma verdad
    # expresada dos veces, y el día que difieran gana la que el consumidor mire primero.
    history: Tuple[Tuple[str, float], ...] = ()
    real_fraction: float = field(default=1.0)  # fracción de sujetos con dato real [0,1]
    note: str = ""                   # nota de trazabilidad (parcialidad, caveat)
    # ALCANCE de la medición — distingue dos cosas que "dato real" confunde:
    #   PER_SUBJECT — se mide por sujeto (sector, país, entidad): DIFERENCIA entre ellos
    #                 y por tanto mueve el ranking.
    #   NATIONAL    — dato real, pero de alcance país: idéntico para todos los sujetos del
    #                 panel. Sostiene el nivel del índice; NO mueve el ranking.
    # Sin este eje, un cliente lee "dato real" y entiende "esto distingue a mi sector de
    # los demás", que puede ser falso. Default PER_SUBJECT (el caso común); un producto
    # con variables nacionales lo declara explícitamente.
    scope: str = "per_subject"
    #: La proyección que sostiene esta señal, cuando ``state == PROJECTED``. Opcional en el
    #: tipo; el gate la exige. Ver `shared.registry.projection`.
    projection: Optional[ProjectionMeta] = None


@dataclass(frozen=True)
class AxisRegistry:
    """Todo lo que un eje/producto mide, normalizado. Unidad de agregación del registro."""

    sector_key: str
    display_name: str
    source: str                      # fuente autoritativa del eje (catálogo)
    implemented: bool
    degraded: bool = False           # cayó al fallback a-nivel-producto (sin variable_signals)
    period: Optional[str] = None
    signals: Tuple[VariableSignal, ...] = ()
    note: str = ""
    #: Qué responde ``coverage_real`` en ESTE eje. Por defecto la pregunta de siempre, así
    #: que ningún eje existente cambia de significado al agregarse el campo.
    coverage_kind: str = COVERAGE_INDEX

    # ── Métricas derivadas (no se guardan crudas: se calculan de las señales) ──
    @property
    def coverage_real(self) -> float:
        """Fracción del PESO del índice anclada a dato real (ponderada por
        ``real_fraction``). Si el eje no expone pesos, cae a promedio simple por
        variable. Es la métrica que alimenta el gate de honestidad (§3.4/§4)."""
        if not self.signals:
            return 0.0
        wsum = sum(s.weight for s in self.signals)
        if wsum > 0:
            got = sum(s.weight * _real_credit(s) for s in self.signals)
            return round(got / wsum, 4)
        # sin pesos: promedio simple del crédito real por variable
        return round(sum(_real_credit(s) for s in self.signals) / len(self.signals), 4)

    @property
    def coverage_anclada(self) -> float:
        """Real + proyectada: la fracción anclada de CUALQUIER manera. Solo tiene sentido
        para un eje de semántica `COVERAGE_PROJECTION`.

        Para un índice, sumarlas estaría mal y por eso `coverage_projected` se documenta como
        HERMANA y no como sumando: una proyección no puede inflar la métrica con la que la
        plataforma dice cuánto de un índice está sostenido por dato real. Pero un eje cuyo
        índice ES la proyección responde otra pregunta —«¿qué fracción de lo que publico está
        anclada?»— y ahí la suma es la respuesta correcta. Existe con nombre propio, y no
        como una suma suelta en quien la necesite, para que la distinción quede a la vista.
        """
        return round(self.coverage_real + self.coverage_projected, 4)

    @property
    def coverage_projected(self) -> float:
        """Fracción del peso del índice sostenida por PROYECCIÓN declarada.

        Propiedad HERMANA de `coverage_real`, no un reemplazo ni un sumando: se reporta al
        lado. Una proyección puede anclar una pregunta prospectiva; lo que no puede es
        inflar la métrica con la que la plataforma dice cuánto de un índice está sostenido
        por dato real. Un producto que hoy reporta 62% sigue reportando 62%.
        """
        if not self.signals:
            return 0.0
        wsum = sum(s.weight for s in self.signals)
        if wsum > 0:
            got = sum(s.weight * _projected_credit(s) for s in self.signals)
            return round(got / wsum, 4)
        return round(sum(_projected_credit(s) for s in self.signals) / len(self.signals), 4)

    @property
    def state_counts(self) -> Dict[str, int]:
        # Las CUATRO claves siempre: un eje sin proyecciones dice `projected: 0`, y no omite
        # la clave. Una clave ausente se lee como «no aplica», que es otra cosa que «cero».
        counts = {REAL: 0, RUBRIC: 0, PROJECTED: 0, GAP: 0}
        for s in self.signals:
            counts[s.state] = counts.get(s.state, 0) + 1
        return counts


def _real_credit(s: VariableSignal) -> float:
    """Crédito de "realidad" de una señal para la cobertura ponderada: una variable
    REAL aporta su ``real_fraction`` (parcial cuenta parcial); RUBRIC/GAP aportan 0
    —una rúbrica no es dato, aunque sea un juicio declarado y honesto."""
    return s.real_fraction if s.state == REAL else 0.0


def _projected_credit(s: VariableSignal) -> float:
    """Crédito de PROYECCIÓN de una señal, simétrico con :func:`_real_credit`.

    Usa ``real_fraction`` y no un ``1.0`` plano: en un panel donde solo algunos sujetos se
    proyectan, una señal parcialmente cubierta cuenta parcialmente. Un ``1.0`` plano
    sobreestimaría la cobertura proyectada — el mismo error que el registro evita del lado
    real."""
    return s.real_fraction if s.state == PROJECTED else 0.0


@dataclass(frozen=True)
class DataRegistry:
    """El registro completo: todos los ejes + un resumen de portafolio."""

    generated_at: str
    axes: Tuple[AxisRegistry, ...] = ()

    @property
    def summary(self) -> Dict:
        implemented = [a for a in self.axes if a.implemented]
        total_signals = sum(len(a.signals) for a in self.axes)
        by_state = {REAL: 0, RUBRIC: 0, PROJECTED: 0, GAP: 0}
        for a in self.axes:
            for k, v in a.state_counts.items():
                by_state[k] = by_state.get(k, 0) + v
        # El promedio se computa SOLO sobre los ejes cuya cobertura mide lo mismo. Mezclar
        # «fracción real del índice» con «indicadores medidos de una ley» daba un número sin
        # significado: al entrar el eje de leyes con 5 de 90, el promedio de la plataforma
        # caía sin que ningún índice hubiera perdido un solo dato real.
        con_senales = [a for a in implemented if a.signals]
        comparables = [a for a in con_senales if a.coverage_kind == COVERAGE_INDEX]
        cov = [a.coverage_real for a in comparables]
        cov_proj = [a.coverage_projected for a in comparables]
        # Los de otra semántica van APARTE y marcados, nunca omitidos: omitirlos los haría
        # desaparecer del resumen sin aviso, que es peor que promediarlos mal.
        otros = [
            {"sector_key": a.sector_key, "coverage_kind": a.coverage_kind,
             "coverage": a.coverage_real}
            for a in con_senales if a.coverage_kind != COVERAGE_INDEX
        ]
        return {
            "axes_total": len(self.axes),
            "axes_implemented": len(implemented),
            "axes_degraded": len([a for a in self.axes if a.degraded]),
            "variables_total": total_signals,
            "by_state": by_state,
            "coverage_real_mean": round(sum(cov) / len(cov), 4) if cov else 0.0,
            # Al lado, nunca sumada. Ver `AxisRegistry.coverage_projected`.
            "coverage_projected_mean": (round(sum(cov_proj) / len(cov_proj), 4)
                                        if cov_proj else 0.0),
            # Sin este denominador, «cobertura media 62%» no dice sobre cuántos ejes.
            "coverage_real_mean_sobre_ejes": len(cov),
            "coverage_no_comparable": otros,
        }
