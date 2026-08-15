"""Backtest de *Alerta Temprana* sobre el histórico SIB.

Aplica las reglas puras de ``early_warning.evaluate`` a los financials mensuales
derivados (``SibHistoricalFinancials``) de las entidades que **realmente quebraron**, y
mide cuántos meses antes de su salida del sistema se habría encendido la primera alerta
de severidad alta. Es la validación del motor contra desenlaces conocidos — la credencial
de venta frente a Fitch.

Diferencia de cadencia respecto al motor operativo: ``early_warning._bank_metrics`` asume
datos **trimestrales** (prev_4 = un año atrás). El histórico es **mensual**, así que aquí
se reusan las reglas puras pero las métricas se arman con offsets mensuales (−12m para
interanual/salto de morosidad, −3m para la corrida de depósitos).

Límite honesto — mismo que el motor: la solvencia Basel y la concentración top-10 no
existen en el histórico contable, así que esas dos reglas no disparan. Es exactamente el
punto ciego ante el fraude ocultado (Baninter): los ratios detectan insolvencia, no
contabilidad paralela.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date
from typing import Dict, List, Optional

from modules.banking_score import early_warning as ew

logger = logging.getLogger("sdq.banking.sib_historical_backtest")

_NEAR_EXIT = 18   # el run de deterioro debe llegar a ≤18m de la salida para fechar la quiebra
_RUN_GAP = 6      # respiros (meses sin cluster) tolerados dentro del run final

# Cohorte de quiebras SISTÉMICAS (Bancos Múltiples) de la crisis de 2003, con su fecha de
# intervención conocida. El backtest es fiable para este tier: entidades de escala con
# ratios significativos. NO se incluyen entidades diminutas (p.ej. Banco Peravia, Ahorro y
# Crédito, fraude 2014): en la banca pequeña una cobertura estructuralmente < 100% y
# depósitos volátiles hacen que el cluster de ratios dispare de forma crónica — el ratio no
# puede fechar su quiebra de forma fiable (mismo punto ciego ante el fraude, amplificado por
# el ruido de escala). Es una limitación declarada, no un dato ocultado.
FAILED_COHORT: List[Dict] = [
    {"nombre": "Banco Nacional de Crédito", "salida": date(2003, 6, 1), "bank_type": "banca_multiple", "episodio": "Crisis 2003 (Bancrédito)"},
    {"nombre": "Banco Mercantil", "salida": date(2003, 9, 1), "bank_type": "banca_multiple", "episodio": "Crisis 2003"},
    {"nombre": "Banco Intercontinental (Baninter)", "salida": date(2003, 5, 1), "bank_type": "banca_multiple", "episodio": "Crisis 2003 (fraude)"},
    {"nombre": "Banco Global", "salida": date(2003, 6, 1), "bank_type": "banca_multiple", "episodio": "Crisis 2003"},
    # Episodio de quiebras de inicios de los 90 (confirmado por el dueño). Salida = último mes
    # reportado en el histórico. Panamericano tiene serie corta (~17m) → el fechado de su onset
    # es menos fiable, pero se documenta como quiebra conocida del roster.
    {"nombre": "Banco Universal", "salida": date(1992, 9, 1), "bank_type": "banca_multiple", "episodio": "Quiebra inicios de los 90"},
    {"nombre": "Banco Panamericano", "salida": date(1992, 4, 1), "bank_type": "banca_multiple", "episodio": "Quiebra inicios de los 90 (serie corta)"},
]


def _g(row, attr) -> Optional[float]:
    v = getattr(row, attr, None) if row is not None else None
    return float(v) if v is not None else None


def _monthly_metrics(dates: List[date], rows: Dict[date, object], i: int,
                     bank_type: Optional[str] = None) -> Dict:
    """Métricas de early-warning en el mes *i*, con offsets MENSUALES.

    solvencia/concentración/fondeo quedan en None: no son reconstruibles del histórico
    contable (regulatorio / top-10 / P&L acumulado YTD). Esas reglas no disparan — es el
    punto ciego declarado ante el fraude. Capital: proxy = apalancamiento contable
    (patrimonio/activos); su CAÍDA en 12m alimenta la erosión de capital. El nivel de
    morosidad se juzga contra el umbral relativo al ``bank_type``, y ``morosidad_chronic``
    (24m atrás) distingue el zombi crónico del deterioro agudo.
    """
    cur = rows[dates[i]]
    p3 = rows[dates[i - 3]] if i >= 3 else None
    p12 = rows[dates[i - 12]] if i >= 12 else None
    p24 = rows[dates[i - 24]] if i >= 24 else None
    return {
        "assets_yoy": ew._yoy(_g(cur, "activos_totales"), _g(p12, "activos_totales")),
        "funding_cost": None,          # gastos_financieros es YTD → ratio ruidoso, se omite
        "cobertura_pct": _g(cur, "cobertura_pct"),
        "morosidad_pct": _g(cur, "morosidad_pct"),
        "morosidad_prev4": _g(p12, "morosidad_pct"),
        "morosidad_chronic": _g(p24, "morosidad_pct"),   # ~2 años atrás → zombi vs deterioro
        "solvencia_pct": None,         # Basel ausente pre-2004
        "capital_now": _g(cur, "apalancamiento_pct"),    # patrimonio/activos (None si no está)
        "capital_prior": _g(p12, "apalancamiento_pct"),
        "bank_type": bank_type,
        "liq_ratio": ew._pct(_g(cur, "activos_liquidos"), _g(cur, "pasivos_totales")),  # proxy
        "deposit_qoq": ew._yoy(_g(cur, "depositos_totales"), _g(p3, "depositos_totales")),
        "concentracion_top10_deudores_pct": None,     # top-10 no disponible
    }


def _peer_growth_p90(all_series: Dict[str, Dict[date, object]], month: date) -> Optional[float]:
    """p90 del crecimiento interanual de activos entre las entidades con dato ese mes."""
    yoys: List[float] = []
    for series in all_series.values():
        dts = sorted(series)
        if month not in series:
            continue
        i = dts.index(month)
        if i < 12:
            continue
        y = ew._yoy(_g(series[month], "activos_totales"), _g(series[dts[i - 12]], "activos_totales"))
        if y is not None:
            yoys.append(y)
    return ew.percentile(yoys, 0.90) if yoys else None


def backtest_entity(series: Dict[date, object], *, all_series: Optional[Dict] = None,
                    salida: Optional[date] = None, min_cluster: int = 2,
                    bank_type: Optional[str] = None) -> Dict:
    """Corre el motor mes a mes y fecha el **inicio del deterioro** como el primer mes con
    un *cluster* de ≥``min_cluster`` alertas de severidad alta simultáneas.

    Por qué un cluster y no una alerta suelta: una sola regla dispara de forma CRÓNICA en
    la banca pequeña (una cobertura estructuralmente < 100% enciende `brecha_provisiones`
    durante años) → sin este filtro el backtest reporta 'anticipaciones' de 60–214 meses,
    que es gritar «lobo», no una señal. La firma real de una quiebra ordenada (Bancrédito
    jul-2002) es la CONVERGENCIA de varias señales altas a la vez: salto de morosidad +
    fuga de depósitos. Exigir el cluster distingue el deterioro agudo del ruido estructural,
    y deja al descubierto —honestamente— que contra el fraude ocultado (Baninter) el cluster
    llega tarde: los ratios no ven la contabilidad paralela.

    ANCLA AL RUN FINAL (no al primer cluster): el onset es el inicio del RUN de deterioro que
    entra a la salida, no el primer parpadeo de la historia. Un banco con 20-40 años de dato
    tiene ruido temprano (libro chico → ratios volátiles) que dispara clusters décadas antes
    del colapso real — por eso "primer cluster" daba 247 meses en Bancrédito y 77 en Global.
    Se recorre HACIA ATRÁS desde la salida el run de meses en cluster de deterioro de CRÉDITO
    (≥``min_cluster`` altas incluyendo salto/nivel de morosidad), tolerando respiros de hasta
    ``_RUN_GAP`` meses; y el run debe llegar a ≤``_NEAR_EXIT`` meses de la salida para contar
    como onset de la quiebra (si el último deterioro quedó lejos, se resolvió y no la causó).
    """
    dates = sorted(series)
    exit_date = salida or (dates[-1] if dates else None)
    timeline: List[Dict] = []
    first_high: Optional[date] = None
    n_high = 0

    credit_codes = {"salto_morosidad", "morosidad_nivel"}
    idx = [d for d in dates if not (exit_date and d > exit_date)]
    det_months: List[date] = []            # meses en cluster de deterioro de crédito
    det_scores: Dict[date, float] = {}
    for d in idx:
        m = _monthly_metrics(dates, series, dates.index(d), bank_type)
        peers = {"growth_p90": _peer_growth_p90(all_series, d) if all_series else None,
                 "funding_p90": None}
        alerts = ew.evaluate(m, peers)
        altas = [a for a in alerts if a.severity == "alta"]
        if altas:
            n_high += 1
            if first_high is None:
                first_high = d
        if len(altas) >= min_cluster and any(a.code in credit_codes for a in altas):
            det_months.append(d)
            # `ensemble_score` devuelve SALUD (100 = ningún precursor activo). El backtest
            # quiere lo contrario —magnitud de deterioro—, así que invierte explícitamente.
            det_scores[d] = 100.0 - ew.ensemble_score(alerts)["salud_precursores"]
        if alerts:
            timeline.append({"period": d.isoformat(),
                             "score": 100.0 - ew.ensemble_score(alerts)["salud_precursores"],
                             "alerts": [{"code": a.code, "severity": a.severity, "value": a.value}
                                        for a in alerts]})

    # Onset = inicio del run FINAL de deterioro que llega cerca de la salida.
    onset: Optional[date] = None
    onset_score: Optional[float] = None
    if det_months:
        last = det_months[-1]
        m2e = ((exit_date.year - last.year) * 12 + (exit_date.month - last.month)
               if exit_date else 0)
        if exit_date is None or m2e <= _NEAR_EXIT:
            det_set = set(det_months)
            onset = last
            gap = 0
            for j in range(idx.index(last) - 1, -1, -1):
                if idx[j] in det_set:
                    onset = idx[j]
                    gap = 0
                else:
                    gap += 1
                    if gap > _RUN_GAP:
                        break
            onset_score = det_scores.get(onset)

    lead_months = None
    if onset and exit_date:
        lead_months = (exit_date.year - onset.year) * 12 + (exit_date.month - onset.month)
    return {
        "exit_date": exit_date.isoformat() if exit_date else None,
        "onset_cluster": onset.isoformat() if onset else None,
        "onset_score": onset_score,
        "first_high_raw": first_high.isoformat() if first_high else None,
        "lead_months": lead_months,
        "n_high_months": n_high,
        "n_flagged_months": len(timeline),
        "timeline": timeline,
    }


def backtest_cohort(db, cohort: Optional[List[Dict]] = None) -> List[Dict]:
    """Backtest de la cohorte de quiebras. Devuelve un resumen por entidad.

    Se keyea por ``entidad_nombre`` (no por ``entidad_code``): el código de la SB es un
    *slot de linaje* que mezcla la entidad quebrada con su sucesor (BANCRÉDITO-LEÓN,
    MERCANTIL-REPUBLIC BANK). Keyear por nombre aísla la institución que quebró.
    """
    from modules.banking_score.models.models import SibHistoricalFinancials

    cohort = cohort or FAILED_COHORT
    # Índice por NOMBRE → {fecha: row}, y por nombre → contexto de pares. Un solo scan.
    by_name: Dict[str, Dict[date, object]] = {}
    for f in db.query(SibHistoricalFinancials).all():
        if f.entidad_nombre:
            by_name.setdefault(f.entidad_nombre, {})[f.fecha] = f

    results: List[Dict] = []
    for spec in cohort:
        series = by_name.get(spec["nombre"])
        if not series:
            results.append({"nombre": spec["nombre"], "episodio": spec["episodio"],
                            "found": False})
            continue
        bt = backtest_entity(series, all_series=by_name, salida=spec.get("salida"),
                             bank_type=spec.get("bank_type"))
        results.append({"nombre": spec["nombre"], "episodio": spec["episodio"],
                        "found": True, **bt})
    return results
