"""Proyección de la venta por local: el nivel base del pronóstico. Determinista.

Este motor NO es el de ``forecast.py``. Aquel pronostica indicadores del estudio de
mercado, que son proporciones muestrales con banda de muestreo y una decena de olas. Este
pronostica la venta, que es **censo**: no hay error de muestreo, hay un panel de miles de
jornadas, y la incertidumbre se estima de los errores del propio modelo fuera de muestra.
Copiar la banda del tracker aquí sería inventar una fuente de ruido que no existe.

## La forma del modelo la dictó el dato, no la preferencia

Sobre el panel real del encargo (30 locales × 70 jornadas, junio–agosto de 2026) la
descomposición de la varianza de ``log(venta)`` dio:

* **97 % entre locales.** Es escala, no señal: hay locales tres veces más grandes que
  otros. Se absorbe con un nivel por local y no se pronostica nada con eso.
* **2 % día nacional.** El calendario promocional común **no domina**. Era el riesgo que
  podía volver inútil todo el eje y quedó refutado con el dato en la mano.
* El residuo, ya quitado nivel de local y día nacional, tiene desvío de ~12 % y
  **autocorrelación de +0,54 a siete días**, contra +0,28 a un día.

Ese +0,54 es la conclusión de diseño: lo que queda por explicar es **semanal y propio de
cada local**. Un local de oficinas y uno de plaza comercial tienen picos en días
distintos, y el efecto de día-de-semana promedio de la red no lo captura. Por eso las
reglas candidatas se construyen sobre la celda ``local × día de semana`` y no sobre
``local + día de semana``.

## Tres reglas de disciplina

**La regla se elige por backtest, nunca por preferencia.** Igual que en ``forecast.py``.
Compiten varias candidatas sobre origen móvil y el informe nombra a la ganadora.

**La partición es temporal, jamás aleatoria.** Partir el panel al azar deja que el modelo
vea el futuro de cada local y el error resultante es ficticio. Aquí se entrena hasta un
corte y se predice el tramo siguiente, desplazando el corte.

**Un local es proyectable cuando su pronóstico le gana al promedio del propio local, y
solo entonces.** No hay umbral de calidad inventado: la vara es la alternativa de no hacer
nada. El que no la supera se declara no proyectable con su motivo, en vez de publicar una
cifra que no sostiene ninguna decisión.
"""
from __future__ import annotations

import math
import statistics as stats
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

#: Mínimo de jornadas de un local para intentar proyectarlo. Cuatro semanas es el piso
#: para que cada celda local × día-de-semana tenga más de una observación; por debajo, la
#: celda es un dato suelto disfrazado de promedio.
MIN_DAYS_PER_STORE = 28

#: Jornadas mínimas de entrenamiento antes del primer corte del backtest.
MIN_TRAIN_DAYS = 28

#: Horizonte por defecto. Con setenta jornadas de historia no hay estacionalidad anual
#: estimable, así que proyectar más allá de un par de semanas es extrapolar una tendencia
#: medida sobre diez semanas. ``forecast.py`` ya documenta que la extrapolación de
#: tendencia es la peor de sus reglas sobre este encargo.
DEFAULT_HORIZON_DAYS = 14

#: Percentiles del residuo fuera de muestra que forman la banda publicada.
BAND_LO_PCT = 10.0
BAND_HI_PCT = 90.0

#: Motivos de no proyección. Son texto declarado, no ausencia silenciosa.
REASON_SHORT_HISTORY = "historia_insuficiente"
REASON_NO_LIFT = "no_supera_al_promedio_del_local"
REASON_NO_SCORED = "sin_predicciones_puntuables"


@dataclass(frozen=True)
class Observation:
    """Una jornada de un local. ``value`` es la magnitud a proyectar, en su unidad."""

    store_id: str
    day: date
    value: float


@dataclass(frozen=True)
class VarianceShares:
    """Reparto de la varianza de ``log(valor)``. El diagnóstico que justifica el diseño."""

    n: int
    store_pct: float
    national_day_pct: float
    dow_pct: float
    residual_pct: float
    residual_sd_pct: float
    acf_lag1: Optional[float]
    acf_lag7: Optional[float]
    note: str


@dataclass(frozen=True)
class RuleScore:
    """Error de una regla candidata fuera de muestra."""

    rule: str
    mape: Optional[float]
    n_predictions: int


@dataclass(frozen=True)
class StoreVerdict:
    """Veredicto por local: proyectable con su error, o no proyectable con su motivo."""

    store_id: str
    projectable: bool
    reason: Optional[str]
    mape: Optional[float]
    baseline_mape: Optional[float]
    n_predictions: int
    n_days: int


@dataclass(frozen=True)
class PointProjection:
    """Un punto proyectado con su banda multiplicativa."""

    store_id: str
    day: date
    point: float
    lo: float
    hi: float


@dataclass(frozen=True)
class ProjectionResult:
    rule: str
    horizon_days: int
    overall_mape: Optional[float]
    baseline_mape: Optional[float]
    band_lo_pct: Optional[float]
    band_hi_pct: Optional[float]
    #: Desviación mediana del real respecto del pronóstico, en por ciento. Un modelo
    #: calibrado la tiene cerca de cero.
    bias_pct: Optional[float]
    #: Proporción de jornadas en que el real superó al pronóstico. Calibrado ≈ 50 %.
    share_above_pct: Optional[float]
    ranked_rules: Tuple[RuleScore, ...]
    verdicts: Tuple[StoreVerdict, ...]
    points: Tuple[PointProjection, ...]
    variance: Optional[VarianceShares]
    basis: str


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────

def _usable(observations: Sequence[Observation]) -> List[Observation]:
    """Jornadas con valor estrictamente positivo. Un cero no es una venta baja.

    El tablero del operador emite el mes completo y las jornadas posteriores al corte
    llegan con la venta corriente en cero. En logaritmos un cero no existe, y promediarlo
    hunde la serie sin que ninguna validación estructural lo advierta.
    """
    return [o for o in observations if o.value is not None and o.value > 0]


def _log_panel(observations: Sequence[Observation]) -> Dict[str, Dict[date, float]]:
    panel: Dict[str, Dict[date, float]] = defaultdict(dict)
    for o in observations:
        panel[o.store_id][o.day] = math.log(o.value)
    return dict(panel)


def _mean(values: Sequence[float]) -> Optional[float]:
    return stats.fmean(values) if values else None


def _pvar(values: Sequence[float]) -> float:
    return stats.pvariance(values) if len(values) > 1 else 0.0


def _mape(log_diffs: Sequence[float]) -> Optional[float]:
    """Error absoluto medio relativo al valor REAL, desde la diferencia logarítmica.

    Con ``d = log(real) − log(pronóstico)``, el término del error es
    ``|real − pronóstico| / real = |1 − e^{−d}| = |expm1(−d)|``. El denominador es el real
    y no el pronóstico: un modelo que subestima sistemáticamente saldría premiado si se
    dividiera por su propia cifra.
    """
    if not log_diffs:
        return None
    return stats.fmean(abs(math.expm1(-d)) for d in log_diffs)


# ─────────────────────────────────────────────────────────────────────────────
# Diagnóstico: de dónde viene la variación
# ─────────────────────────────────────────────────────────────────────────────

def variance_decomposition(observations: Sequence[Observation]) -> Optional[VarianceShares]:
    """Reparte la varianza de ``log(valor)`` entre local, día nacional y residuo.

    Es la prueba que decide si el resto del eje tiene margen. Si el día nacional se lleva
    casi todo, la variación entre locales es ruido alrededor de una señal común y ninguna
    capa de intención ni de planes va a aportar por encima. Si el residuo propio de cada
    local conserva estructura, la hay.

    ``residual_pct`` sobre el total suele ser diminuto y **es engañoso leerlo solo**: el
    total está dominado por la escala entre locales, que no es señal. Por eso se reporta
    además ``residual_sd_pct``, que es el tamaño típico del vaivén diario que el modelo
    tiene que capturar, y la autocorrelación, que dice si ese vaivén es predecible.
    """
    usable = _usable(observations)
    if len(usable) < MIN_TRAIN_DAYS:
        return None

    logs = [math.log(o.value) for o in usable]
    grand = stats.fmean(logs)
    total = _pvar(logs)
    if total <= 0:
        return None

    by_store: Dict[str, List[float]] = defaultdict(list)
    by_day: Dict[date, List[float]] = defaultdict(list)
    by_dow: Dict[int, List[float]] = defaultdict(list)
    for o, lv in zip(usable, logs):
        by_store[o.store_id].append(lv)
        by_day[o.day].append(lv)
        by_dow[o.day.weekday()].append(lv)

    store_eff = {k: stats.fmean(v) - grand for k, v in by_store.items()}
    day_eff = {k: stats.fmean(v) - grand for k, v in by_day.items()}
    dow_eff = {k: stats.fmean(v) - grand for k, v in by_dow.items()}

    store_share = _pvar([store_eff[o.store_id] for o in usable]) / total * 100.0
    day_share = _pvar([day_eff[o.day] for o in usable]) / total * 100.0
    dow_share = _pvar([dow_eff[o.day.weekday()] for o in usable]) / total * 100.0

    residuals = [
        lv - grand - store_eff[o.store_id] - day_eff[o.day]
        for o, lv in zip(usable, logs)
    ]
    res_share = _pvar(residuals) / total * 100.0
    res_sd = stats.pstdev(residuals) if len(residuals) > 1 else 0.0

    seq: Dict[str, Dict[date, float]] = defaultdict(dict)
    for o, e in zip(usable, residuals):
        seq[o.store_id][o.day] = e

    note = (
        f"Descomposición sobre {len(usable)} jornadas. El {store_share:.0f}% de la varianza "
        f"es escala entre locales y no es pronosticable; el día común a toda la red explica "
        f"{day_share:.0f}%. El vaivén diario propio de cada local tiene desvío de "
        f"{res_sd * 100:.0f}% y es lo que el modelo debe capturar."
    )

    return VarianceShares(
        n=len(usable),
        store_pct=store_share,
        national_day_pct=day_share,
        dow_pct=dow_share,
        residual_pct=res_share,
        residual_sd_pct=res_sd * 100.0,
        acf_lag1=_autocorrelation(seq, 1),
        acf_lag7=_autocorrelation(seq, 7),
        note=note,
    )


def _autocorrelation(seq: Mapping[str, Mapping[date, float]], lag: int) -> Optional[float]:
    """Correlación del residuo consigo mismo desplazado ``lag`` días, dentro de cada local."""
    xs: List[float] = []
    ys: List[float] = []
    for days in seq.values():
        for day, value in days.items():
            other = days.get(day + timedelta(days=lag))
            if other is not None:
                xs.append(value)
                ys.append(other)
    if len(xs) < 2:
        return None
    mx, my = stats.fmean(xs), stats.fmean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den > 0 else None


# ─────────────────────────────────────────────────────────────────────────────
# Reglas candidatas
# ─────────────────────────────────────────────────────────────────────────────
#
# Cada regla recibe el panel de ENTRENAMIENTO en logaritmos y devuelve un predictor
# ``(store_id, day) -> log(valor) | None``. Devolver ``None`` es legítimo: significa que
# esa regla no tiene con qué pronunciarse sobre esa celda, y el backtest no la puntúa ahí
# en vez de rellenarla.

Predictor = Callable[[str, date], Optional[float]]
RuleBuilder = Callable[[Dict[str, Dict[date, float]]], Predictor]


def _build_store_mean(train: Dict[str, Dict[date, float]]) -> Predictor:
    """Nivel del local. Es la vara: no hacer nada más que conocer el tamaño del local."""
    level = {s: _mean(list(d.values())) for s, d in train.items()}

    def predict(store_id: str, day: date) -> Optional[float]:
        return level.get(store_id)

    return predict


def _build_store_dow(train: Dict[str, Dict[date, float]]) -> Predictor:
    """Celda local × día de semana. Donde el diagnóstico dice que está la señal."""
    cells: Dict[Tuple[str, int], List[float]] = defaultdict(list)
    for store_id, days in train.items():
        for day, lv in days.items():
            cells[(store_id, day.weekday())].append(lv)
    means = {k: _mean(v) for k, v in cells.items()}
    fallback = {s: _mean(list(d.values())) for s, d in train.items()}

    def predict(store_id: str, day: date) -> Optional[float]:
        cell = means.get((store_id, day.weekday()))
        return cell if cell is not None else fallback.get(store_id)

    return predict


def _build_store_dow_recent(train: Dict[str, Dict[date, float]],
                            weeks: int = 4) -> Predictor:
    """Celda local × día de semana estimada solo sobre las últimas semanas.

    Si el local cambió de nivel a mitad del período —remodelación, obra en la vía, un
    competidor que abrió enfrente— el promedio largo arrastra un régimen que ya no existe.
    """
    cutoffs = {
        s: (max(d) - timedelta(days=weeks * 7)) for s, d in train.items() if d
    }
    cells: Dict[Tuple[str, int], List[float]] = defaultdict(list)
    for store_id, days in train.items():
        cut = cutoffs.get(store_id)
        for day, lv in days.items():
            if cut is not None and day > cut:
                cells[(store_id, day.weekday())].append(lv)
    means = {k: _mean(v) for k, v in cells.items()}
    fallback = _build_store_dow(train)

    def predict(store_id: str, day: date) -> Optional[float]:
        cell = means.get((store_id, day.weekday()))
        return cell if cell is not None else fallback(store_id, day)

    return predict


def _build_store_dow_drift(train: Dict[str, Dict[date, float]],
                           window: int = 14) -> Predictor:
    """Celda local × día de semana, corregida por la desviación reciente del local.

    Recoge la autocorrelación a un día: si el local viene por encima de su patrón durante
    las últimas dos semanas, arranca por encima. El ajuste es de nivel, no de pendiente:
    proyectar pendiente sobre diez semanas de historia es el error que ``forecast.py`` ya
    documentó sobre este encargo.
    """
    base = _build_store_dow(train)
    drift: Dict[str, float] = {}
    for store_id, days in train.items():
        if not days:
            continue
        recent_cut = max(days) - timedelta(days=window)
        deviations = [
            lv - b
            for day, lv in days.items()
            if day > recent_cut and (b := base(store_id, day)) is not None
        ]
        if deviations:
            drift[store_id] = stats.fmean(deviations)

    def predict(store_id: str, day: date) -> Optional[float]:
        b = base(store_id, day)
        if b is None:
            return None
        return b + drift.get(store_id, 0.0)

    return predict


def _build_last_same_dow(train: Dict[str, Dict[date, float]]) -> Predictor:
    """El mismo día de la semana más reciente. Persistencia a frecuencia semanal."""

    def predict(store_id: str, day: date) -> Optional[float]:
        days = train.get(store_id)
        if not days:
            return None
        candidates = [d for d in days if d.weekday() == day.weekday() and d < day]
        return days[max(candidates)] if candidates else None

    return predict


def _drift_builder(window: int) -> RuleBuilder:
    def build(train: Dict[str, Dict[date, float]]) -> Predictor:
        return _build_store_dow_drift(train, window=window)
    return build


RULES: Dict[str, RuleBuilder] = {
    "store_mean": _build_store_mean,
    "store_dow": _build_store_dow,
    "store_dow_recent": _build_store_dow_recent,
    "store_dow_drift_7": _drift_builder(7),
    "store_dow_drift_14": _drift_builder(14),
    "store_dow_drift_28": _drift_builder(28),
    "last_same_dow": _build_last_same_dow,
}

#: La vara contra la que se mide el aporte de cualquier regla.
BASELINE_RULE = "store_mean"


# ─────────────────────────────────────────────────────────────────────────────
# Backtest de origen móvil
# ─────────────────────────────────────────────────────────────────────────────

def _folds(days: Sequence[date], horizon: int) -> List[Tuple[date, List[date]]]:
    """Cortes sucesivos: entrena hasta el corte, predice las ``horizon`` jornadas siguientes."""
    ordered = sorted(set(days))
    out: List[Tuple[date, List[date]]] = []
    start = MIN_TRAIN_DAYS
    while start + 1 <= len(ordered):
        cut = ordered[start - 1]
        ahead = ordered[start:start + horizon]
        if not ahead:
            break
        out.append((cut, ahead))
        start += horizon
    return out


def backtest(
    observations: Sequence[Observation],
    horizon: int = DEFAULT_HORIZON_DAYS,
) -> Tuple[List[RuleScore], Dict[str, Dict[str, List[float]]]]:
    """Puntúa cada regla candidata sobre origen móvil, sin mirar hacia adelante.

    Devuelve el ranking y, por regla y por local, la **diferencia logarítmica con signo**
    de cada predicción puntuada, ``log(real) − log(pronóstico)``. Se guarda con signo y sin
    transformar por un motivo: de ahí salen dos cosas distintas y una de ellas se rompe si
    se guarda el valor absoluto. El error medio necesita la magnitud; la banda necesita la
    **asimetría**, porque errar por encima y por debajo no es simétrico en una serie que se
    modela en logaritmos. Se devuelven en vez de recalcularse para que el error, la banda y
    el veredicto por local salgan todos de la misma corrida.

    El horizonte se puntúa completo: un backtest a catorce días promedia el acierto del día
    siguiente con el del decimocuarto. Es el número honesto para un pronóstico que se emite
    una vez y se lee durante todo el tramo.
    """
    usable = _usable(observations)
    panel = _log_panel(usable)
    all_days = sorted({o.day for o in usable})
    folds = _folds(all_days, horizon)

    errors: Dict[str, Dict[str, List[float]]] = {name: defaultdict(list) for name in RULES}
    if not folds:
        return [RuleScore(name, None, 0) for name in RULES], errors

    for cut, ahead in folds:
        train = {
            store_id: {d: v for d, v in days.items() if d <= cut}
            for store_id, days in panel.items()
        }
        train = {s: d for s, d in train.items() if d}
        if not train:
            continue
        for name, build in RULES.items():
            predict = build(train)
            for store_id, days in panel.items():
                for day in ahead:
                    actual = days.get(day)
                    if actual is None:
                        continue
                    pred = predict(store_id, day)
                    if pred is None:
                        continue
                    errors[name][store_id].append(actual - pred)

    ranked = [
        RuleScore(
            name,
            _mape([d for errs in per_store.values() for d in errs]),
            sum(len(v) for v in per_store.values()),
        )
        for name, per_store in errors.items()
    ]
    ranked.sort(key=lambda r: (r.mape is None, r.mape if r.mape is not None else 0.0))
    return ranked, errors


# ─────────────────────────────────────────────────────────────────────────────
# Veredicto por local y proyección
# ─────────────────────────────────────────────────────────────────────────────

def _verdicts(
    panel: Dict[str, Dict[date, float]],
    errors: Dict[str, Dict[str, List[float]]],
    rule: str,
) -> List[StoreVerdict]:
    """Un local es proyectable cuando la regla elegida le gana a su propio promedio.

    Sin umbral inventado: la vara es la alternativa de no hacer nada. Los que no la
    superan se declaran, no se ocultan — ocultarlos los haría desaparecer sin aviso y el
    informe quedaría afirmando cobertura que no tiene.
    """
    out: List[StoreVerdict] = []
    for store_id in sorted(panel):
        n_days = len(panel[store_id])
        chosen = errors.get(rule, {}).get(store_id, [])
        base = errors.get(BASELINE_RULE, {}).get(store_id, [])
        mape = _mape(chosen)
        base_mape = _mape(base)

        if n_days < MIN_DAYS_PER_STORE:
            reason: Optional[str] = REASON_SHORT_HISTORY
        elif mape is None:
            reason = REASON_NO_SCORED
        elif base_mape is not None and mape >= base_mape and rule != BASELINE_RULE:
            reason = REASON_NO_LIFT
        else:
            reason = None

        out.append(StoreVerdict(
            store_id=store_id,
            projectable=reason is None,
            reason=reason,
            mape=mape,
            baseline_mape=base_mape,
            n_predictions=len(chosen),
            n_days=n_days,
        ))
    return out


def _percentile(values: Sequence[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * pct / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] * (hi - k) + ordered[hi] * (k - lo)


def project(
    observations: Sequence[Observation],
    horizon: int = DEFAULT_HORIZON_DAYS,
    rule: Optional[str] = None,
) -> Optional[ProjectionResult]:
    """Proyecta ``horizon`` jornadas hacia adelante desde la última observada.

    La banda no es de muestreo: sale de los percentiles de los errores del propio modelo
    fuera de muestra. Es la respuesta a *cuánto suele errarle este modelo a este local*, y
    esa es la única incertidumbre que un censo admite.

    Devuelve ``None`` cuando no hay historia suficiente para puntuar ninguna regla, en vez
    de emitir una proyección sin respaldo.
    """
    usable = _usable(observations)
    if not usable:
        return None
    panel = _log_panel(usable)
    ranked, errors = backtest(usable, horizon)

    scored = [r for r in ranked if r.mape is not None]
    if not scored:
        return None
    chosen = rule or scored[0].rule
    overall = next((r.mape for r in ranked if r.rule == chosen), None)
    baseline = next((r.mape for r in ranked if r.rule == BASELINE_RULE), None)

    verdicts = _verdicts(panel, errors, chosen)
    projectable = {v.store_id for v in verdicts if v.projectable}

    # La banda sale de los percentiles de la desviación CON SIGNO respecto del punto:
    # ``real / pronóstico − 1``. Tomar percentiles del error absoluto y aplicarlos
    # simétricamente inventaría un borde inferior que el backtest nunca midió.
    pooled = [math.expm1(d) for errs in errors.get(chosen, {}).values() for d in errs]
    band_lo = _percentile(pooled, BAND_LO_PCT)
    band_hi = _percentile(pooled, BAND_HI_PCT)

    predict = RULES[chosen](panel)
    last_day = max(o.day for o in usable)
    points: List[PointProjection] = []
    for offset in range(1, horizon + 1):
        day = last_day + timedelta(days=offset)
        for store_id in sorted(projectable):
            log_point = predict(store_id, day)
            if log_point is None or band_lo is None or band_hi is None:
                continue
            point = math.exp(log_point)
            points.append(PointProjection(
                store_id=store_id,
                day=day,
                point=point,
                lo=point * (1.0 + band_lo),
                hi=point * (1.0 + band_hi),
            ))

    bias = stats.median(pooled) if pooled else None
    above = (
        sum(1 for r in pooled if r > 0) / len(pooled) * 100.0 if pooled else None
    )

    n_scored = next((r.n_predictions for r in ranked if r.rule == chosen), 0)
    lift = (
        f"{(baseline - overall) / baseline * 100:.0f}% menos error que el promedio del local"
        if baseline and overall and baseline > 0 else "sin contraste contra la vara"
    )
    calib = (
        f" El real superó al pronóstico en {above:.0f}% de las jornadas puntuadas "
        f"(mediana {bias * 100:+.1f}%): "
        + ("calibrado." if above is not None and 45.0 <= above <= 55.0
           else "el pronóstico corre sesgado y la banda lo refleja.")
        if above is not None and bias is not None else ""
    )
    basis = (
        f"Regla '{chosen}' elegida por backtest de origen móvil sobre {n_scored} "
        f"predicciones a {horizon} días ({lift}). Banda de los percentiles "
        f"{BAND_LO_PCT:.0f}–{BAND_HI_PCT:.0f} del error fuera de muestra, no de muestreo: "
        f"la venta es censo. {len(projectable)} de {len(verdicts)} locales proyectables."
        + calib
    )

    return ProjectionResult(
        rule=chosen,
        horizon_days=horizon,
        overall_mape=overall,
        baseline_mape=baseline,
        band_lo_pct=(band_lo * 100.0) if band_lo is not None else None,
        band_hi_pct=(band_hi * 100.0) if band_hi is not None else None,
        bias_pct=(bias * 100.0) if bias is not None else None,
        share_above_pct=above,
        ranked_rules=tuple(ranked),
        verdicts=tuple(verdicts),
        points=tuple(points),
        variance=variance_decomposition(usable),
        basis=basis,
    )
