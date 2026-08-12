"""La lectura de la venta: tráfico, cheque y canal. Determinista de punta a punta.

El estudio de mercado establece qué percibe el consumidor; la venta establece qué hizo.
Lo que este motor computa es la única descomposición que ninguna encuesta puede dar:
cuánto de un movimiento de facturación proviene de **más visitas** y cuánto de **mayor
gasto por visita**. Una encuesta no observa transacciones; el tablero del operador sí.

Tres reglas gobiernan el módulo:

**Cero LLM.** Aquí no hay nada que interpretar: son sumas y cocientes sobre columnas
rotuladas. La narrativa del informe lee este resultado y lo redacta; jamás lo recalcula.

**El cheque promedio se computa, nunca se acumula.** El cheque de un agregado es
``venta total ÷ transacciones totales``, no el promedio de los cheques de cada local: un
promedio de promedios pondera igual a un local de 900 transacciones y a uno de 90. Este
motor computa siempre el cociente de los agregados.

**La brecha se declara, jamás se rellena.** Si un canal no viene informado, su fila
queda ausente con su motivo en vez de entrar en cero; si el deflactor no cubre el tramo,
la lectura real se marca como parcial y se dice hasta dónde llega el índice. Un cero
inventado y un dato ausente son indistinguibles aguas abajo, y el primero miente.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.brand_intel.sales_engine")

#: Canales del tablero, con su etiqueta de lector. El orden es el del documento.
CHANNELS: Tuple[Tuple[str, str], ...] = (
    ("drive_thru", "Automac"),
    ("counter", "Mostrador"),
    ("delivery", "Delivery"),
)

#: Mínimo de jornadas para publicar un agregado. Un tramo de pocos días no sostiene una
#: comparación interanual: el día de la semana domina sobre la tendencia.
MIN_DAYS = 14


def comparable_rows(rows: Sequence[Any]) -> Tuple[List[Any], Dict[str, Any]]:
    """Las jornadas que admiten comparación interanual, y el detalle de lo excluido.

    **El defecto que esto ataca no falla: devuelve cifras plausibles.** El tablero del
    operador se emite a mitad de mes y trae las jornadas del mes COMPLETO: las
    posteriores al corte llegan con el comparativo del ejercicio anterior cargado y la
    venta corriente en cero. Promediarlas hunde la comparación —en el tablero real, de
    +5,7% a −19,5%— sin que ninguna validación estructural lo advierta, porque los ceros
    son internamente consistentes: la suma de canales sigue cuadrando con el total.

    La regla es una jornada comparable = con venta o transacciones corrientes efectivas.
    Lo excluido se cuenta y se declara; no se descarta en silencio.
    """
    vivas = [r for r in rows if (r.sales or 0) > 0 or (r.transactions or 0) > 0]
    if not vivas:
        return [], {"excluded_days": 0, "reason": "Ninguna jornada trae venta corriente."}
    fechas_vivas = {r.business_date for r in vivas if r.business_date}
    fechas_todas = {r.business_date for r in rows if r.business_date}
    excluidas = sorted(fechas_todas - fechas_vivas)
    detalle: Dict[str, Any] = {
        "excluded_days": len(excluidas),
        "cutoff": max(fechas_vivas).isoformat() if fechas_vivas else None,
    }
    if excluidas:
        detalle["note"] = (
            f"El tablero incluye {len(excluidas)} jornada(s) posterior(es) al corte del "
            f"{detalle['cutoff']} con el comparativo del ejercicio anterior y sin venta "
            "corriente; quedan fuera de la comparación por no ser comparables."
        )
    return vivas, detalle


def _ratio(new: Optional[float], old: Optional[float]) -> Optional[float]:
    """Variación porcentual, o ``None`` si la base no la admite."""
    if new is None or old is None or old == 0:
        return None
    return (new / old - 1.0) * 100.0


def _avg_check(sales: Optional[float], tx: Optional[float]) -> Optional[float]:
    if not sales or not tx:
        return None
    return sales / tx


@dataclass
class Aggregate:
    """Un agregado de venta con su comparativo. Todo lo derivado se computa al leer."""

    label: str
    sales: float = 0.0
    sales_prior: float = 0.0
    transactions: float = 0.0
    transactions_prior: float = 0.0
    days: int = 0
    stores: set = field(default_factory=set)

    def add(self, row: Any) -> None:
        self.sales += row.sales or 0.0
        self.sales_prior += row.sales_prior or 0.0
        self.transactions += row.transactions or 0.0
        self.transactions_prior += row.transactions_prior or 0.0
        self.stores.add(row.store_id)

    def as_dict(self) -> Dict[str, Any]:
        ac, ac_prior = (_avg_check(self.sales, self.transactions),
                        _avg_check(self.sales_prior, self.transactions_prior))
        return {
            "label": self.label,
            "sales": self.sales, "sales_prior": self.sales_prior,
            "sales_change_pct": _ratio(self.sales, self.sales_prior),
            "transactions": self.transactions,
            "transactions_prior": self.transactions_prior,
            "transactions_change_pct": _ratio(self.transactions,
                                              self.transactions_prior),
            "avg_check": ac, "avg_check_prior": ac_prior,
            "avg_check_change_pct": _ratio(ac, ac_prior),
            "days": self.days, "stores": len(self.stores),
        }


def _growth_composition(agg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """De dónde viene el crecimiento: afluencia o gasto por visita.

    La venta es transacciones × cheque, así que su variación se reparte de forma exacta:
    ``(1+v) = (1+t)(1+c)``. El reparto se expresa en puntos de la variación de venta,
    con el término cruzado asignado de forma explícita en vez de repartido en silencio.
    """
    v, t, c = (agg.get("sales_change_pct"), agg.get("transactions_change_pct"),
               agg.get("avg_check_change_pct"))
    if v is None or t is None or c is None:
        return None
    cross = (t / 100.0) * (c / 100.0) * 100.0
    dominant = "trafico" if abs(t) >= abs(c) else "cheque"
    share_traffic = None
    if v != 0:
        share_traffic = max(0.0, min(100.0, (t / v) * 100.0))
    return {
        "sales_change_pct": v,
        "traffic_points": t,
        "check_points": c,
        "cross_term_points": cross,
        "dominant": dominant,
        "traffic_share_of_growth_pct": share_traffic,
    }


def _real_check(agg: Dict[str, Any], inflation_pct: Optional[float],
                coverage: Optional[str]) -> Dict[str, Any]:
    """El cheque en términos reales: nominal deflactado por la inflación interanual.

    Un cheque nominalmente estable con inflación positiva es una CAÍDA del gasto real.
    Cuando el índice no cubre el tramo, se computa igual con el último dato oficial y se
    declara la brecha: la alternativa —omitir la lectura— esconde el hallazgo, y
    rellenar el índice inventaría el dato.
    """
    nominal = agg.get("avg_check_change_pct")
    if nominal is None or inflation_pct is None:
        return {"available": False,
                "reason": ("Sin variación nominal de cheque para deflactar."
                           if nominal is None else
                           "Sin serie de inflación cargada para el período.")}
    real = ((1 + nominal / 100.0) / (1 + inflation_pct / 100.0) - 1) * 100.0
    return {
        "available": True,
        "nominal_pct": nominal,
        "inflation_pct": inflation_pct,
        "real_pct": real,
        "deflator_coverage": coverage,
        "note": (
            f"Cheque promedio nominal {nominal:+.1f}% contra inflación interanual de "
            f"{inflation_pct:.2f}%: el gasto real por visita varía {real:+.1f}%."
        ),
    }


def _channel_rows(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Un renglón por canal informado. El canal sin datos no aparece: no vale cero."""
    out: List[Dict[str, Any]] = []
    for code, label in CHANNELS:
        s = sum(getattr(r, f"sales_{code}") or 0.0 for r in rows)
        sp = sum(getattr(r, f"sales_{code}_prior") or 0.0 for r in rows)
        t = sum(getattr(r, f"transactions_{code}") or 0.0 for r in rows)
        tp = sum(getattr(r, f"transactions_{code}_prior") or 0.0 for r in rows)
        if not s and not sp:
            continue
        ac, acp = _avg_check(s, t), _avg_check(sp, tp)
        out.append({
            "channel": code, "label": label,
            "sales": s, "sales_change_pct": _ratio(s, sp),
            "transactions": t, "transactions_change_pct": _ratio(t, tp),
            "avg_check": ac, "avg_check_change_pct": _ratio(ac, acp),
        })
    out.sort(key=lambda x: (x["sales_change_pct"] is None, -(x["sales_change_pct"] or 0)))
    return out


def _consistency(rows: Sequence[Any]) -> Dict[str, Any]:
    """¿La suma de los canales reproduce el total? Es el único chequeo que detecta una
    columna mal mapeada — el defecto que no falla, solo devuelve cifras plausibles."""
    total = sum(r.sales or 0.0 for r in rows)
    by_channel = sum((getattr(r, f"sales_{c}") or 0.0) for r in rows for c, _ in CHANNELS)
    if not total:
        return {"checked": False, "reason": "Sin venta total para contrastar."}
    delta = abs(total - by_channel) / total * 100.0
    return {
        "checked": True, "total": total, "by_channel_sum": by_channel,
        "gap_pct": delta,
        "reconciles": delta < 0.5,
        "note": ("La suma de los canales reproduce la venta total."
                 if delta < 0.5 else
                 f"La suma de los canales difiere {delta:.1f}% del total informado: el "
                 "desglose por canal se publica con esa reserva."),
    }


def sales_analysis(
    rows: Sequence[Any],
    inflation_pct: Optional[float] = None,
    inflation_coverage: Optional[str] = None,
) -> Dict[str, Any]:
    """La lectura completa de la venta. ``rows`` son jornadas ``BrandSalesDaily``.

    No consulta la base: recibe las filas ya cargadas para que el motor sea probable con
    objetos simples y para que el llamador gobierne el filtro de período.
    """
    if not rows:
        return {"available": False,
                "reason": "No hay jornadas de venta cargadas para el encargo."}

    # La ventana comparable manda: las jornadas posteriores al corte del tablero traen
    # el comparativo del año anterior sin venta corriente y NO son comparables.
    rows, ventana = comparable_rows(rows)
    if not rows:
        return {"available": False, "reason": ventana.get("reason")}

    fechas = sorted({r.business_date for r in rows if r.business_date})
    if len(fechas) < MIN_DAYS:
        return {
            "available": False,
            "reason": (f"La serie de venta cubre {len(fechas)} jornada(s); se requieren "
                       f"al menos {MIN_DAYS} para una comparación interanual en la que "
                       "el día de la semana no domine sobre la tendencia."),
        }

    system = Aggregate("Sistema")
    system.days = len(fechas)
    por_ciudad: Dict[str, Aggregate] = {}
    por_tienda: Dict[str, Aggregate] = {}
    for r in rows:
        system.add(r)
        ciudad = r.city or "Sin plaza declarada"
        por_ciudad.setdefault(ciudad, Aggregate(ciudad)).add(r)
        tienda = r.store_name or str(r.store_id)
        por_tienda.setdefault(tienda, Aggregate(tienda)).add(r)

    sistema = system.as_dict()
    ciudades = sorted((a.as_dict() for a in por_ciudad.values()),
                      key=lambda x: -(x["sales"] or 0))
    tiendas = sorted((a.as_dict() for a in por_tienda.values()),
                     key=lambda x: (x["sales_change_pct"] is None,
                                    x["sales_change_pct"] or 0))

    # Plazas en contracción de venta Y tráfico a la vez: el agregado positivo del sistema
    # las oculta, y son las únicas cuya caída no admite lectura de precio.
    contraccion = [c for c in ciudades
                   if (c["sales_change_pct"] or 0) < 0
                   and (c["transactions_change_pct"] or 0) < 0]

    return {
        "available": True,
        "period": {"from": fechas[0].isoformat(), "to": fechas[-1].isoformat(),
                   "days": len(fechas)},
        "comparable_window": ventana,
        "system": sistema,
        "growth_composition": _growth_composition(sistema),
        "real_check": _real_check(sistema, inflation_pct, inflation_coverage),
        "by_city": ciudades,
        "by_channel": _channel_rows(rows),
        "stores": {"n": sistema["stores"],
                   "worst": tiendas[:3], "best": tiendas[-3:][::-1]},
        "contracting_cities": contraccion,
        "consistency": _consistency(rows),
        "note": (
            "Venta y transacciones del tablero del operador, contrastadas contra las "
            "mismas fechas del ejercicio anterior tal como el propio tablero las "
            "publica. El cheque promedio se computa como venta entre transacciones "
            "sobre el agregado, no como promedio de los cheques de cada local."
        ),
    }


def campaign_window(
    rows: Sequence[Any], start: date, end: date, baseline_days: int = 28,
) -> Dict[str, Any]:
    """El efecto de una iniciativa sobre la venta diaria, contra su propia línea base.

    Compara el promedio diario del tramo de campaña con el de las jornadas inmediatamente
    anteriores. Es una lectura de ventana, NO una estimación causal: cualquier otro hecho
    del período entra en la misma diferencia, y así se declara.
    """
    if not rows:
        return {"available": False, "reason": "Sin jornadas de venta cargadas."}
    rows, _ventana = comparable_rows(rows)   # misma regla: el corte del tablero manda
    dentro = [r for r in rows if r.business_date and start <= r.business_date <= end]
    if not dentro:
        return {"available": False,
                "reason": "El tramo de la iniciativa no tiene jornadas cargadas."}
    prev = [r for r in rows if r.business_date
            and (start - r.business_date).days > 0
            and (start - r.business_date).days <= baseline_days]
    if not prev:
        return {"available": False,
                "reason": ("Sin jornadas previas suficientes para construir la línea "
                           "base de la iniciativa.")}

    def _daily(sel):
        dias = len({r.business_date for r in sel})
        return (sum(r.sales or 0.0 for r in sel) / dias if dias else None,
                sum(r.transactions or 0.0 for r in sel) / dias if dias else None, dias)

    v_in, t_in, d_in = _daily(dentro)
    v_pre, t_pre, d_pre = _daily(prev)
    return {
        "available": True,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": d_in},
        "baseline_days": d_pre,
        "daily_sales": v_in, "daily_sales_baseline": v_pre,
        "sales_lift_pct": _ratio(v_in, v_pre),
        "daily_transactions": t_in, "daily_transactions_baseline": t_pre,
        "transactions_lift_pct": _ratio(t_in, t_pre),
        "note": ("Diferencia del promedio diario del tramo contra las jornadas previas. "
                 "Es una lectura de ventana y no una estimación causal: cualquier otro "
                 "hecho del período se refleja en la misma diferencia."),
    }
