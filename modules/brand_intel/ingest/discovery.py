"""Structure discovery — read a deck's own vocabulary before anything is declared.

An engagement is created with a client and a focal brand, nothing more. The strict
pipeline in ``pdf_pipeline`` then maps printed labels onto the engagement's declared
waves and brands — which works only once those exist. Until now they existed solely as
a side effect of the provider's Excel workbook, so a client who has slides and no
workbook could create an engagement and then find every cell rejected.

This module closes that gap without weakening the guarantee that makes the strict
pipeline trustworthy. It **proposes**; a person adopts. Nothing here writes an entity.

Two passes, deliberately asymmetric in cost:

* **Waves come from the PDF's text layer** — free, exhaustive, no model call. Wave
  labels are dates, and dates have a shape a regex can find on every page at once.
* **Brands come from a vision pass over a handful of slides** — brand names have no
  shape to match, so the model reads them. Sampling a few slides is enough because a
  tracker repeats its competitive set on every chart; reading all 59 would cost as much
  as the real ingest and tell us nothing more.

Both return candidates with the evidence attached — how often each label appears and on
which slides — because a reviewer adopting a competitive set needs to see that
"Little Ceasars" on one slide and "Little Caesars" on another are the same chain.
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.brand_intel.discovery")

# A label must recur before it is worth proposing. A tracker prints its wave on every
# chart; a stray date in a footnote or a methodology slide appears once or twice.
MIN_WAVE_OCCURRENCES = 3
MIN_BRAND_OCCURRENCES = 2
BRAND_SAMPLE_PAGES = 5

# Month vocabulary. Spanish first because that is the market, English because the next
# client's deck may not be — the whole point of this module is that it is not written
# for one tracker.
_MONTHS: Dict[str, int] = {
    "ene": 1, "enero": 1, "jan": 1, "january": 1,
    "feb": 2, "febrero": 2, "february": 2,
    "mar": 3, "marzo": 3, "march": 3,
    "abr": 4, "abril": 4, "apr": 4, "april": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6, "june": 6,
    "jul": 7, "julio": 7, "july": 7,
    "ago": 8, "agosto": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "septiembre": 9, "september": 9,
    "oct": 10, "octubre": 10, "october": 10,
    "nov": 11, "noviembre": 11, "november": 11,
    "dic": 12, "diciembre": 12, "dec": 12, "december": 12,
}

# Longest alternatives first so "septiembre" is not truncated to "sep", and the
# four-digit year is tried before the two-digit one so "2025" never reads as "20".
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_RE = re.compile(
    rf"\b({_MONTH_ALT})\.?\s*[''`´]?\s*(20\d{{2}}|\d{{2}})\b",
    re.IGNORECASE,
)
# Quarters: "Q1 2025", "T1 '25" — the other common way a tracker names a wave.
_QUARTER_RE = re.compile(r"\b([QT])\s*([1-4])\s*[''`´]?\s*(20\d{2}|\d{2})\b", re.IGNORECASE)


def _year(raw: str) -> int:
    """Two-digit years are this century: a tracker deck is not from 1925."""
    n = int(raw)
    return n if n >= 1000 else 2000 + n


@dataclass(frozen=True)
class WaveCandidate:
    """A wave the deck talks about, with the evidence for it."""

    code: str                     # "2025-11" — stable key, derived not printed
    label: str                    # "Nov '25" — the most common printed spelling
    period_date: date             # first of the month: the deflator's anchor
    occurrences: int
    pages: Tuple[int, ...]
    spellings: Tuple[str, ...]    # every printed form seen, for the reviewer

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code, "label": self.label,
            "period_date": self.period_date.isoformat(),
            "occurrences": self.occurrences, "pages": list(self.pages[:8]),
            "spellings": list(self.spellings),
        }


@dataclass(frozen=True)
class BrandCandidate:
    """A brand printed in the deck, with the evidence for it."""

    name: str                     # the most common printed spelling
    occurrences: int
    pages: Tuple[int, ...]
    spellings: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "occurrences": self.occurrences,
            "pages": list(self.pages[:8]), "spellings": list(self.spellings),
        }


@dataclass
class StructureProposal:
    """What the deck appears to contain. Nothing here is adopted."""

    waves: List[WaveCandidate] = field(default_factory=list)
    brands: List[BrandCandidate] = field(default_factory=list)
    n_pages: int = 0
    pages_sampled: Tuple[int, ...] = ()
    brand_pass_error: str = ""
    discarded_waves: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "waves": [w.as_dict() for w in self.waves],
            "brands": [b.as_dict() for b in self.brands],
            "n_pages": self.n_pages,
            "pages_sampled": list(self.pages_sampled),
            "brand_pass_error": self.brand_pass_error,
            "discarded_waves": self.discarded_waves,
            "note": self._note(),
        }

    def _note(self) -> str:
        parts = [
            f"{len(self.waves)} ola(s) y {len(self.brands)} marca(s) encontradas en "
            f"{self.n_pages} lámina(s)."
        ]
        if self.pages_sampled:
            listed = ", ".join(str(p) for p in self.pages_sampled)
            parts.append(f"Las marcas salen de una muestra de láminas ({listed}), no del "
                         "mazo completo: un tracker repite su set competitivo en cada "
                         "gráfico.")
        if self.discarded_waves:
            parts.append(f"{len(self.discarded_waves)} fecha(s) descartadas por aparecer "
                         f"menos de {MIN_WAVE_OCCURRENCES} veces.")
        if self.brand_pass_error:
            parts.append("La lectura de marcas falló; puedes declararlas a mano.")
        return " ".join(parts)


def _page_texts(content: bytes) -> List[str]:
    """The text layer, page by page. Empty strings for pages that carry none."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def discover_waves(page_texts: Sequence[str]) -> Tuple[List[WaveCandidate], List[Dict[str, Any]]]:
    """Find the deck's waves in its text layer. No model call.

    Returns the candidates that clear the recurrence floor and, separately, the dates
    that did not — a date seen once is far more likely to be a footnote than a wave, but
    the reviewer should still be told it was dropped rather than silently losing it.
    """
    hits: Dict[Tuple[int, int], Counter] = defaultdict(Counter)
    pages: Dict[Tuple[int, int], set] = defaultdict(set)

    for page_no, text in enumerate(page_texts, start=1):
        if not text:
            continue
        for month_raw, year_raw in _MONTH_RE.findall(text):
            key = (_year(year_raw), _MONTHS[_strip_accents(month_raw).lower()])
            hits[key][f"{month_raw} '{year_raw[-2:]}"] += 1
            pages[key].add(page_no)
        for letter, quarter, year_raw in _QUARTER_RE.findall(text):
            # A quarter anchors on its first month: Q1 → January.
            key = (_year(year_raw), (int(quarter) - 1) * 3 + 1)
            hits[key][f"{letter.upper()}{quarter} '{year_raw[-2:]}"] += 1
            pages[key].add(page_no)

    kept: List[WaveCandidate] = []
    dropped: List[Dict[str, Any]] = []
    for (yr, mo), spellings in sorted(hits.items()):
        total = sum(spellings.values())
        label, _ = spellings.most_common(1)[0]
        if total < MIN_WAVE_OCCURRENCES:
            dropped.append({"label": label, "occurrences": total,
                            "pages": sorted(pages[(yr, mo)])[:4]})
            continue
        kept.append(WaveCandidate(
            code=f"{yr:04d}-{mo:02d}",
            label=label,
            period_date=date(yr, mo, 1),
            occurrences=total,
            pages=tuple(sorted(pages[(yr, mo)])),
            spellings=tuple(s for s, _ in spellings.most_common()),
        ))
    return kept, dropped


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _norm_brand(name: str) -> str:
    """Fold a brand name for grouping: no accents, no case, no punctuation."""
    return "".join(c for c in _strip_accents(name).lower() if c.isalnum())


def pick_sample_pages(page_texts: Sequence[str], k: int = BRAND_SAMPLE_PAGES) -> List[int]:
    """Choose the slides most likely to list the full competitive set.

    Ranked by how much text a slide carries, which for a tracker deck tracks how many
    brands it charts: a ranking or a stacked bar names every competitor, while a title
    card or a single-brand callout names one or none. Cover slides and methodology
    appendices sink to the bottom on their own, with no per-deck rules.
    """
    scored = sorted(
        ((len(t or ""), i) for i, t in enumerate(page_texts, start=1)),
        reverse=True,
    )
    return sorted(i for _, i in scored[:k])


def _merge_near_duplicates(
    counts: Dict[str, Counter], pages: Dict[str, set],
) -> Tuple[Dict[str, Counter], Dict[str, set]]:
    """Fold typo variants of one brand into a single candidate.

    A real deck prints "Little Ceasars" on one slide and "Little Caesars" on another.
    Proposing both is worse than proposing neither: adopting two entities splits one
    brand's series in two, and every share and trend computed from it is wrong in a way
    nothing downstream can detect. The tolerance matches ``_LabelResolver.brand`` — same
    budget, same refusal to touch short names — so a name discovered here resolves there.
    """
    from modules.brand_intel.ingest.pdf_pipeline import _edit_distance

    # Most frequent first: the dominant spelling becomes the anchor others fold into.
    order = sorted(counts, key=lambda k: (-sum(counts[k].values()), k))
    anchors: List[str] = []
    out_counts: Dict[str, Counter] = {}
    out_pages: Dict[str, set] = {}

    for key in order:
        budget = 0 if len(key) < 6 else (1 if len(key) < 10 else 2)
        match = None
        if budget:
            near = [a for a in anchors
                    if abs(len(a) - len(key)) <= budget
                    and _edit_distance(key, a, budget) <= budget]
            # Ambiguity is refused rather than guessed, exactly as in the resolver.
            match = near[0] if len(near) == 1 else None
        if match is None:
            anchors.append(key)
            out_counts[key] = Counter(counts[key])
            out_pages[key] = set(pages[key])
        else:
            out_counts[match].update(counts[key])
            out_pages[match] |= pages[key]
    return out_counts, out_pages


def discover_brands(
    content: bytes,
    page_texts: Sequence[str],
    known_waves: Sequence[str] = (),
    sample: int = BRAND_SAMPLE_PAGES,
    renderer: Optional[Callable[..., List[bytes]]] = None,
    extractor: Optional[Callable[..., Any]] = None,
) -> Tuple[List[BrandCandidate], List[int], str]:
    """Read the competitive set off a sample of slides.

    Reuses the ordinary extraction call with an empty brand list, so the model returns
    whatever brand labels it sees printed. The names are grouped by folded key, and each
    group reports every spelling encountered — that is how a reviewer sees a typo for
    what it is instead of adopting two brands.
    """
    from modules.brand_intel.ingest import pdf_vision

    render = renderer or pdf_vision.render_pages
    extract = extractor or pdf_vision.extract_page

    pages = pick_sample_pages(page_texts, sample)
    counts: Dict[str, Counter] = defaultdict(Counter)
    seen_pages: Dict[str, set] = defaultdict(set)
    errors: List[str] = []

    for page_no in pages:
        try:
            images = render(content, first=page_no, last=page_no)
            if not images:
                continue
            read = extract(images[0], page_no, [], list(known_waves))
        except Exception as exc:  # noqa: BLE001 — a bad slide must not lose the pass
            logger.warning("Descubrimiento: página %s ilegible: %s", page_no, exc)
            errors.append(f"p{page_no}: {exc}")
            continue
        for cell in read.cells or []:
            label = (cell.get("brand_label") or "").strip()
            if not label:
                continue          # a category-level figure, not a brand
            key = _norm_brand(label)
            if not key:
                continue
            counts[key][label] += 1
            seen_pages[key].add(page_no)

    merged_counts, merged_pages = _merge_near_duplicates(counts, seen_pages)

    brands = []
    for key, spellings in merged_counts.items():
        total = sum(spellings.values())
        if total < MIN_BRAND_OCCURRENCES and len(merged_pages[key]) < 2:
            continue          # seen once, on one slide: too thin to propose
        name, _ = spellings.most_common(1)[0]
        brands.append(BrandCandidate(
            name=name, occurrences=total,
            pages=tuple(sorted(merged_pages[key])),
            spellings=tuple(s for s, _ in spellings.most_common()),
        ))
    brands.sort(key=lambda b: (-b.occurrences, b.name))

    error = ""
    if errors and not brands:
        error = "; ".join(errors[:3])
    return brands, pages, error


def discover_structure(
    content: bytes,
    sample: int = BRAND_SAMPLE_PAGES,
    renderer: Optional[Callable[..., List[bytes]]] = None,
    extractor: Optional[Callable[..., Any]] = None,
    with_brands: bool = True,
) -> StructureProposal:
    """Both passes over one deck. Proposes; adopts nothing."""
    texts = _page_texts(content)
    waves, dropped = discover_waves(texts)

    proposal = StructureProposal(n_pages=len(texts), waves=waves, discarded_waves=dropped)
    if not with_brands:
        return proposal

    brands, pages, error = discover_brands(
        content, texts, known_waves=[w.label for w in waves],
        sample=sample, renderer=renderer, extractor=extractor,
    )
    proposal.brands = brands
    proposal.pages_sampled = tuple(pages)
    proposal.brand_pass_error = error
    return proposal
