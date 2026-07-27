"""Crosswalk: derive per-entity monthly financials from the raw SIB historical ledger.

Pivots :class:`SibHistoricalLedger` (long: 1 row per chart-of-accounts line) into
:class:`SibHistoricalFinancials` (wide: 1 row per entity per month) with the indicator
inputs that are *authentically* reconstructable from the accounting ledger. The mapping
is the crosswalk validated in ``docs/SIB_HISTORICO_FASE1_DISENO.md`` §3 (checked against
Banco Popular dic-2023: activos RD$755.3B, morosidad 0.63%, cobertura 472%).

What is NOT derived here: regulatory capital (patrimonio técnico / APR / solvencia Basel)
— it doesn't exist in the accounting balance and is absent pre-2004; ``apalancamiento_pct``
(patrimonio/activos) is the labelled leverage proxy instead. P&L magnitudes are stored as
the SB reports them (YTD-accumulated within the calendar year).
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger("sdq.banking.sib_historical_crosswalk")

# Balance nivel_2 buckets that make up liquid assets.
_LIQUIDOS_N2 = {"Efectivo y equivalentes de efectivo", "Inversiones", "Fondos interbancarios"}


def _f(x) -> Optional[float]:
    return float(x) if x is not None else None


def _add(acc: Optional[float], m: Optional[float]) -> Optional[float]:
    """Promote None→value on first hit, else sum. Keeps 'never seen' as None."""
    if m is None:
        return acc
    return (acc or 0.0) + m


def _ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or not den:
        return None
    return round(100.0 * num / den, 4)


def derive_group(rows: Iterable) -> Optional[Dict]:
    """Reduce all ledger rows of ONE (entidad_code, fecha) to a derived-financials dict.

    ``rows`` items expose ``estado, nivel_1..4, monto`` and the entity/date metadata
    (SQLAlchemy objects or any attribute-carrying record). Returns ``None`` if the group
    is empty.
    """
    meta = None
    activos = pasivos = patrim = depos = bruta = prov = venc = liq = None
    util = ingf = gasf = gaso = margb = None

    for r in rows:
        if meta is None:
            meta = r
        n1, n2, n3 = r.nivel_1, r.nivel_2, r.nivel_3
        m = _f(r.monto)
        if r.estado == "situacion":
            if n1 == "Activos" and n2 == "Total":
                activos = _add(activos, m)
            elif n1 == "Pasivos" and n2 == "Total":
                pasivos = _add(pasivos, m)
            elif n1 == "Patrimonio" and n2 == "Total":
                patrim = _add(patrim, m)
            elif n2 == "Depósitos del público":
                depos = _add(depos, m)
            elif n1 == "Activos" and n2 in _LIQUIDOS_N2:
                liq = _add(liq, m)
            elif n2 == "Cartera de créditos":
                if n3 and "Provisiones" in n3:
                    prov = _add(prov, m)                     # arrives negative
                else:
                    bruta = _add(bruta, m)
                    if n3 and (n3.startswith("Vencida (más de 90") or n3 == "Cobranza judicial"):
                        venc = _add(venc, m)
        elif r.estado == "resultados":
            if n1 == "Resultado del ejercicio":
                util = _add(util, m)
            elif n1 == "Ingresos financieros":
                ingf = _add(ingf, m)
            elif n1 == "Gastos financieros":
                gasf = _add(gasf, m)
            elif n1 == "Gastos operativos":
                gaso = _add(gaso, m)
            elif n1 == "Margen financiero bruto":
                margb = _add(margb, m)

    if meta is None:
        return None

    provisiones_abs = abs(prov) if prov is not None else None
    cartera_neta = (bruta + prov) if (bruta is not None and prov is not None) else bruta

    return {
        "entidad_code": meta.entidad_code,
        "entidad_nombre": meta.entidad_nombre,
        "tipo_entidad": meta.tipo_entidad,
        "sector": meta.sector,
        "fecha": meta.fecha,
        "ano": meta.ano,
        "mes": meta.mes,
        "activos_totales": activos,
        "cartera_bruta": bruta,
        "cartera_neta": cartera_neta,
        "provisiones": provisiones_abs,
        "cartera_vencida_90d": venc,
        "depositos_totales": depos,
        "patrimonio": patrim,
        "pasivos_totales": pasivos,
        "activos_liquidos": liq,
        "utilidad_neta": util,
        "ingresos_financieros": ingf,
        "gastos_financieros": gasf,
        "gastos_operativos": gaso,
        "margen_financiero_bruto": margb,
        "morosidad_pct": _ratio(venc, bruta),
        "cobertura_pct": _ratio(provisiones_abs, venc),
        "apalancamiento_pct": _ratio(patrim, activos),
        "snapshot_date": meta.snapshot_date,
    }


def derive_all(db, *, batch_size: int = 5000) -> int:
    """Rebuild ``sib_historical_financials`` from the whole ledger. Returns row count.

    Replace-all idempotency: the derived table is a pure function of the ledger snapshot,
    so it's cleared and rebuilt. Single ordered pass over the ledger (by entity, date)
    groups both estados of a period together with O(1) memory.
    """
    from modules.banking_score.models.models import (
        SibHistoricalFinancials,
        SibHistoricalLedger,
    )

    db.query(SibHistoricalFinancials).delete(synchronize_session=False)
    db.flush()

    q = (
        db.query(SibHistoricalLedger)
        .order_by(SibHistoricalLedger.entidad_code, SibHistoricalLedger.fecha)
        .yield_per(batch_size)
    )

    written = 0
    buf: List[Dict] = []
    cur_key = None
    group: List = []

    def flush_group():
        nonlocal written
        if not group:
            return
        row = derive_group(group)
        if row:
            buf.append(row)

    for r in q:
        key = (r.entidad_code, r.fecha)
        if key != cur_key:
            flush_group()
            group = []
            cur_key = key
            if len(buf) >= batch_size:
                db.bulk_insert_mappings(SibHistoricalFinancials, buf)
                db.flush()
                written += len(buf)
                buf = []
        group.append(r)
    flush_group()
    if buf:
        db.bulk_insert_mappings(SibHistoricalFinancials, buf)
        written += len(buf)
    db.commit()
    logger.info("sib_historical_crosswalk: %d filas derivadas", written)
    return written


def reconcile_entity(db, entidad_code: str, bank_id: str, *, tol: float = 0.02) -> List[Dict]:
    """Cross-check derived vs live (``sib_api``) data for one entity over the overlap.

    Compares ``activos_totales`` at shared period-ends between the derived historical
    financials and ``banking_data``. Returns a per-period list of
    ``{period, historical, live, rel_diff, ok}``. Full auto-matching of the ~180 entities
    to ``banks`` is deferred (the entity matcher has known pitfalls); callers pass an
    explicit (entidad_code, bank_id) pair.
    """
    from modules.banking_score.models.models import (
        BankingData,
        SibHistoricalFinancials,
    )

    live = {
        bd.period_end: _f(bd.activos_totales)
        for bd in db.query(BankingData).filter(BankingData.bank_id == bank_id).all()
        if bd.activos_totales is not None
    }
    out: List[Dict] = []
    for f in (
        db.query(SibHistoricalFinancials)
        .filter(SibHistoricalFinancials.entidad_code == entidad_code)
        .all()
    ):
        if f.fecha not in live or f.activos_totales is None:
            continue
        h = float(f.activos_totales)
        lv = live[f.fecha]
        rel = abs(h - lv) / lv if lv else None
        out.append({
            "period": f.fecha.isoformat(),
            "historical": h,
            "live": lv,
            "rel_diff": round(rel, 4) if rel is not None else None,
            "ok": (rel is not None and rel <= tol),
        })
    return sorted(out, key=lambda x: x["period"])
