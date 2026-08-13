"""Validation engine — the structural invariants that make extraction trustworthy.

Extraction from a slide is only as good as what can be checked afterwards. This module
holds the checks, and every one of them is **derived from the structure of the data, not
from a particular client's deck** — which is what lets the same pipeline take a tracker it
has never seen and still fail closed on a mis-read number.

Four independent invariants, weakest to strongest:

1. **Range.** A proportion lives in [0, 100]. Catches decimal-point and axis misreads.
2. **Distribution.** A set of values that should sum to ~100 (single-choice questions,
   stacked bars) must actually do so. Catches a missed or duplicated series.
3. **Funnel monotonicity.** Each rung of a reach ladder is a subset of the one above it,
   so the numbers must not increase going down. Catches swapped rows and column drift.
4. **Cross-source agreement.** The same cell read twice — once by vision, once from the
   PDF's own text coordinates — must agree. Two independent methods landing on the same
   number is the strongest evidence available without a human.

Nothing here knows what "McDonald's" or "QSR" is. A distribution is any set of values the
extractor labelled as one; a funnel is the metric ladder already declared in
``engines/metrics.py``. A new client works on day one.

**Unchecked is not passed.** A cell no invariant covers is reported as `unchecked` and
carried to review, never quietly treated as verified. That distinction is the whole point:
a reviewer needs to know which numbers the machine actually confirmed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from modules.brand_intel.engines.metrics import TRACKER_VOCABULARY, Vocabulary

PASSED = "passed"
FAILED = "failed"
UNCHECKED = "unchecked"
CONFLICT = "conflict"

# A single-choice distribution rarely sums to exactly 100 — rounding to whole percentages
# across a dozen brands drifts a couple of points either way. Wider than that is a real
# extraction error, not rounding.
DISTRIBUTION_TOLERANCE = 3.0
# Two independent reads of the same printed number should be identical; 0.5 absorbs one
# source reporting a decimal the other rounded.
CROSS_SOURCE_TOLERANCE = 0.5


@dataclass
class Cell:
    """One extracted value, mutable so validation can annotate it in place."""

    key: str                       # stable id for reporting (row index, uuid, …)
    metric_code: str
    value: float
    wave_code: Optional[str] = None
    brand_slug: Optional[str] = None
    segment: str = "total"
    #: El atributo que la cifra califica, cuando la métrica se mide por atributo. Es una
    #: DIMENSIÓN, no un adorno: sin él, ocho atributos de una rejilla caen en la misma
    #: coordenada y el detector de duplicados los declara contradictorios entre sí —pasó
    #: con 144 celdas de una sola lámina del mazo de Ola 5.
    attribute: Optional[str] = None
    base_n: Optional[int] = None
    unit: str = "pct"
    coordinate_value: Optional[float] = None
    distribution_id: Optional[str] = None
    # Set by the extractor when several cells form one distribution (a single-choice
    # question, one stacked bar). Cells sharing an id are summed and checked against 100.
    validation: str = UNCHECKED
    validation_note: str = ""
    source_method: str = "vision"


@dataclass(frozen=True)
class ValidationReport:
    passed: int
    failed: int
    unchecked: int
    conflict: int
    findings: List[Dict[str, str]]

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.unchecked + self.conflict

    @property
    def clean(self) -> bool:
        """No cell failed and none conflicted. `unchecked` does not block."""
        return self.failed == 0 and self.conflict == 0

    def as_dict(self) -> Dict[str, object]:
        return {
            "total": self.total, "passed": self.passed, "failed": self.failed,
            "unchecked": self.unchecked, "conflict": self.conflict,
            "clean": self.clean, "findings": self.findings,
        }


def _mark(cell: Cell, status: str, note: str) -> None:
    """Apply a status, keeping the worst one a cell has earned.

    A cell that failed one invariant must not be upgraded to `passed` by a later one that
    happened to be satisfied — otherwise a weak check silently overrides a strong failure.
    """
    rank = {UNCHECKED: 0, PASSED: 1, CONFLICT: 2, FAILED: 3}
    if rank[status] >= rank[cell.validation]:
        cell.validation = status
        cell.validation_note = note


def check_range(cells: Sequence[Cell], vocab: Vocabulary = TRACKER_VOCABULARY) -> None:
    """A proportion outside [0, 100] is impossible, not merely suspicious."""
    for c in cells:
        m = vocab.get(c.metric_code)
        if m is None or m.kind != "proportion":
            continue
        if not 0.0 <= c.value <= 100.0:
            _mark(c, FAILED,
                  f"Valor {c.value} fuera del rango [0, 100] para una proporción.")


def check_distributions(cells: Sequence[Cell]) -> List[Dict[str, str]]:
    """Cells the extractor grouped as one distribution must sum to ~100."""
    findings: List[Dict[str, str]] = []
    groups: Dict[str, List[Cell]] = defaultdict(list)
    for c in cells:
        if c.distribution_id:
            groups[c.distribution_id].append(c)

    for gid, group in groups.items():
        total = sum(c.value for c in group)
        if abs(total - 100.0) <= DISTRIBUTION_TOLERANCE:
            for c in group:
                _mark(c, PASSED, f"Distribución «{gid}» suma {total:.1f}: consistente.")
        else:
            note = (f"Distribución «{gid}» suma {total:.1f}, fuera de 100 ± "
                    f"{DISTRIBUTION_TOLERANCE:.0f}: falta o sobra una serie.")
            for c in group:
                _mark(c, FAILED, note)
            findings.append({"kind": "distribution", "id": gid, "detail": note})
    return findings


def check_funnel_monotonicity(
    cells: Sequence[Cell], vocab: Vocabulary = TRACKER_VOCABULARY,
) -> List[Dict[str, str]]:
    """Each rung of the ladder must be ≤ the rung above it, per brand and wave.

    A study that declares no ladder has nothing to check here — which is the point: the
    invariant applies where a conversion sequence exists, not everywhere.
    """
    findings: List[Dict[str, str]] = []
    ladder_pos = {code: i for i, code in enumerate(vocab.ladder)}

    grouped: Dict[Tuple[Optional[str], Optional[str], str], List[Cell]] = defaultdict(list)
    for c in cells:
        if c.metric_code in ladder_pos:
            grouped[(c.wave_code, c.brand_slug, c.segment)].append(c)

    for (wave, brand, segment), group in grouped.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda c: ladder_pos[c.metric_code])
        ok = True
        for upper, lower in zip(ordered, ordered[1:]):
            # Two readings of the SAME rung are not a ladder step — comparing them here
            # would report a monotonicity break where the real issue is a duplicate, and
            # the duplicate check is what should speak to that.
            if upper.metric_code == lower.metric_code:
                continue
            if lower.value > upper.value + 0.01:
                note = (f"Embudo inconsistente en {brand or '—'} / {wave or '—'}: "
                        f"«{lower.metric_code}» ({lower.value}) supera a "
                        f"«{upper.metric_code}» ({upper.value}). Cada escalón es un "
                        "subconjunto del anterior y no puede crecer.")
                _mark(lower, FAILED, note)
                _mark(upper, FAILED, note)
                findings.append({"kind": "funnel", "id": f"{brand}/{wave}", "detail": note})
                ok = False
        if ok:
            for c in ordered:
                _mark(c, PASSED, "Embudo monótono decreciente: consistente.")
    return findings


def check_cross_source(cells: Sequence[Cell]) -> List[Dict[str, str]]:
    """Where a second, independent read exists, the two must agree.

    Agreement between vision and the PDF's own text coordinates is the strongest signal
    available without a human: two methods with unrelated failure modes landing on the
    same number. Disagreement is marked ``conflict`` rather than ``failed`` — one of them
    is right, and the reviewer decides which.
    """
    findings: List[Dict[str, str]] = []
    for c in cells:
        if c.coordinate_value is None:
            continue
        if abs(c.value - c.coordinate_value) <= CROSS_SOURCE_TOLERANCE:
            c.source_method = "both"
            _mark(c, PASSED,
                  f"Confirmado por dos fuentes independientes ({c.value} = "
                  f"{c.coordinate_value} por coordenadas).")
        else:
            note = (f"Discrepancia entre fuentes: visión leyó {c.value}, las coordenadas "
                    f"del PDF {c.coordinate_value}. Requiere revisión.")
            _mark(c, CONFLICT, note)
            findings.append({"kind": "cross_source", "id": c.key, "detail": note})
    return findings


def check_internal_duplicates(cells: Sequence[Cell]) -> List[Dict[str, str]]:
    """The same cell read on two different slides must carry the same number.

    Trackers repeat figures across charts — a funnel slide and an incidence slide often
    both show the same reach. That redundancy is free corroboration, and it is entirely
    generic: it needs no knowledge of which client or which layout produced it.
    """
    findings: List[Dict[str, str]] = []
    seen: Dict[Tuple, List[Cell]] = defaultdict(list)
    for c in cells:
        seen[(c.wave_code, c.brand_slug, c.metric_code, c.segment, c.attribute)].append(c)

    for key, group in seen.items():
        if len(group) < 2:
            continue
        values = {round(c.value, 2) for c in group}
        if len(values) == 1:
            for c in group:
                _mark(c, PASSED,
                      f"Coincide con la misma cifra leída en otra lámina ({group[0].value}).")
        else:
            note = (f"La misma celda aparece con valores distintos en varias láminas: "
                    f"{sorted(values)}. Una de las lecturas es incorrecta.")
            for c in group:
                _mark(c, CONFLICT, note)
            findings.append({"kind": "duplicate", "id": "/".join(str(k) for k in key),
                             "detail": note})
    return findings


def distribution_verdicts(cells: Sequence[Cell]) -> Dict[str, Tuple[str, str]]:
    """Judge distributions on their own, returning ``{id: (status, note)}``.

    This exists because *what was read* and *what the engagement tracks* are different
    sets. A deck may chart eighteen brands while the engagement declares seven; the
    distribution sums to 100 across all eighteen and never across the seven. Checking it
    after the engagement filter would therefore fail every real deck — the invariant has
    to be evaluated on the full slide, then carried over to the cells that survive.
    """
    scratch = [
        Cell(key=c.key, metric_code=c.metric_code, value=c.value,
             distribution_id=c.distribution_id)
        for c in cells
    ]
    check_distributions(scratch)
    out: Dict[str, Tuple[str, str]] = {}
    for c in scratch:
        if c.distribution_id and c.distribution_id not in out:
            out[c.distribution_id] = (c.validation, c.validation_note)
    return out


def validate(
    cells: Sequence[Cell],
    distribution_results: Optional[Dict[str, Tuple[str, str]]] = None,
    vocab: Vocabulary = TRACKER_VOCABULARY,
) -> ValidationReport:
    """Run every invariant over the extracted cells and summarise the outcome.

    ``distribution_results`` carries verdicts computed earlier on the full slide (see
    ``distribution_verdicts``). When supplied, distributions are not re-judged here — the
    subset that reached this point cannot be expected to sum to 100.
    """
    findings: List[Dict[str, str]] = []
    check_range(cells, vocab)
    if distribution_results is None:
        findings += check_distributions(cells)
    else:
        for c in cells:
            verdict = distribution_results.get(c.distribution_id or "")
            if verdict:
                _mark(c, verdict[0], verdict[1])
        findings += [
            {"kind": "distribution", "id": did, "detail": note}
            for did, (status, note) in distribution_results.items() if status == FAILED
        ]
    findings += check_funnel_monotonicity(cells, vocab)
    findings += check_internal_duplicates(cells)
    findings += check_cross_source(cells)

    counts = {PASSED: 0, FAILED: 0, UNCHECKED: 0, CONFLICT: 0}
    for c in cells:
        counts[c.validation] += 1

    return ValidationReport(
        passed=counts[PASSED], failed=counts[FAILED],
        unchecked=counts[UNCHECKED], conflict=counts[CONFLICT],
        findings=findings,
    )


def coverage_note(report: ValidationReport) -> str:
    """One line the report can show: how much of the extraction was actually verified."""
    if report.total == 0:
        return "No se extrajo ninguna celda."
    verified = report.passed / report.total * 100.0
    base = (f"{report.passed} de {report.total} celdas ({verified:.0f}%) confirmadas por "
            "una invariante estructural")
    if report.unchecked:
        base += (f"; {report.unchecked} sin verificación posible — se muestran, pero no "
                 "están confirmadas")
    if report.failed or report.conflict:
        base += (f"; {report.failed} inconsistentes y {report.conflict} en conflicto entre "
                 "fuentes, retenidas para revisión")
    return base + "."
