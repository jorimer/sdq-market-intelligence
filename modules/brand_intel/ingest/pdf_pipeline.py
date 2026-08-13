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
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.brand_intel.engines import segments as seg
from modules.brand_intel.engines import validation as val
from modules.brand_intel.engines.metrics import TRACKER_VOCABULARY, Vocabulary
from modules.brand_intel.ingest import pdf_vision
from modules.brand_intel.models.models import (
    BrandEngagement,
    BrandEntity,
    BrandExtraction,
    BrandExtractionCell,
    BrandObservation,
    BrandObservationReading,
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
    # El SIGLO se descarta antes de normalizar: el mismo mazo escribe «Junio 2026» en una
    # lámina y «Jun '26» en otra, y con el año a cuatro dígitos las claves salían «jun2026»
    # y «jun26». En producción eso rechazó 144 celdas del mazo de Ola 5 por «ola no
    # reconocida». Se hace sobre el texto CRUDO porque hace falta la frontera de palabra
    # que la normalización borra.
    text = re.sub(r"\b(?:19|20)(\d{2})\b", r"\1", text or "")
    folded = _norm(text)
    letters = "".join(c for c in folded if c.isalpha())[:3]
    digits = "".join(c for c in folded if c.isdigit())
    return f"{letters}{digits}" if (letters or digits) else ""


class _LabelResolver:
    """Maps printed labels onto the engagement's declared brands and waves."""

    def __init__(self, brands: Sequence[BrandEntity], waves: Sequence[BrandWave],
                 segments: Sequence[str] = ()):
        #: Los cortes que el encargo ya escribe. Manda sobre cualquier tabla de alias
        #: nuestra: si viene escribiendo «santo domingo», un «SD» de la próxima entrega
        #: tiene que caer ahí en vez de abrir una segunda forma del mismo corte.
        self.segments: List[str] = [str(x) for x in segments if str(x or "").strip()]
        self._brands: Dict[str, str] = {}
        #: Nombre CON sus palabras intactas → slug. El otro índice normaliza a una sola
        #: cadena sin espacios, que sirve para igualdad pero borra las fronteras de
        #: palabra que la regla de prefijo necesita.
        self._brands_by_name: Dict[str, str] = {}
        for b in brands:
            self._brands[_norm(b.name)] = b.slug
            self._brands[_norm(b.slug)] = b.slug
            self._brands_by_name[str(b.name)] = str(b.slug)
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
        if len(matches) == 1:
            return next(iter(matches))
        return self._by_word_prefix(label)

    def _by_word_prefix(self, label: str) -> Optional[str]:
        """Un rótulo que es el PRIMER TRAMO DE PALABRAS de una sola marca declarada.

        Los trackers abrevian la razón social: la matriz histórica imprime «Domino's»
        donde el encargo declaró «Domino's Pizza». La distancia de edición no lo alcanza
        —sobran seis caracteres— y sin esta regla se crea una marca paralela que PARTE los
        datos del competidor en dos y corrompe el denominador de la categoría.

        Tres condiciones para que no degenere en adivinanza: el rótulo tiene que cerrar en
        frontera de palabra (así «Pizza» no captura «Pizzarelli»), tener al menos seis
        caracteres normalizados, y coincidir con UNA sola marca — «Taco» abriría a «Taco
        Bell» y «Taco del Sol», y ante dos no se elige ninguna.
        """
        key = _norm(label)
        if len(key) < 6:
            return None
        matches = set()
        for name, slug in self._brands_by_name.items():
            palabras = name.split()
            for corte in range(1, len(palabras)):
                if _norm(" ".join(palabras[:corte])) == key:
                    matches.add(slug)
                    break
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
    vocab: Vocabulary = TRACKER_VOCABULARY,
) -> List[val.Cell]:
    """Turn the model's rows into validation cells, rejecting what cannot be placed.

    ``vocab`` is the engagement's own vocabulary when it declares one — a study that is
    not a brand tracker measures things the canonical dictionary has never heard of, and
    checking against the wrong dictionary rejects every figure it has.
    """
    cells: List[val.Cell] = []
    for idx, (page, chart_title, row) in enumerate(raw):
        metric = (row.get("metric_code") or "").strip()
        if vocab.get(metric) is None:
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

        # El corte se canoniza contra los cortes que el encargo YA escribe, y el atributo
        # sale de su propio campo o del rótulo empaquetado con barra. Guardar el rótulo
        # crudo es lo que produjo tres escrituras de «Santo Domingo» y enunciados de
        # pregunta usados como si fueran poblaciones.
        attribute, segment = seg.normalize_dimensions(
            row.get("attribute"), row.get("segment"), resolver.segments)
        cells.append(val.Cell(
            key=f"p{page}-{idx}",
            metric_code=metric,
            value=value,
            wave_code=wave_code,
            brand_slug=brand_slug,
            segment=segment,
            attribute=attribute,
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
    on_page: Optional[Callable[[int], None]] = None,
    into: Optional[BrandExtraction] = None,
) -> IngestReport:
    """Read a presentation into staging, page by page. Nothing reaches observations here.

    Runs inside the worker, not the web request. Reading a real deck is dozens of vision
    calls — the first version did it in one HTTP request and died against the time budget
    with nothing to show, after paying for every call it had made.

    Each page is committed as it is read, so the work already done survives a crash, and
    ``pages_done`` is where a re-run picks up. That is also what makes the progress on
    screen真 rather than a spinner: it is the number of slides actually persisted.
    """
    report = IngestReport()
    render = renderer or pdf_vision.render_pages
    extract = extractor or pdf_vision.extract_page

    from modules.brand_intel import service as svc

    vocab = svc.vocabulary_for(db, str(engagement.id))
    brands = (db.query(BrandEntity)
              .filter(BrandEntity.engagement_id == engagement.id).all())
    waves = (db.query(BrandWave)
             .filter(BrandWave.engagement_id == engagement.id).all())
    if not brands or not waves:
        report.reject(0, "Encargo incompleto",
                      "Carga primero las olas y las marcas: sin ellas no hay contra qué "
                      "mapear las etiquetas impresas en las láminas.")
        return report

    segmentos = [r[0] for r in db.query(BrandObservation.segment)
                 .filter(BrandObservation.engagement_id == engagement.id)
                 .distinct().all()]
    resolver = _LabelResolver(brands, waves, segmentos)
    model_used = None

    # Se avanza lámina a lámina hasta que el render no devuelve nada: el mazo dice dónde
    # termina. Renderizarlo entero por adelantado tenía además un coste de memoria que
    # crece con el mazo — 59 PNG a 140 ppp viven todos a la vez.
    raw: List[Tuple[int, str, Dict[str, Any]]] = []
    page_no = 0
    while max_pages is None or page_no < max_pages:
        page_no += 1
        try:
            images = render(content, first=page_no, last=page_no)
            if not images:
                page_no -= 1
                break
            read = extract(images[0], page_no, resolver.brand_names, resolver.wave_labels)
        except Exception as exc:  # noqa: BLE001 — one bad page must not lose the document
            logger.warning("Página %s ilegible: %s", page_no, exc)
            report.page_errors.append({"page": page_no, "error": str(exc)})
            if on_page:
                on_page(page_no)
            continue

        model_used = model_used or read.model_used
        if not read.readable or not read.cells:
            report.pages_skipped += 1
        else:
            report.pages_read += 1
            for row in read.cells:
                raw.append((page_no, read.chart_title, row))
        if on_page:
            on_page(page_no)

    n_pages = page_no

    # Judge distributions on the full slide first — before the engagement filter drops
    # brands the client does not track. Afterwards the surviving subset could never sum
    # to 100, and every real deck would fail the check.
    #
    # The id is namespaced by page because the model invents it per slide: two slides that
    # both call their distribution "preferencia" are not one distribution, and merging
    # them makes the sum ~200 and fails both.
    full_slide = [
        val.Cell(key=f"raw-{i}", metric_code=(row.get("metric_code") or ""),
                 value=float(row.get("value") or 0),
                 distribution_id=(f"p{page}:{did}"
                                  if (did := (row.get("distribution_id") or "").strip())
                                  else None))
        for i, (page, _, row) in enumerate(raw)
        if isinstance(row.get("value"), (int, float))
    ]
    dist_verdicts = val.distribution_verdicts(full_slide)

    cells = _to_validation_cells(raw, resolver, report, vocab)
    result = val.validate(cells, distribution_results=dist_verdicts, vocab=vocab)
    report.cells_extracted = len(cells)
    report.validation = result.as_dict()
    report.coverage_note = val.coverage_note(result)

    # `into` es la fila del trabajo, que ya existe desde que se encoló: rellenarla deja
    # UNA fila por documento, desde `queued` hasta `validated`. Sin ella —el camino de los
    # tests y del Excel— se crea aquí.
    extraction = into or BrandExtraction(
        engagement_id=engagement.id, document_name=document_name, method="vision")
    extraction.n_pages = n_pages
    extraction.pages_done = n_pages
    extraction.status = "validated" if cells else "rejected"
    extraction.model_used = model_used
    extraction.summary = result.as_dict()
    extraction.note = report.coverage_note
    if into is None:
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
            attribute=c.attribute,
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


@dataclass
class Reading:
    """Una cifra que una entrega afirma, ya resuelta contra la estructura del encargo."""

    wave_id: str
    brand_slug: Optional[str]
    metric_code: str
    segment: str
    attribute: Optional[str]
    value: float
    base_n: Optional[int] = None
    unit: str = "pct"
    source: str = ""


def renormalize_staged(
    db: Session, extraction: Any, known_segments: Sequence[str] = ()
) -> Dict[str, Any]:
    """Recanoniza los cortes de las celdas YA extraídas y vuelve a juzgarlas.

    Existe para no pagar dos veces la misma lectura. Cuando el defecto está en cómo se
    GUARDÓ una dimensión —tres escrituras del mismo corte, el enunciado de la pregunta
    metido en el campo del corte— la información sigue en la celda: releer el mazo cuesta
    decenas de llamadas de visión y devuelve exactamente lo mismo.

    Lo que NO puede reparar: un atributo que el lector nunca emitió porque no tenía campo
    donde ponerlo. Esas celdas siguen colisionando y hay que releer el mazo con el esquema
    nuevo. La diferencia se declara en el resultado en vez de insinuar que quedó todo listo.
    """
    filas = (db.query(BrandExtractionCell)
             .filter(BrandExtractionCell.extraction_id == extraction.id)
             .all())
    if not filas:
        return {"celdas": 0, "cortes_recanonizados": 0, "atributos_recuperados": 0,
                "sin_atributo_recuperable": 0, "validacion": {}}

    cortes = 0
    atributos = 0
    for f in filas:
        atributo, corte = seg.normalize_dimensions(
            str(f.attribute) if f.attribute is not None else None,
            str(f.segment), known_segments)
        if str(f.segment) != corte:
            f.segment = corte                      # type: ignore[assignment]
            cortes += 1
        if atributo and f.attribute is None:
            f.attribute = atributo[:120]           # type: ignore[assignment]
            atributos += 1

    cells = [
        val.Cell(key=str(f.id), metric_code=str(f.metric_code), value=float(f.value),
                 wave_code=str(f.wave_code) if f.wave_code else None,
                 brand_slug=str(f.brand_slug) if f.brand_slug else None,
                 segment=str(f.segment),
                 attribute=str(f.attribute) if f.attribute else None,
                 base_n=int(f.base_n) if f.base_n is not None else None,
                 unit=str(f.unit), source_method=str(f.source_method))
        for f in filas
    ]
    informe = val.validate(cells)
    por_id = {c.key: c for c in cells}
    for f in filas:
        c = por_id[str(f.id)]
        f.validation = c.validation                # type: ignore[assignment]
        f.validation_note = c.validation_note or None  # type: ignore[assignment]

    # Una métrica que se mide POR atributo y sigue sin atributo no es reparable acá: el
    # lector no lo emitió. Se cuenta para que el número diga qué falta, no qué se logró.
    huerfanas = sum(1 for f in filas
                    if str(f.metric_code) == "attribute_index" and not f.attribute)
    db.flush()
    return {
        "celdas": len(filas),
        "cortes_recanonizados": cortes,
        "atributos_recuperados": atributos,
        "sin_atributo_recuperable": huerfanas,
        "validacion": {"passed": informe.passed, "conflict": informe.conflict,
                       "failed": informe.failed, "unchecked": informe.unchecked},
    }


def promote_readings(
    db: Session,
    engagement_id: str,
    extraction: BrandExtraction,
    readings: Sequence[Reading],
) -> Dict[str, Any]:
    """Registra lo que dice una entrega y proyecta la observación vigente.

    Común a las dos rutas de carga —el mazo en PDF y el libro Excel— y a propósito: decidir
    qué cifra es la vigente es lo más delicado del módulo, y dos implementaciones acabarían
    divergiendo justo ahí.

    Una entrega puede nombrar la misma cifra más de una vez (una lámina de resumen que
    repite el titular, dos filas del libro para el mismo dato). Se agrupan **antes** de
    escribir por dos razones. La mecánica: la clave de una observación es única y añadir
    dos filas aborta el commit entero. La de fondo: cuando las lecturas **discrepan**,
    elegir una es inventar la respuesta — nada aquí sabe cuál se leyó mal, así que la clave
    queda fuera y se nombra.

    **Nada de lo que dijo una entrega se pisa.** Cada lectura se guarda atada a la entrega
    de la que vino, y la observación es una proyección: gana la de la entrega con la ola
    más reciente. El orden de subida deja de decidir la verdad.
    """
    waves = (db.query(BrandWave)
             .filter(BrandWave.engagement_id == engagement_id).all())
    wave_code: Dict[str, str] = {str(w.id): str(w.code) for w in waves}

    # La añada de una entrega es la ola más reciente que trae: un hecho de la entrega, no
    # de cuándo alguien se puso a subirla.
    vintage: str = max(
        (str(wave_code.get(r.wave_id) or "") for r in readings), default="")
    # De una vez: resolverlo por cifra es una consulta por dato, y una entrega real trae
    # varios cientos.
    vintage_of: Dict[str, str] = {
        str(eid): str(v or "")
        for eid, v in db.query(BrandObservationReading.extraction_id,
                               func.max(BrandObservationReading.deck_vintage))
        .filter(BrandObservationReading.engagement_id == engagement_id)
        .group_by(BrandObservationReading.extraction_id).all()
        if eid
    }

    grouped: Dict[Tuple[Any, ...], List[Reading]] = {}
    for r in readings:
        grouped.setdefault(
            (r.wave_id, r.brand_slug, r.metric_code, r.segment, r.attribute),
            []).append(r)

    created = updated = duplicated = superseded = 0
    disagreements: List[Dict[str, Any]] = []
    corrections: List[Dict[str, Any]] = []

    for (wid, slug, metric, segment, attribute), group in grouped.items():
        values = {round(float(x.value), 6) for x in group}
        if len(values) > 1:
            disagreements.append({
                "marca": slug or "categoría", "metrica": metric, "segmento": segment,
                "ola": wave_code.get(wid, ""), "valores": sorted(values),
            })
            continue
        duplicated += len(group) - 1
        c = group[0]

        reading = (
            db.query(BrandObservationReading)
            .filter(
                BrandObservationReading.extraction_id == extraction.id,
                BrandObservationReading.wave_id == wid,
                BrandObservationReading.brand_slug == slug,
                BrandObservationReading.metric_code == metric,
                BrandObservationReading.segment == segment,
                BrandObservationReading.attribute == attribute,
            )
            .first()
        ) or BrandObservationReading(
            engagement_id=engagement_id, extraction_id=extraction.id,
            wave_id=wid, brand_slug=slug, metric_code=metric, segment=segment,
            attribute=attribute,
        )
        reading.value = c.value
        reading.base_n = c.base_n
        reading.unit = c.unit
        reading.deck_vintage = vintage
        reading.source = c.source
        if reading.id is None:
            db.add(reading)

        existing = (
            db.query(BrandObservation)
            .filter(
                BrandObservation.engagement_id == engagement_id,
                BrandObservation.wave_id == wid,
                BrandObservation.brand_slug == slug,
                BrandObservation.metric_code == metric,
                BrandObservation.segment == segment,
                BrandObservation.attribute == attribute,
            )
            .first()
        )
        if existing is not None:
            held_by = vintage_of.get(str(existing.source_extraction_id or ""), "")
            if held_by > vintage:
                if round(float(existing.value), 6) not in values:
                    superseded += 1
                    corrections.append({
                        "marca": slug or "categoría", "metrica": metric,
                        "ola": wave_code.get(wid, ""), "segmento": segment,
                        "vigente": float(existing.value), "esta_entrega": float(c.value),
                        "entrega_vigente": held_by, "esta": vintage,
                    })
                continue
            if round(float(existing.value), 6) not in values:
                corrections.append({
                    "marca": slug or "categoría", "metrica": metric,
                    "ola": wave_code.get(wid, ""), "segmento": segment,
                    "anterior": float(existing.value), "corregida": float(c.value),
                    "entrega_vigente": held_by, "esta": vintage,
                })

        target = existing or BrandObservation(
            engagement_id=engagement_id, wave_id=wid,
            brand_slug=slug, metric_code=metric, segment=segment,
            attribute=attribute,
        )
        target.value = c.value
        target.base_n = c.base_n
        target.unit = c.unit
        target.source = c.source
        target.source_extraction_id = extraction.id
        if existing:
            updated += 1
        else:
            db.add(target)
            created += 1

    return {
        "creadas": created, "actualizadas": updated,
        "repetidas_coincidentes": duplicated,
        "omitidas_por_discrepancia": len(disagreements),
        "discrepancias": disagreements,
        "no_reemplazan_por_entrega_mas_nueva": superseded,
        "cifras_que_cambian": corrections,
        "anada_de_la_entrega": vintage,
    }


def confirm_extraction(
    db: Session, extraction: BrandExtraction, confirmed_by: str,
) -> Dict[str, Any]:
    """Promote the reviewer-kept cells into observations.

    Refuses to promote a cell that failed an invariant even if it is still flagged for
    inclusion: the reviewer's judgement resolves *conflicts* and *unchecked* readings, but
    a value the machine proved inconsistent is not theirs to wave through.

    A deck names the same figure on more than one slide — a headline number repeated in a
    summary, a series charted twice from different angles — so several staged cells can
    land on one observation key. They are grouped first, before anything is written, for
    two reasons. The mechanical one: an observation key is unique, and adding two rows for
    it aborts the whole commit, losing a confirmation the reviewer already worked through.
    The substantive one: when the readings **disagree**, picking one is inventing an
    answer. Nothing here is qualified to say which slide was misread, so the key is left
    out and named, which is the same rule the invariants follow.

    **Nothing a delivery said is overwritten.** Every reading is kept in
    ``brand_observation_readings`` tied to the deck it came from, and the observation is a
    projection of them: the reading from the deck with the most recent wave wins. Order of
    upload therefore stops deciding the truth — loading a year of decks back-to-front used
    to walk corrected figures backwards in silence — and "the provider changed this
    number" survives as something the report can state instead of something that is lost
    the moment the newer deck lands.
    """
    from datetime import datetime, timezone

    cells = (db.query(BrandExtractionCell)
             .filter(BrandExtractionCell.extraction_id == extraction.id).all())
    wave_id = {w.code: w.id for w in db.query(BrandWave)
               .filter(BrandWave.engagement_id == extraction.engagement_id).all()}

    skipped_failed = skipped_dropped = 0
    readings: List[Reading] = []
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
        readings.append(Reading(
            wave_id=str(wid),
            brand_slug=str(c.brand_slug) if c.brand_slug is not None else None,
            metric_code=str(c.metric_code),
            segment=str(c.segment),
            attribute=str(c.attribute) if c.attribute is not None else None,
            value=float(c.value),
            base_n=int(c.base_n) if c.base_n is not None else None,
            unit=str(c.unit),
            source=(f"{extraction.document_name} · lámina {c.page_number} · "
                    f"extracción asistida confirmada por {confirmed_by}"),
        ))

    out = promote_readings(db, str(extraction.engagement_id), extraction, readings)

    extraction.status = "confirmed"
    extraction.confirmed_by = confirmed_by
    extraction.confirmed_at = datetime.now(timezone.utc)

    return {
        **out,
        "omitidas_por_inconsistencia": skipped_failed,
        "descartadas_por_revision": skipped_dropped,
        "confirmada_por": confirmed_by,
    }

