"""Orchestrator — URL/path → ExtractionSpec (cached) → Records → ValidationReport.

The spec cache is keyed by the workbook's ``structure_hash``, so each layout is
inferred (heuristically or by Claude) once and replayed thereafter; a genuine
layout change busts the key and re-infers automatically. This is what collapses
the marginal cost per file: the corpus is "one cheap inference + a validation"
per *layout*, not a hand-written parser per file.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.data.base_client import Record

from .catalog import CatalogEntry
from .download import DEFAULT_CACHE_DIR, fetch_excel
from .extract import extract_records
from .inference import infer_spec
from .interpreter import interpret_spec
from .spec import ExtractionSpec
from .validation import ValidationReport, validate
from .workbook import Workbook, load_workbook

logger = logging.getLogger("sdq.data.bcrd_excel.engine")

DEFAULT_SPEC_CACHE = Path("data/bcrd_excel/specs.json")
MIN_CONFIDENCE = 0.6


class SpecCache:
    """Disk-backed ``structure_hash → ExtractionSpec`` cache."""

    def __init__(self, path: Path | str = DEFAULT_SPEC_CACHE):
        self.path = Path(path)
        self._data: Dict[str, dict] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self._data = {}

    def get(self, structure_hash: str) -> Optional[ExtractionSpec]:
        d = self._data.get(structure_hash)
        return ExtractionSpec.from_dict(d) if d else None

    def set(self, structure_hash: str, spec: ExtractionSpec) -> None:
        self._data[structure_hash] = spec.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                             encoding="utf-8")


@dataclass
class IngestResult:
    file: str
    spec: ExtractionSpec
    records: List[Record]
    report: ValidationReport

    def summary(self) -> dict:
        return {
            "file": self.file,
            "method": self.spec.method,
            "confidence": self.spec.confidence,
            "orientation": self.spec.orientation,
            "records": len(self.records),
            "validation": self.report.summary(),
        }


def build_spec(
    wb: Workbook, file: str, *, cache: Optional[SpecCache] = None,
    min_confidence: float = MIN_CONFIDENCE, use_claude: bool = True,
    client: Any = None,
) -> ExtractionSpec:
    """Resolve a spec: cache → heuristic → (Claude if low confidence)."""
    h = wb.structure_hash()
    if cache is not None:
        hit = cache.get(h)
        if hit is not None:
            hit.method = "cached"
            return hit
    spec = infer_spec(wb, file)
    if spec.confidence < min_confidence and use_claude:
        try:
            spec = interpret_spec(wb, file, client=client)
        except Exception as e:  # noqa: BLE001 - keep the heuristic spec on any model/network error
            logger.warning("[bcrd_excel] intérprete Claude no usado para %s: %s", file, e)
    if cache is not None:
        cache.set(h, spec)
    return spec


def ingest_excel(
    source: str | Path | CatalogEntry, *,
    cache: Optional[SpecCache] = None,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    references: Optional[Dict[str, Dict[str, float]]] = None,
    bands: Optional[Dict[str, tuple]] = None,
    use_claude: bool = True,
    client: Any = None,
) -> IngestResult:
    """Full pipeline for one file: (download) → spec → extract → validate."""
    if isinstance(source, CatalogEntry):
        path = fetch_excel(source.url, cache_dir=cache_dir)
        file_label = source.url
    elif isinstance(source, str) and source.startswith("http"):
        path = fetch_excel(source, cache_dir=cache_dir)
        file_label = source
    else:
        path = Path(source)
        file_label = str(source)

    wb = load_workbook(path)
    spec = build_spec(wb, file_label, cache=cache, use_claude=use_claude, client=client)
    records = extract_records(wb, spec)
    report = validate(records, file=file_label, references=references, bands=bands)
    logger.info(
        "[bcrd_excel] %s: %d obs, %d series, validación %s (%s, conf %.2f)",
        file_label, len(records), len(report.series),
        "OK" if report.ok else "MARCADA", spec.method, spec.confidence,
    )
    return IngestResult(file=file_label, spec=spec, records=records, report=report)
