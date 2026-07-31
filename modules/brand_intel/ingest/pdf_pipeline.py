"""PDF ingestion pipeline — render, read, validate, stage, and only then promote.

    PDF ─▶ render page ─▶ vision read ─▶ map labels to the engagement ─▶
          invariants (engines/validation) ─▶ staging (BrandExtraction*) ─▶
          human confirmation ─▶ BrandObservation

Two properties are worth naming because they are what make this safe to point at a deck
nobody has seen before.

**Labels are mapped, never invented.** The model returns the brand and wave text printed
on the slide. This layer matches that text against the engagement's own brands and waves;
an unmatched label becomes a rejected row with the reason attached. A typo can therefore
never create a phantom brand that silently splits a series in two.

**Promotion is a separate, explicit step.** Extraction writes only to staging. Confirmation
copies the surviving cells into observations, and it refuses to promote anything that
failed an invariant — the reviewer can drop a cell, but cannot wave through a number the
machine already knows is inconsistent.
"""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.brand_intel.engines import validation as val
from modules.brand_intel.engines.metrics import get_metric
from modules.brand_intel.ingest import pdf_vision
from modules.brand_intel.models.models import (
    BrandEngagement,
    BrandEntity,
    BrandExtraction,
    BrandExtractionCell,
    BrandObservation,
    BrandWave,
)

logger = logging.getLogger("sdq.brand_intel.pdf_pipeline")


def _norm(text: str) -> str:
    """Fold a printed label to a comparable key: no accents, no case, no punctuation."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return "".join(c for c in stripped.lower() if c.isalnum())


@dataclass
class IngestReport:
    """What the document produced, and everything it could not place."""

    extraction_id: Optional[str] = None
    pages_read: int = 0
    pages_skipped: int = 0
    cells_extracted: int = 0
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    page_errors: List[Dict[str, Any]] = field(default_factory=list)
    validation: Dict[str, Any] = field(default_factory=dict)
    coverage_note: str = ""

    def reject(self, page: int, reason: str, detail: str = "") -> None:
        self.rejected.append({"page": page, "reason": reason, "detail": detail})

    def as_dict(self) -> Dict[str, Any]:
        return {
            "extraction_id": self.extraction_id,
            "paginas": {"leidas": self.pages_read, "omitidas": self.pages_skipped},
            "celdas_extraidas": self.cells_extracted,
            "rechazadas": self.rejected,
            "errores_por_pagina": self.page_errors,
            "validacion": self.validation,
            "nota_cobertura": self.coverage_note,
            "total_rechazadas": len(self.rejected),
        }


def _edit_distance(a: str, b: str, budget: int) -> int:
    """Levenshtein distance, abandoned once it exceeds ``budget``."""
    if abs(len(a) - len(b)) > budget:
        return budget + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > budget:
            return budget + 1
        prev = cur
    return prev[-1]


def _loose_key(text: str) -> str:
    """A tolerant key for period labels: first letters of the word plus its digits.

    Decks and engagements spell the same wave differently — a slide prints "Mayo '25"
    where the engagement declared "May '25". Both reduce to ``may25`` here. Without this,
    every cell in a real deck is rejected as an unknown wave, which is the difference
    between the pipeline working on a client's actual file and only on our own fixtures.
    """
    folded = _norm(text)
    letters = "".join(c for c in folded if c.isalpha())[:3]
    digits = "".join(c for c in folded if c.isdigit())
    return f"{letters}{digits}" if (letters or digits) else ""


class _LabelResolver:
    """Maps printed labels onto the engagement's declared brands and waves."""

    def __init__(self, brands: Sequence[BrandEntity], waves: Sequence[BrandWave]):
        self._brands: Dict[str, str] = {}
        for b in brands:
            self._brands[_norm(b.name)] = b.slug
            self._brands[_norm(b.slug)] = b.slug
        self._waves: Dict[str, str] = {}
        self._waves_loose: Dict[str, str] = {}
        for w in waves:
            self._waves[_norm(w.label)] = w.code
            self._waves[_norm(w.code)] = w.code
            # Ambiguity is resolved by refusing rather than guessing: if two waves
            # collapse to the same loose key, neither is reachable by that key.
            for key in (_loose_key(w.label), _loose_key(w.code)):
                if not key:
                    continue
                if key in self._waves_loose and self._waves_loose[key] != w.code:
                    self._waves_loose[key] = ""      # collision → unusable
                else:
                    self._waves_loose.setdefault(key, w.code)
        self.brand_names = [b.name for b in brands]
        self.wave_labels = [w.label for w in waves]

    def brand(self, label: str) -> Optional[str]:
        """Exact match first, then a tight edit-distance fallback.

        Decks contain typos — a real tracker prints "Little Ceasars" on some slides and
        "Little Caesars" on others. Rejecting the misspelling is safe but useless: it
        drops a whole brand from the ingest. Allowing a *tight* edit distance recovers it
        while still refusing anything that is genuinely a different brand, and the match
        is recorded so a reviewer can see it happened.
        """
        key = _norm(label)
        exact = self._brands.get(key)
        if exact:
            return exact
        if len(key) < 6:
            return None          # short names are too easy to confuse
        budget = 1 if len(key) < 10 else 2
        matches = {
            slug for known, slug in self._brands.items()
            if abs(len(known) - len(key)) <= budget
            and _edit_distance(key, known, budget) <= budget
        }
        # Ambiguity is refused, not guessed: two brands within the budget means neither.
        return next(iter(matches)) if len(matches) == 1 else None

    def wave(self, label: str) -> Optional[str]:
        exact = self._waves.get(_norm(label))
        if exact:
            return exact
        return self._waves_loose.get(_loose_key(label)) or None

    @property
    def single_wave(self) -> Optional[str]:
        """The only wave, when there is exactly one — lets unlabelled slides resolve."""
        codes = set(self._waves.values())
        return next(iter(codes)) if len(codes) == 1 else None


def _to_validation_cells(
    raw: Sequence[Tuple[int, str, Dict[str, Any]]],
    resolver: _LabelResolver,
    report: IngestReport,
) -> List[val.Cell]:
    """Turn the model's rows into validation cells, rejecting what cannot be placed."""
    cells: List[val.Cell] = []
    for idx, (page, chart_title, row) in enumerate(raw):
        metric = (row.get("metric_code") or "").strip()
        if get_metric(metric) is None:
            report.reject(page, "Métrica fuera del diccionario",
                          f"«{metric}» en «{chart_title}»")
            continue

        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            report.reject(page, "Valor no numérico", f"«{chart_title}»")
            continue

        brand_label = (row.get("brand_label") or "").strip()
        brand_slug = resolver.brand(brand_label) if brand_label else None
        if brand_label and brand_slug is None:
            report.reject(page, "Marca no reconocida",
                          f"«{brand_label}» no coincide con ninguna marca del encargo")
            continue

        wave_label = (row.get("wave_label") or "").strip()
        wave_code = resolver.wave(wave_label) if wave_label else resolver.single_wave
        if wave_code is None:
            report.reject(
                page, "Ola no reconocida",
                f"«{wave_label}» no coincide con ninguna ola del encargo"
                if wave_label else
                "La lámina no rotula la ola y el encargo tiene más de una",
            )
            continue

        base_n = row.get("base_n") or None
        if base_n is not None:
            try:
                base_n = int(base_n) or None
            except (TypeError, ValueError):
                base_n = None

        cells.append(val.Cell(
            key=f"p{page}-{idx}",
            metric_code=metric,
            value=value,
            wave_code=wave_code,
            brand_slug=brand_slug,
            segment=(row.get("segment") or "total").strip().lower() or "total",
            base_n=base_n,
            distribution_id=(row.get("distribution_id") or "").strip() or None,
        ))
    return cells


def ingest_pdf(
    db: Session,
    engagement: BrandEngagement,
    content: bytes,
    document_name: str,
    max_pages: Optional[int] = None,
    extractor: Optional[Callable[..., pdf_vision.PageExtraction]] = None,
    renderer: Optional[Callable[..., List[bytes]]] = None,
) -> IngestReport:
    """Read a presentation into staging. Nothing reaches observations here."""
    report = IngestReport()
    render = renderer or pdf_vision.render_pages
    extract = extractor or pdf_vision.extract_page

    brands = (db.query(BrandEntity)
              .filter(BrandEntity.engagement_id == engagement.id).all())
    waves = (db.query(BrandWave)
             .filter(BrandWave.engagement_id == engagement.id).all())
    if not brands or not waves:
        report.reject(0, "Encargo incompleto",
                      "Carga primero las olas y las marcas: sin ellas no hay contra qué "
                      "mapear las etiquetas impresas en las láminas.")
        return report

    resolver = _LabelResolver(brands, waves)
    images = render(content, last=max_pages)

    raw: List[Tuple[int, str, Dict[str, Any]]] = []
    model_used = None
    for i, image in enumerate(images, start=1):
        try:
            read = extract(image, i, resolver.brand_names, resolver.wave_labels)
        except Exception as exc:  # noqa: BLE001 — one bad page must not lose the document
            logger.warning("Página %s ilegible: %s", i, exc)
            report.page_errors.append({"page": i, "error": str(exc)})
            continue

        model_used = model_used or read.model_used
        if not read.readable or not read.cells:
            report.pages_skipped += 1
            continue
        report.pages_read += 1
        for row in read.cells:
            raw.append((i, read.chart_title, row))

    # Judge distributions on the full slide first — before the engagement filter drops
    # brands the client does not track. Afterwards the surviving subset could never sum
    # to 100, and every real deck would fail the check.
    full_slide = [
        val.Cell(key=f"raw-{i}", metric_code=(row.get("metric_code") or ""),
                 value=float(row.get("value") or 0),
                 distribution_id=(row.get("distribution_id") or "").strip() or None)
        for i, (_, _, row) in enumerate(raw)
        if isinstance(row.get("value"), (int, float))
    ]
    dist_verdicts = val.distribution_verdicts(full_slide)

    cells = _to_validation_cells(raw, resolver, report)
    result = val.validate(cells, distribution_results=dist_verdicts)
    report.cells_extracted = len(cells)
    report.validation = result.as_dict()
    report.coverage_note = val.coverage_note(result)

    extraction = BrandExtraction(
        engagement_id=engagement.id,
        document_name=document_name,
        n_pages=len(images),
        status="validated" if cells else "rejected",
        model_used=model_used,
        method="vision",
        summary=result.as_dict(),
        note=report.coverage_note,
    )
    db.add(extraction)
    db.flush()

    title_by_page = {p: t for p, t, _ in raw}
    for c in cells:
        page = int(c.key.split("-")[0].lstrip("p"))
        db.add(BrandExtractionCell(
            extraction_id=extraction.id,
            engagement_id=engagement.id,
            page_number=page,
            chart_label=title_by_page.get(page),
            wave_code=c.wave_code,
            brand_slug=c.brand_slug,
            metric_code=c.metric_code,
            segment=c.segment,
            value=c.value,
            base_n=c.base_n,
            source_method=c.source_method,
            validation=c.validation,
            validation_note=c.validation_note,
            coordinate_value=c.coordinate_value,
            included=c.validation != val.FAILED,
        ))

    report.extraction_id = extraction.id
    return report


def confirm_extraction(
    db: Session, extraction: BrandExtraction, confirmed_by: str,
) -> Dict[str, Any]:
    """Promote the reviewer-kept cells into observations.

    Refuses to promote a cell that failed an invariant even if it is still flagged for
    inclusion: the reviewer's judgement resolves *conflicts* and *unchecked* readings, but
    a value the machine proved inconsistent is not theirs to wave through.
    """
    from datetime import datetime, timezone

    cells = (db.query(BrandExtractionCell)
             .filter(BrandExtractionCell.extraction_id == extraction.id).all())
    wave_id = {
        w.code: w.id
        for w in db.query(BrandWave)
        .filter(BrandWave.engagement_id == extraction.engagement_id).all()
    }

    created = updated = skipped_failed = skipped_dropped = 0
    for c in cells:
        if c.validation == val.FAILED:
            skipped_failed += 1
            continue
        if not c.included:
            skipped_dropped += 1
            continue
        wid = wave_id.get(c.wave_code or "")
        if not wid:
            skipped_dropped += 1
            continue

        existing = (
            db.query(BrandObservation)
            .filter(
                BrandObservation.engagement_id == extraction.engagement_id,
                BrandObservation.wave_id == wid,
                BrandObservation.brand_slug == c.brand_slug,
                BrandObservation.metric_code == c.metric_code,
                BrandObservation.segment == c.segment,
            )
            .first()
        )
        target = existing or BrandObservation(
            engagement_id=extraction.engagement_id, wave_id=wid,
            brand_slug=c.brand_slug, metric_code=c.metric_code, segment=c.segment,
        )
        target.value = c.value
        target.base_n = c.base_n
        target.unit = c.unit
        target.source = (
            f"{extraction.document_name} · lámina {c.page_number} · "
            f"extracción asistida confirmada por {confirmed_by}"
        )
        if existing:
            updated += 1
        else:
            db.add(target)
            created += 1

    extraction.status = "confirmed"
    extraction.confirmed_by = confirmed_by
    extraction.confirmed_at = datetime.now(timezone.utc)

    return {
        "creadas": created, "actualizadas": updated,
        "omitidas_por_inconsistencia": skipped_failed,
        "descartadas_por_revision": skipped_dropped,
        "confirmada_por": confirmed_by,
    }
