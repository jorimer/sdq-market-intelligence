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
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.data.base_client import Record

from .catalog import CatalogEntry
from .download import DEFAULT_CACHE_DIR, fetch_excel
from .extract import _slug, default_prefix, extract_records
from .inference import data_sheets, infer_spec
from .interpreter import interpret_spec, name_ambiguous_rows
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
        self._flush()

    # El caché de NOMBRES no guarda specs: ``get`` coerciona a ExtractionSpec y reventaría
    # con un diccionario de rótulos. Va por su propia puerta, en el mismo archivo.
    def get_names(self, key: str) -> Optional[Dict[str, str]]:
        d = self._data.get(f"names:{key}")
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else None

    def set_names(self, key: str, names: Dict[str, str]) -> None:
        self._data[f"names:{key}"] = dict(names)
        self._flush()

    def _flush(self) -> None:
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


_AMBIGUOUS = re.compile(r"^(?P<base>.+)_r(?P<row>\d+)$")

#: Lo declara `extract` cuando el encabezado del cuadro dice que el período es corrido
#: desde enero. Vive acá también porque el renombrado tiene que conservarlo.
_SUFIJO_ACUMULADO = "_acumulado"


def _resolve_ambiguous_names(wb: Workbook, spec: ExtractionSpec, records: List[Record],
                             *, cache: Optional[SpecCache] = None, client: Any = None):
    """Renombra las series que la heurística desempató por número de fila.

    El sufijo ``_rNN`` es una coordenada, no un nombre: dice DÓNDE estaba la fila, no QUÉ
    mide. Cuando aparece, se le pide al modelo la lectura que haría un analista —bajo qué
    grupo cuelga cada fila— igual que la plataforma ya interpreta estados financieros de
    pensiones y seguros. El resultado se cachea por hash de estructura: se paga una vez
    por layout, no por corrida.

    Best-effort de punta a punta: sin clave, sin red o ante cualquier fallo, los registros
    vuelven intactos con su nombre anterior. Nunca se pierde una serie por esto.
    """
    rows_by_code: Dict[str, int] = {}
    for rec in records:
        leaf = str(rec.series).split(".")[-1]
        m = _AMBIGUOUS.match(leaf)
        if m:
            rows_by_code[rec.series] = int(m.group("row"))
    if not rows_by_code:
        return records

    cache_key = wb.structure_hash()
    named: Dict[int, str] = {}
    cached = cache.get_names(cache_key) if cache is not None else None
    if cached:
        named = {int(k): v for k, v in cached.items()}
    else:
        try:
            named = name_ambiguous_rows(
                wb.grid(spec.sheet), sorted(set(rows_by_code.values())), client=client)
            if cache is not None and named:
                cache.set_names(cache_key, {str(k): v for k, v in named.items()})
        except Exception as e:  # noqa: BLE001 — nombrar nunca puede costar la ingesta
            logger.warning("[bcrd_excel] nombrado semántico no aplicado a %s: %s",
                           spec.file, e)
            return records

    prefix = spec.code_prefix or ""
    rename: Dict[str, str] = {}
    used: set = set()
    for code, row in rows_by_code.items():
        pretty = named.get(row)
        if not pretty:
            continue
        head = code.rsplit(".", 1)[0]
        slug = ".".join(_slug(part) for part in pretty.split(">") if _slug(part))
        # El calificador de ACUMULADO no se pierde al renombrar. El nombre semántico
        # REEMPLAZA la hoja del código, así que un `agropecuario_acumulado_r46` volvía como
        # `ponderacion...agropecuario` — sin decir que es el corrido del año. Eran 96 de las
        # 163 series acumuladas del PIB por origen, y quedaban indistinguibles de las de
        # flujo salvo por el segmento de hoja. Lo que el cuadro declara sobre su período no
        # puede depender de si al modelo le tocó renombrar esa fila.
        base = _AMBIGUOUS.match(code.rsplit(".", 1)[1])
        if slug and base and base.group("base").endswith(_SUFIJO_ACUMULADO):
            slug = f"{slug}{_SUFIJO_ACUMULADO}"
        candidate = f"{head}.{slug}" if slug else code
        if candidate in used or candidate == code:
            continue
        used.add(candidate)
        rename[code] = candidate
    if not rename:
        return records
    logger.info("[bcrd_excel] %d series renombradas por lectura semántica", len(rename))
    return [replace(r, series=rename.get(r.series, r.series)) for r in records]


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
    # TODAS las hojas con datos, no solo la más densa: un libro del BCRD suele traer
    # varios cortes de la misma estadística en hojas distintas, y quedarse con una
    # descartaba el resto en silencio (15 hojas perdidas en 5 de los 23 canónicos).
    sheets = data_sheets(wb)
    spec = build_spec(wb, file_label, cache=cache, use_claude=use_claude, client=client)
    if len(sheets) <= 1:
        records = extract_records(wb, spec)
        if use_claude:
            records = _resolve_ambiguous_names(wb, spec, records, cache=cache, client=client)
    else:
        records = []
        for grid in sheets:
            sub = Workbook(path=wb.path, grids=[grid])
            try:
                sheet_spec = build_spec(sub, file_label, cache=cache,
                                        use_claude=use_claude, client=client)
                # El código lleva la hoja: dos cortes de la misma estadística son series
                # distintas y no deben colisionar (No Residentes vs Residentes).
                base = sheet_spec.code_prefix or default_prefix(file_label)
                sheet_spec.code_prefix = f"{base}.{_slug(grid.name)}"
                sheet_records = extract_records(sub, sheet_spec)
                if use_claude:
                    sheet_records = _resolve_ambiguous_names(
                        sub, sheet_spec, sheet_records, cache=cache, client=client)
                records.extend(sheet_records)
            except Exception as e:  # noqa: BLE001 — una hoja rota no cuesta las demás
                logger.warning("[bcrd_excel] hoja '%s' de %s no extraída: %s",
                               grid.name, file_label, e)
        if records:
            spec = build_spec(wb, file_label, cache=cache, use_claude=use_claude,
                              client=client)
    report = validate(records, file=file_label, references=references, bands=bands)
    logger.info(
        "[bcrd_excel] %s: %d obs, %d series, validación %s (%s, conf %.2f)",
        file_label, len(records), len(report.series),
        "OK" if report.ok else "MARCADA", spec.method, spec.confidence,
    )
    return IngestResult(file=file_label, spec=spec, records=records, report=report)
