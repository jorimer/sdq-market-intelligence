"""AI-native extraction of by-region education from ONE study PDFs (Eje 6 Fase 2).

Reads the FULL text of the ENHOGAR / Censo report and asks Claude to extract the
literacy rate for each of the 10 development regions — *only* what is stated in
the text, ``null`` otherwise (never estimated or fabricated). Out-of-range values
are dropped at validation. The result upgrades the IDM ``education`` dimension's
``literacy_rate`` from declared rubric to real, by region. (``schooling_years``
is NOT extracted here: ENHOGAR does not publish it by region — it now comes from
the ONE national series; see PR #202.)

The extraction needs a valid ANTHROPIC key (prod): locally it raises, so the sync
is best-effort and the data stays rubric until run where the key is configured.
"""
import json
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.social_dev.models.models import SocialIndicator
from shared.observability.llm_ledger import (  # noqa: E402
    PURPOSE_EXTRACTION, account,
)

logger = logging.getLogger("sdq.social_dev.education_extract")

# Source study: ENHOGAR-2022 reports the literacy rate by the 10 development
# regions (Cuadro 3). It does NOT publish years-of-study by region.
ENHOGAR_URL = "https://www.one.gob.do/media/my1fqfov/informe-general-enhogar-2022.pdf"
ENHOGAR_PERIOD = "2022"
SOURCE = "ONE-ENHOGAR"
_MAX_CHARS = 700_000  # full report (~631k); fits Claude's 200k-token context
_MAX_TOKENS = 1500

# Plausible ranges — anything outside is a misread → dropped (not persisted).
_RANGES = {"literacy_rate": (50.0, 100.0)}


def _prompt(text: str, regions: list) -> str:
    region_lines = "\n".join(f"  - {slug}: {name}" for slug, name in regions)
    return (
        "Eres un demógrafo leyendo el INFORME COMPLETO del ENHOGAR-2022 de la Oficina "
        "Nacional de Estadística (ONE) de la República Dominicana. Tu tarea: extraer, "
        "para cada una de las 10 REGIONES DE DESARROLLO, un indicador:\n"
        "  - literacy_rate: tasa de alfabetización de la población (%) \n\n"
        "REGIONES (usa exactamente estos slugs como claves):\n" + region_lines + "\n\n"
        "REGLAS ESTRICTAS (anti-fabricación):\n"
        "1. Usa SOLO cifras que aparezcan EXPLÍCITAMENTE en el texto para esa región.\n"
        "2. Si una región o el indicador NO aparece, pon null. NO estimes, NO promedies, "
        "NO infieras de otras regiones ni del nacional.\n"
        "3. Devuelve ÚNICAMENTE un objeto JSON válido (sin texto adicional, sin ```), con "
        "la forma exacta: {\"<slug>\": {\"literacy_rate\": número|null}, ...}\n\n"
        "TEXTO COMPLETO DEL INFORME:\n" + text
    )


def extract_education(text: str, regions: list, *, api_key: Optional[str] = None,
                      model: Optional[str] = None) -> Dict[str, Dict[str, Optional[float]]]:  # pragma: no cover - AI call
    """Call Claude over the full report text → ``{slug: {literacy_rate}}``.

    Returns only validated, in-range numbers; everything else is ``None``. Raises
    if no API key is configured (the sync catches it — best-effort)."""
    from shared.config.settings import settings
    from shared.publications.digest import _extract_json

    key = api_key or settings.ANTHROPIC_API_KEY
    if not key:
        raise ValueError("Se requiere ANTHROPIC_API_KEY para la extracción de educación.")
    if not text.strip():
        return {}

    import anthropic

    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model or settings.ANTHROPIC_MODEL, max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": _prompt(text, regions)}],
    )
    account(resp, model=model or settings.ANTHROPIC_MODEL, purpose=PURPOSE_EXTRACTION, module="social_dev", template="educacion")
    raw = resp.content[0].text if resp.content else ""
    data = _extract_json(raw)
    return validate_education(data, {slug for slug, _ in regions})


def validate_education(data: dict, valid_slugs: set) -> Dict[str, Dict[str, Optional[float]]]:
    """Keep only known regions + in-range numbers; everything else → None.

    Pure (no I/O) so it is unit-testable without the model. Drops a value that
    falls outside its plausible range — a misread must not pass as real data."""
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for slug, vals in (data or {}).items():
        if slug not in valid_slugs or not isinstance(vals, dict):
            continue
        row: Dict[str, Optional[float]] = {}
        for var, (lo, hi) in _RANGES.items():
            v = vals.get(var)
            try:
                fv = float(v)
            except (TypeError, ValueError):
                fv = None
            row[var] = fv if (fv is not None and lo <= fv <= hi) else None
        if any(v is not None for v in row.values()):
            out[slug] = row
    return out


def one_education_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Extract by-region education from the ENHOGAR full text and upsert into
    ``sd_indicators``. Best-effort; the AI step needs a valid key (prod)."""
    set_phase = set_phase or (lambda _m: None)
    from shared.data.one_client import region_catalog
    from shared.pdf import extract_pdf_text
    from shared.publications.fetcher import download_pdf

    regions = region_catalog()
    set_phase("descargando ENHOGAR (ONE)")
    try:
        path = download_pdf(ENHOGAR_URL)
        set_phase("leyendo el informe completo")
        text = extract_pdf_text(path, max_chars=_MAX_CHARS)
        set_phase("interpretando educación por región (IA)")
        extracted = extract_education(text, regions)
    except Exception as e:  # noqa: BLE001 — best-effort; the AI step needs a prod key
        logger.warning("ONE education extract falló: %s", e)
        return {"error": str(e), "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo educación de {len(extracted)} regiones")
    synced = 0
    for slug, vals in extracted.items():
        for theme, value in vals.items():
            if value is None:
                continue
            existing = (
                db.query(SocialIndicator)
                .filter_by(entity_key=slug, theme=theme, period=ENHOGAR_PERIOD)
                .first()
            )
            row = existing or SocialIndicator(theme=theme, entity_key=slug, period=ENHOGAR_PERIOD)
            row.value = value
            row.disaggregation = "region"
            row.source = SOURCE
            row.published_at = date(2022, 12, 31)
            row.unit = "%"  # literacy_rate is the only theme extracted here
            if not existing:
                db.add(row)
            synced += 1
    db.commit()
    return {
        "synced": synced,
        "regions_with_data": len(extracted),
        "themes": sorted({t for v in extracted.values() for t, val in v.items() if val is not None}),
        "errors": [],
    }
