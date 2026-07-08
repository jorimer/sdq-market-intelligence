"""Panel POINT-IN-TIME de decisiones de TPM + features macro.

Para cada reunión de la Junta Monetaria (fila = una decisión de TPM) arma el vector de
features usando SOLO el dato que estaba PUBLICADO a la fecha de la reunión, respetando el
rezago real de publicación de cada serie (``PUBLICATION_LAG_DAYS``). Es la regla que hace
creíble el backtest: nada de mirar hacia adelante.

Limitación declarada (documentada en el reporte): el BCRD no publica *vintages*, así que
usamos el valor FINAL de cada serie con su rezago típico de publicación, no el dato tal
como se veía ese día (que pudo revisarse después). Tratar los resultados como
direccionales, no como una reconstrucción exacta del dato disponible.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.service import _series_by_code, period_end_date
from modules.macro_monitor.tpm_modeling import features as F

# ── Series y su rezago típico de publicación (días tras el cierre del período) ──
# Rezagos aproximados observados en el calendario del BCRD: el IPC sale a mediados del
# mes siguiente; el IMAE ~45 días después; agregados monetarios ~40; reservas ~20; el
# tipo de cambio es diario (ya cerrado al fin de mes → ~1).
INFLATION_CODE = "bcrd.inflacion.inflacion.interanual"
IMAE_INDEX_CODE = "bcrd.xls.imae_2018.serie_original_indice"
FX_CODE = "bcrd.sector_externo.tasas_de_cambio.venta"
RESERVES_CODE = "bcrd.xls.reservas_internacionales.reservas_brutas"
M1_CODE = "bcrd.xls.agregados_monetarios.total_3_1_2"

PUBLICATION_LAG_DAYS: Dict[str, int] = {
    INFLATION_CODE: 15,
    IMAE_INDEX_CODE: 45,
    FX_CODE: 1,
    RESERVES_CODE: 20,
    M1_CODE: 40,
}


@dataclass(frozen=True)
class PanelRow:
    """Una decisión de TPM con su target y features point-in-time."""

    as_of: date                     # fecha de la reunión (decision_date)
    action: str                     # hold | cut | hike  (target del clasificador)
    tpm_level: Optional[float]      # nivel resultante (target de la regla; None en 14 antiguas)
    tpm_prev: Optional[float]       # nivel vigente ANTES de la decisión (= decisión previa)
    features: Dict[str, Optional[float]]  # FEATURE_NAMES → valor (None si falta el dato)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _shift_months(period: str, months: int) -> str:
    """Etiqueta ``YYYY-MM`` desplazada ``months`` (negativo = hacia atrás)."""
    y, m = int(period[:4]), int(period[5:7])
    idx = (y * 12 + (m - 1)) + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


class _Series:
    """Serie mensual con selección point-in-time por fecha de disponibilidad."""

    def __init__(self, obs: List[Tuple[str, float]], lag_days: int):
        # Solo períodos mensuales con valor; ordenados por fin de período.
        self._by_period: Dict[str, float] = {}
        rows: List[Tuple[date, str, float]] = []
        for period, value in obs:
            if value is None:
                continue
            end = period_end_date(period)
            if end is None or len(period) != 7:  # solo YYYY-MM
                continue
            rows.append((end, period, float(value)))
            self._by_period[period] = float(value)
        rows.sort(key=lambda r: r[0])
        self._rows = rows
        self._lag = timedelta(days=lag_days)

    def latest_available(self, as_of: date) -> Optional[Tuple[str, float]]:
        """(período, valor) de la última observación PUBLICADA en o antes de ``as_of``."""
        best: Optional[Tuple[str, float]] = None
        for end, period, value in self._rows:
            if end + self._lag <= as_of:
                best = (period, value)
            else:
                break  # rows ordenados: en cuanto uno no está disponible, los siguientes tampoco
        return best

    def value_at(self, period: str) -> Optional[float]:
        return self._by_period.get(period)

    def history_until(self, as_of: date) -> List[float]:
        """Valores disponibles (publicados) hasta ``as_of``, en orden temporal."""
        return [v for end, _p, v in self._rows if end + self._lag <= as_of]


def _load_series(db: Session) -> Dict[str, _Series]:
    grouped = _series_by_code(db, include_future=True)
    return {
        code: _Series(grouped.get(code, []), lag)
        for code, lag in PUBLICATION_LAG_DAYS.items()
    }


def _decisions_asc(db: Session) -> List[Tuple[date, str, Optional[float]]]:
    """Decisiones de TPM (fecha, sentido, nivel), de la más antigua a la más reciente."""
    from modules.macro_monitor.comunicados.service import _decisions_desc

    rows = _decisions_desc(db)
    out: List[Tuple[date, str, Optional[float]]] = []
    for r in rows:
        d = _parse_date(r.decision_date)
        if d is not None and r.action:
            out.append((d, r.action, r.tpm_level))
    out.sort(key=lambda t: t[0])
    return out


def _row_features(series: Dict[str, _Series], as_of: date, tpm_prev: Optional[float]) -> Dict[str, Optional[float]]:
    """Ensambla el vector de features point-in-time para una fecha de reunión."""
    infl_pit = series[INFLATION_CODE].latest_available(as_of)
    inflation = infl_pit[1] if infl_pit else None

    output_gap = F.output_gap_last(series[IMAE_INDEX_CODE].history_until(as_of))

    def _yoy(code: str) -> Optional[float]:
        pit = series[code].latest_available(as_of)
        if pit is None:
            return None
        period, now = pit
        return F.yoy(now, series[code].value_at(_shift_months(period, -12)))

    return {
        "inflation_gap": F.inflation_gap(inflation),
        "output_gap": output_gap,
        # Tasa real ex-ante: la TPM VIGENTE (previa) frente a la inflación disponible.
        "real_rate": F.real_rate(tpm_prev, inflation),
        "tpm_lag": tpm_prev,
        "fx_yoy": _yoy(FX_CODE),
        "reserves_yoy": _yoy(RESERVES_CODE),
        "m1_yoy": _yoy(M1_CODE),
    }


def build_panel(db: Session) -> List[PanelRow]:
    """Construye el panel completo (una fila por decisión de TPM), point-in-time."""
    series = _load_series(db)
    decisions = _decisions_asc(db)
    rows: List[PanelRow] = []
    prev_level: Optional[float] = None
    for as_of, action, level in decisions:
        rows.append(PanelRow(
            as_of=as_of, action=action, tpm_level=level, tpm_prev=prev_level,
            features=_row_features(series, as_of, prev_level),
        ))
        # El nivel vigente para la próxima decisión es el resultante de ésta (si se conoce).
        if level is not None:
            prev_level = level
    return rows


def current_feature_row(db: Session) -> Dict[str, Any]:
    """Features point-in-time HOY, para pronosticar la PRÓXIMA decisión.

    Usa el nivel de TPM vigente (última decisión conocida) como ``tpm_lag`` y ``today`` como
    fecha de corte para la disponibilidad de las series.
    """
    series = _load_series(db)
    decisions = _decisions_asc(db)
    prev_level = next((lvl for _d, _a, lvl in reversed(decisions) if lvl is not None), None)
    as_of = date.today()
    return {
        "as_of": as_of.isoformat(),
        "tpm_vigente": prev_level,
        "features": _row_features(series, as_of, prev_level),
    }
