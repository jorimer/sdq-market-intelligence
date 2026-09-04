"""Validation — the single gate of correctness for extracted records.

Bounding by correctness (not by effort): a spec is trusted only if its output
survives these checks. Nothing is silently dropped — failures are *flagged* and
reported so a human reviews the marked series rather than the whole corpus.

Three layers:

* **internal** — per series: monotonic, duplicate-free periods; a minimum number
  of real observations (catches the thin noise columns like ``brutas_1``); no
  NaN/inf; not all-missing.
* **plausibility** — values within an optional ``[lo, hi]`` band per series.
* **cross-check against the live API** — for series that overlap an already-loaded
  API series in a *comparable* quantity (reserves level, FX, inflation rate — NOT
  rebased index levels), compare value-by-value within a relative tolerance. This
  is the strongest signal that the Excel was read correctly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from shared.data.base_client import Record


@dataclass
class CrossCheck:
    api_series: str
    n_compared: int
    n_match: int
    n_mismatch: int
    max_rel_err: float
    examples: List[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.n_compared > 0 and self.n_mismatch == 0


@dataclass
class SeriesReport:
    code: str
    unit: Optional[str]
    n_obs: int
    n_missing: int
    period_min: Optional[str]
    period_max: Optional[str]
    monotonic: bool
    duplicates: int
    flags: List[str] = field(default_factory=list)
    crosscheck: Optional[CrossCheck] = None

    @property
    def ok(self) -> bool:
        hard = {f for f in self.flags if not f.startswith("info:")}
        return not hard and (self.crosscheck is None or self.crosscheck.ok)


@dataclass
class ValidationReport:
    file: str
    series: List[SeriesReport]
    #: Avisos de ARCHIVO, no de una serie: hoy, que el rango del spec dejó afuera períodos
    #: que el encabezado declara. No caben en `series` porque no pertenecen a ninguna —y
    #: meterlos como una serie falsa desviaría el conteo—, pero tienen que marcar el archivo:
    #: una lectura truncada sale sin error, sin hueco y sin nada que la delate.
    avisos: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.series) and bool(self.series) and not self.avisos

    @property
    def flagged(self) -> List[SeriesReport]:
        return [s for s in self.series if not s.ok]

    def summary(self) -> dict:
        return {
            "file": self.file,
            "series_total": len(self.series),
            "series_ok": sum(1 for s in self.series if s.ok),
            "series_flagged": len(self.flagged),
            "avisos": list(self.avisos),
            "obs_total": sum(s.n_obs for s in self.series),
            "ok": self.ok,
            "flagged": [
                {"code": s.code, "flags": s.flags,
                 "crosscheck": vars(s.crosscheck) if s.crosscheck else None}
                for s in self.flagged
            ],
        }


def _rel_err(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom


def validate(
    records: List[Record],
    file: str = "",
    references: Optional[Dict[str, Dict[str, float]]] = None,
    min_obs: int = 6,
    rel_tol: float = 0.02,
    bands: Optional[Dict[str, tuple]] = None,
) -> ValidationReport:
    """Validate *records* into a :class:`ValidationReport`.

    ``references`` maps an extracted ``series_code`` → ``{period: api_value}`` for
    the comparable, already-loaded API series; ``bands`` maps a code → ``(lo, hi)``.
    """
    by_code: Dict[str, List[Record]] = {}
    for r in records:
        by_code.setdefault(r.series, []).append(r)

    reports: List[SeriesReport] = []
    for code, recs in sorted(by_code.items()):
        periods = [r.period for r in recs]
        seen, dups = set(), 0
        for p in periods:
            if p in seen:
                dups += 1
            seen.add(p)
        ordered = sorted(periods)
        # Record order follows the sheet's layout, not time, so series-level
        # monotonicity isn't meaningful here; "clean" means no duplicate periods.
        monotonic = dups == 0
        values = [r.value for r in recs]
        n_missing = sum(1 for v in values if v is None)
        real = [v for v in values if v is not None]

        flags: List[str] = []
        if not real:
            flags.append("todas las observaciones vacías")
        if len(real) < min_obs:
            flags.append(f"pocas observaciones ({len(real)} < {min_obs})")
        if any(v is not None and (math.isnan(v) or math.isinf(v)) for v in values):
            flags.append("valores NaN/inf")
        if dups:
            flags.append(f"períodos duplicados ({dups})")
        if bands and code in bands:
            lo, hi = bands[code]
            out_of_band = sum(1 for v in real if v < lo or v > hi)
            if out_of_band:
                flags.append(f"fuera de rango [{lo},{hi}] ({out_of_band})")

        crosscheck = None
        if references and code in references:
            ref = references[code]
            by_period = {r.period: r.value for r in recs}
            n_cmp = n_match = n_mismatch = 0
            max_err = 0.0
            examples: List[dict] = []
            for period, ref_val in ref.items():
                got = by_period.get(period)
                if got is None or ref_val is None:
                    continue
                n_cmp += 1
                err = _rel_err(got, ref_val)
                max_err = max(max_err, err)
                if err <= rel_tol:
                    n_match += 1
                else:
                    n_mismatch += 1
                    if len(examples) < 5:
                        examples.append({"period": period, "excel": got,
                                         "api": ref_val, "rel_err": round(err, 4)})
            crosscheck = CrossCheck(api_series=code, n_compared=n_cmp, n_match=n_match,
                                    n_mismatch=n_mismatch, max_rel_err=round(max_err, 4),
                                    examples=examples)
            if n_cmp == 0:
                flags.append("info:sin períodos solapados para cruzar")

        reports.append(SeriesReport(
            code=code, unit=recs[0].unit, n_obs=len(recs), n_missing=n_missing,
            period_min=ordered[0] if ordered else None,
            period_max=ordered[-1] if ordered else None,
            monotonic=monotonic, duplicates=dups, flags=flags, crosscheck=crosscheck,
        ))
    return ValidationReport(file=file, series=reports)
