"""Calibración de los pesos de *Alerta Temprana* sobre el histórico SIB — el ARTEFACTO.

MAPA DE MÓDULOS — cuál es el vivo. Hay cuatro piezas que se parecen y sirven a fines distintos;
confundirlas es como se producen las regresiones de dirección:

  propension_quiebra.py .............. EL MODELO VIVO. Evalúa a cualquier banco y devuelve su
                                       propensión + la explicación en prosa de negocio.
  validation/terminaciones.py ........ la cohorte y el registro curado que lo alimentan.
  validation/hazard.py ............... la infraestructura del panel de riesgo (censura, riesgos
                                       en competencia) que `propension_quiebra` REUSA. Su
                                       `ajustar()` es el diagnóstico curada-vs-inferida, no el
                                       modelo de producto.
  validation/ew_calibration.py ....... calibra los pesos del ÍNDICE LEGACY de `early_warning`,
                                       que es un contador de umbrales heredado del rating. NO
                                       es el modelo de propensión y no se usa para predecir.

Regla: si el trabajo es "predecir quiebras", el archivo es `propension_quiebra.py`. Si te
encontrás ajustando `ALERT_WEIGHTS`, estás en el módulo equivocado.

Por qué existe este módulo. Los pesos de ``early_warning.ALERT_WEIGHTS`` se describían como
"calibrados sobre la cohorte de 35 terminaciones agudas del histórico SIB, con regresión
logística estandarizada validada leave-one-entity-out (AUC 0.88, detección 34/35, falsos
positivos 1/45)". Esa calibración NO existía como código: ni script, ni cohorte definida, ni
matriz — solo el comentario y el mensaje del commit. Siete números que ponderan el índice de
un informe que se vende, imposibles de re-derivar, re-validar o extender.

Qué encontró al reconstruirla. Los pesos **no están identificados por el dato**: cambiar la
definición de la cohorte —incluir o no a los zombis crónicos entre los positivos, usar como
controles a todas las entidades o solo a las que sobrevivieron, mover el horizonte— mueve
``morosidad_nivel`` entre 0.00 y 0.42 y ``brecha_provisiones`` entre 0.00 y 0.55. Ninguna de
esas decisiones es caprichosa; son las que cualquiera toma al armar el ejercicio.

Por eso la salida canónica de este módulo es :func:`sensitivity_table` —la tabla completa de
variantes— y NO un vector único de pesos. Publicar siete decimales fijos escondería que la
receta los determina tanto como el dato. Quien fije la receta, que la declare.

Dos hallazgos SÍ son robustos (aparecen en las seis variantes, ver la tabla):
  • ``crecimiento_anomalo`` recibe peso CERO en todas. En producción vale 0.08 y su glosa lo
    llama "la señal MÁS temprana". El panel histórico no sostiene esa afirmación.
  • ``estres_liquidez`` es siempre material (0.19–0.69). En producción vale 0.02 con la glosa
    "pesa poco: CONFIRMA tarde, no anticipa". La diferencia es de un orden de magnitud y en
    dirección contraria a lo documentado.
Y el AUC leave-one-entity-out no alcanza 0.88 en ninguna variante: el techo medido es 0.800.

Límite declarado: ``solvencia_piso`` NO entra en la matriz. Es solvencia Basilea, regulatoria
y ausente pre-2004 — el mismo punto ciego que declara el backtest. Su peso vigente (0.06) no
es verificable con esta fuente. ``fondeo_caro`` tampoco: el P&L del ledger es acumulado YTD.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.banking.ew_calibration")

# Piso de morosidad relativo al tipo — misma doctrina que ``early_warning``: lo "normal"
# difiere por modelo de negocio. Las claves son el ``tipo_entidad`` del ledger, normalizado.
MOROSIDAD_FLOOR_BY_TYPE: Dict[str, float] = {
    "bancos multiples": 5.0,
    "asociaciones de ahorros y prestamos": 7.0,
    "bancos de ahorro y credito": 9.0,
    "corporaciones de credito": 15.0,
    "entidades publicas de intermediacion financiera": 7.0,
}
DEFAULT_MOROSIDAD_FLOOR = 7.0

# Una entidad "sigue viva" si reporta hasta el final del panel; se tolera un rezago de
# publicación. Más allá de eso, su última fila es una SALIDA del sistema.
EXIT_LAG_M = 6
# Un control no puede estar a menos de estos meses de su propia salida (evita etiquetar
# como "sana" una observación que ya está dentro del deterioro terminal).
SAFE_GAP_M = 24
# Estado sano exigido a esta distancia de la salida para que la terminación sea AGUDA.
LOOKBACK_SANO_M = 24
# Un control por año calendario: 950 meses casi idénticos de la misma entidad no son 950
# observaciones independientes; inflan el n y estrechan los intervalos de forma falsa.
CONTROL_MONTH = 12

FEATURES: Tuple[str, ...] = (
    "morosidad_nivel", "salto_morosidad", "brecha_provisiones",
    "erosion_capital", "crecimiento_anomalo", "estres_liquidez",
)


@dataclass(frozen=True)
class CohortSpec:
    """Una receta de cohorte. El barrido sobre estas es la salida del módulo."""
    name: str
    solo_agudas: bool                    # positivos = solo salidas que venían sanas
    controles_solo_supervivientes: bool  # excluye el pasado de las entidades que salieron
    horizon_m: int                       # meses antes de la salida donde se miden features


COHORT_VARIANTS: Tuple[CohortSpec, ...] = (
    CohortSpec("agudas · controles=todos · h12", True, False, 12),
    CohortSpec("agudas · controles=supervivientes · h12", True, True, 12),
    CohortSpec("todas las salidas · controles=todos · h12", False, False, 12),
    CohortSpec("todas las salidas · controles=supervivientes · h12", False, True, 12),
    CohortSpec("agudas · controles=supervivientes · h6", True, True, 6),
    CohortSpec("agudas · controles=supervivientes · h24", True, True, 24),
)


@dataclass(frozen=True)
class FitResult:
    spec: CohortSpec
    n_pos: int
    n_ctrl: int
    n_entities: int
    auc: Optional[float]
    coef: Dict[str, float]      # coeficientes estandarizados (con signo)
    weights: Dict[str, float]   # normalizados sobre los coeficientes POSITIVOS


def _norm(s: Optional[str]) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _shift(d: date, back_m: int) -> date:
    total = d.year * 12 + (d.month - 1) - back_m
    return date(total // 12, total % 12 + 1, 1)


def morosidad_floor(tipo_entidad: Optional[str]) -> float:
    return MOROSIDAD_FLOOR_BY_TYPE.get(_norm(tipo_entidad), DEFAULT_MOROSIDAD_FLOOR)


def build_features(series: Dict[date, Dict], ref: date, floor: float) -> Optional[Dict[str, float]]:
    """Las seis señales en *ref*, o ``None`` si falta algún input.

    Devolver ``None`` —y no un cero— es deliberado: una observación con datos faltantes se
    excluye de la matriz, no entra rellenada. Un cero acá sería una brecha disfrazada de
    señal apagada, que es exactamente lo que la doctrina prohíbe.
    """
    cur = series.get(ref)
    p12 = series.get(_shift(ref, 12))
    p3 = series.get(_shift(ref, 3))
    if cur is None or p12 is None:
        return None
    mora, cob = _f(cur.get("morosidad_pct")), _f(cur.get("cobertura_pct"))
    mora12 = _f(p12.get("morosidad_pct"))
    apa, apa12 = _f(cur.get("apalancamiento_pct")), _f(p12.get("apalancamiento_pct"))
    act, act12 = _f(cur.get("activos_totales")), _f(p12.get("activos_totales"))
    dep = _f(cur.get("depositos_totales"))
    dep3 = _f(p3.get("depositos_totales")) if p3 else None
    if (mora is None or cob is None or mora12 is None or apa is None or apa12 is None
            or act is None or not act12):
        return None
    return {
        # Nivel de mora RELATIVO a su tipo (positivo = por encima de lo normal para el tipo).
        "morosidad_nivel": mora - floor,
        "salto_morosidad": mora - mora12,
        # Brecha respecto de cobertura plena; 0 si cubre ≥100% (no se premia el exceso).
        "brecha_provisiones": max(0.0, 100.0 - cob),
        # Signo invertido: la señal es la CAÍDA del capital, no su nivel.
        "erosion_capital": -(apa - apa12),
        "crecimiento_anomalo": act / act12 - 1.0,
        # Signo invertido: la señal es la fuga de depósitos.
        "estres_liquidez": -(dep / dep3 - 1.0) if (dep3 and dep is not None) else 0.0,
    }


def build_design(panel: Dict[str, Dict[date, Dict]], spec: CohortSpec,
                 panel_end: date) -> Tuple[List[List[float]], List[int], List[str]]:
    """Matriz de diseño para una receta: ``(X, y, groups)``. ``groups`` es la entidad, que
    es la unidad de la validación (leave-one-ENTITY-out): dos meses del mismo banco no son
    observaciones independientes."""
    X: List[List[float]] = []
    y: List[int] = []
    groups: List[str] = []
    for code, series in panel.items():
        dates = sorted(series)
        if len(dates) < LOOKBACK_SANO_M + 2:
            continue
        last = dates[-1]
        tipo = series[last].get("tipo_entidad")
        floor = morosidad_floor(tipo)
        salio = _months_between(last, panel_end) > EXIT_LAG_M
        if salio:
            usar = True
            if spec.solo_agudas:
                sano = series.get(_shift(last, LOOKBACK_SANO_M))
                ms = _f(sano.get("morosidad_pct")) if sano else None
                usar = ms is not None and ms <= floor
            if usar:
                fx = build_features(series, _shift(last, spec.horizon_m), floor)
                if fx:
                    X.append([fx[k] for k in FEATURES])
                    y.append(1)
                    groups.append(code)
        if salio and spec.controles_solo_supervivientes:
            continue
        for d in dates:
            if d.month != CONTROL_MONTH:
                continue
            ref_end = last if salio else panel_end
            if _months_between(d, ref_end) < SAFE_GAP_M + spec.horizon_m:
                continue
            fx = build_features(series, d, floor)
            if fx:
                X.append([fx[k] for k in FEATURES])
                y.append(0)
                groups.append(code)
    return X, y, groups


def build_design_cohorte(panel: Dict[str, Dict[date, Dict]], terminaciones,
                         spec: CohortSpec, panel_end: date
                         ) -> Tuple[List[List[float]], List[int], List[str]]:
    """Matriz de diseño sobre la COHORTE CANÓNICA, no sobre una etiqueta propia.

    Antes esta calibración definía sus quiebras al vuelo —última fila del panel, con una regla
    de "estado sano 24m antes"— y el resultado dependía tanto de esa receta como del dato.
    `validation.terminaciones` clasifica las 224 salidas del histórico por el estado en que la
    entidad dejó de reportar, y aísla la institución del código (sin eso Bancrédito y Mercantil
    no existen como quiebras). Esta función usa ESE conjunto.

    Los `no_evaluable` quedan fuera de las DOS clases: no se sabe qué fueron, y meterlos como
    negativos afirmaría que sobrevivieron. Las salidas `sana_al_salir` sí son negativos
    legítimos: fusiones y ventas de entidades que no estaban deteriorándose.
    """
    from modules.banking_score.validation.terminaciones import cohorte_canonica

    quiebras = {t.entidad_nombre: t for t in cohorte_canonica(terminaciones)}
    no_evaluables = {t.entidad_nombre for t in terminaciones
                     if t.naturaleza == "no_evaluable"}
    X: List[List[float]] = []
    y: List[int] = []
    groups: List[str] = []
    for code, series in panel.items():
        dates = sorted(series)
        if not dates:
            continue
        nombre = str(series[dates[-1]].get("entidad_nombre") or code)
        if nombre in no_evaluables:
            continue
        floor = morosidad_floor(series[dates[-1]].get("tipo_entidad"))
        t = quiebras.get(nombre)
        if t is not None:
            fx = build_features(series, _shift(t.fecha_salida, spec.horizon_m), floor)
            if fx:
                X.append([fx[k] for k in FEATURES])
                y.append(1)
                groups.append(nombre)
            continue      # una quiebra no aporta también controles de su propio pasado
        ref_end = dates[-1] if _months_between(dates[-1], panel_end) > EXIT_LAG_M else panel_end
        for d in dates:
            if d.month != CONTROL_MONTH:
                continue
            if _months_between(d, ref_end) < SAFE_GAP_M + spec.horizon_m:
                continue
            fx = build_features(series, d, floor)
            if fx:
                X.append([fx[k] for k in FEATURES])
                y.append(0)
                groups.append(nombre)
    return X, y, groups


def fit_weights(X: Sequence[Sequence[float]], y: Sequence[int], groups: Sequence[str],
                spec: CohortSpec) -> Optional[FitResult]:
    """Regresión logística estandarizada + validación leave-one-entity-out.

    Los pesos se normalizan sobre los coeficientes POSITIVOS: un coeficiente negativo
    significa que la señal apunta al revés en esta cohorte, y una señal que apunta al revés
    no puede aportar peso a un índice de deterioro — se reporta con su signo en ``coef`` y
    se le asigna peso 0, en vez de tomarle el valor absoluto (que la premiaría por estar mal).
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    Xa, ya, ga = np.asarray(X, dtype=float), np.asarray(y), np.asarray(groups)
    if Xa.size == 0 or ya.sum() < 8:
        logger.info("Cohorte '%s': positivos insuficientes (%s)", spec.name,
                    int(ya.sum()) if ya.size else 0)
        return None
    Xs = StandardScaler().fit_transform(Xa)
    coef = LogisticRegression(max_iter=2000, class_weight="balanced").fit(Xs, ya).coef_[0]

    preds = np.zeros(len(ya))
    for e in set(ga.tolist()):
        tr, te = ga != e, ga == e
        if ya[tr].sum() < 2:
            continue
        preds[te] = (LogisticRegression(max_iter=2000, class_weight="balanced")
                     .fit(Xs[tr], ya[tr]).predict_proba(Xs[te])[:, 1])
    auc = float(roc_auc_score(ya, preds)) if len(set(ya.tolist())) > 1 else None

    pos = np.clip(coef, 0.0, None)
    w = pos / pos.sum() if pos.sum() else pos
    return FitResult(
        spec=spec, n_pos=int(ya.sum()), n_ctrl=int((ya == 0).sum()),
        n_entities=len(set(ga.tolist())), auc=auc,
        coef={k: round(float(c), 4) for k, c in zip(FEATURES, coef)},
        weights={k: round(float(v), 4) for k, v in zip(FEATURES, w)},
    )


def sensitivity_table(panel: Dict[str, Dict[date, Dict]],
                      specs: Sequence[CohortSpec] = COHORT_VARIANTS,
                      panel_end: Optional[date] = None) -> List[FitResult]:
    """LA salida del módulo: los pesos bajo CADA receta de cohorte.

    No devuelve un vector elegido a propósito. Que el resultado dependa tanto de la receta
    como del dato es el hallazgo, y esconderlo detrás de siete decimales sería el error que
    este módulo existe para no repetir.
    """
    if panel_end is None:
        panel_end = max(d for s in panel.values() for d in s) if panel else date.today()
    out: List[FitResult] = []
    for spec in specs:
        X, y, g = build_design(panel, spec, panel_end)
        r = fit_weights(X, y, g, spec)
        if r:
            out.append(r)
    return out


# Todo lo que los consumidores del panel leen. `load_panel` DEBE poblar cada una: un campo
# que falte no rompe nada visible, simplemente devuelve None y el consumidor se apaga en
# silencio. Pasó con `entidad_nombre`: sin él, `terminaciones.detectar` veía todas las
# entidades sin nombre, la curaduría no emparejaba con ninguna, el modelo se entrenaba con
# CERO quiebras curadas y `modelo_vigente` devolvía None — o sea que la propensión nunca se
# computó en producción, y el informe simplemente omitía la sección. Lo cazó regenerar contra
# prod, no los 4.000 tests: yo verificaba sobre un panel derivado del CSV, que sí trae el
# nombre. Probar el camino viejo no prueba el nuevo.
CAMPOS_DEL_PANEL: Tuple[str, ...] = (
    "entidad_code", "entidad_nombre", "tipo_entidad", "morosidad_pct", "cobertura_pct",
    "apalancamiento_pct", "activos_totales", "depositos_totales",
)


def load_panel(db) -> Dict[str, Dict[date, Dict]]:
    """Panel mensual desde ``SibHistoricalFinancials`` (la tabla derivada por el crosswalk
    de producción — la calibración corre sobre la MISMA derivación que el motor)."""
    from modules.banking_score.models.models import SibHistoricalFinancials as F

    panel: Dict[str, Dict[date, Dict]] = {}
    for r in db.query(F).all():
        panel.setdefault(str(r.entidad_code), {})[r.fecha] = {
            # La institución, no el slot: `terminaciones` recorre runs de NOMBRE porque el
            # código de la SB aloja varias entidades a lo largo del tiempo.
            "entidad_nombre": r.entidad_nombre,
            "entidad_code": r.entidad_code,
            "tipo_entidad": r.tipo_entidad,
            "morosidad_pct": r.morosidad_pct,
            "cobertura_pct": r.cobertura_pct,
            "apalancamiento_pct": r.apalancamiento_pct,
            "activos_totales": r.activos_totales,
            "depositos_totales": r.depositos_totales,
        }
    return panel


def format_table(results: Sequence[FitResult]) -> str:
    """La tabla en texto — para el informe de metodología y para leerla en consola."""
    head = (f"{'receta de cohorte':52} {'pos':>4} {'ctrl':>5} {'AUC':>6} | "
            + " ".join(f"{k[:9]:>9}" for k in FEATURES))
    lines = [head, "-" * len(head)]
    for r in results:
        auc = f"{r.auc:6.3f}" if r.auc is not None else "     —"
        lines.append(f"{r.spec.name:52} {r.n_pos:4} {r.n_ctrl:5} {auc} | "
                     + " ".join(f"{r.weights[k]:9.3f}" for k in FEATURES))
    return "\n".join(lines)
