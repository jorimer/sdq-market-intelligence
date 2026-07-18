"""Secciones estándar auto-generadas del reporte (Metodología, Fuentes).

Nuestra ventaja sobre el gold standard típico (ver docs/REPORT_STANDARD.md): las secciones
más respetadas y peor ejecutadas del mercado —Metodología y Fuentes— las derivamos
AUTOMÁTICAMENTE de lo que ya rastreamos por producto (``data_signals`` = cobertura/cadencia/
frescura/fuentes; ``validation_state`` = backtest/score/notas). No se redactan a mano; son
honestas y verificables. Se anexan a las narrativas del producto en el ensamblador, así las
heredan las tres superficies (online, PDF, Word) sin tocar cada sector.

Defensivo: cualquier fallo devuelve ``{}`` → el reporte se sirve igual (nunca rompe).
Anonimización-seguras: hablan de fuentes/cobertura, no de entidades.
"""
from __future__ import annotations

from typing import Dict

from shared.products.tiers import ProductTier

# Claves y títulos canónicos de las secciones estándar (se mergean en el render).
METHODOLOGY_KEY = "std_methodology"
SOURCES_KEY = "std_sources"
GLOSSARY_KEY = "std_glossary"

STANDARD_SECTION_TITLES = {
    METHODOLOGY_KEY: "Metodología y fuentes",
    SOURCES_KEY: "Fuentes y referencias",
    GLOSSARY_KEY: "Glosario",
}

# Tier → qué secciones estándar añade. Pulse queda lean (teaser); Insight suma metodología;
# Deep Dive suma además la lista explícita de fuentes.
_TIERS_WITH_METHODOLOGY = {ProductTier.insight.value, ProductTier.deep_dive.value}
_TIERS_WITH_SOURCES = {ProductTier.deep_dive.value}


def _pct(x) -> str:
    try:
        return f"{float(x) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _methodology_md(sig, val) -> str:
    """Markdown de Metodología desde ``DataHealth`` (sig) + ``ValidationState`` (val)."""
    lines = []
    sources = ", ".join(s for s in (sig.sources or ()) if s) if sig else ""
    lines.append(f"**Fuentes de dato:** {sources or '—'}.")
    cadence = (sig.cadence if sig else None) or "—"
    if sig and sig.freshness_days is not None:
        lines.append(f"**Cadencia:** {cadence}. **Frescura:** el dato más reciente tiene "
                     f"{int(sig.freshness_days)} días.")
    else:
        lines.append(f"**Cadencia:** {cadence}.")
    if sig and sig.coverage is not None:
        lines.append(f"**Cobertura:** {_pct(sig.coverage)} del índice se sostiene en dato real; "
                     "lo no cubierto se declara como rúbrica o brecha — nunca se fabrica.")
    if sig and getattr(sig, "detail", None):
        lines.append(f"**Lectura del dato:** {sig.detail}")
    if val is not None:
        note = f" {val.notes}" if getattr(val, "notes", None) else ""
        score = getattr(val, "score", None)
        score_txt = f" (score de validación {score:.2f})" if isinstance(score, (int, float)) else ""
        lines.append(f"**Validación:**{note}{score_txt}")
    return "\n\n".join(lines)


def _sources_md(sig) -> str:
    """Lista de fuentes (Deep Dive). Enriquecible con URL/licencia/fecha vía lineage (futuro)."""
    sources = [s for s in (sig.sources or ()) if s] if sig else []
    if not sources:
        return "Fuentes no declaradas para este producto."
    out = ["Datos oficiales de acceso público; cada cifra material se ancla a su fuente:"]
    out += [f"- {s}" for s in sources]
    return "\n".join(out)


def standard_sections(product, tier: ProductTier) -> Dict[str, str]:
    """``{key: markdown}`` de las secciones estándar para *product* en *tier*.

    Derivadas de ``product.data_signals()`` + ``product.validation_state()``. Tier-gated:
    Pulse → ninguna; Insight → metodología; Deep Dive → metodología + fuentes. Defensivo."""
    tv = tier.value if isinstance(tier, ProductTier) else str(tier)
    if tv not in _TIERS_WITH_METHODOLOGY:
        return {}
    try:
        sig = product.data_signals()
    except Exception:  # noqa: BLE001 — la metodología nunca debe romper el reporte
        sig = None
    try:
        val = product.validation_state()
    except Exception:  # noqa: BLE001
        val = None
    out: Dict[str, str] = {METHODOLOGY_KEY: _methodology_md(sig, val)}
    if tv in _TIERS_WITH_SOURCES:
        out[SOURCES_KEY] = _sources_md(sig)
    return out


def glossary_section(narrative_text: str, tier: ProductTier) -> Dict[str, str]:
    """``{std_glossary: markdown}`` con las siglas/términos técnicos que aparecen en
    ``narrative_text`` (el texto YA REDACTADO del producto, antes de anexar metodología/
    fuentes). Tier-gated igual que metodología (Pulse queda lean, sin glosario). Vacío
    si el texto no usa ningún término del diccionario."""
    tv = tier.value if isinstance(tier, ProductTier) else str(tier)
    if tv not in _TIERS_WITH_METHODOLOGY:
        return {}
    from shared.products.glossary import glossary_markdown
    md = glossary_markdown(narrative_text)
    return {GLOSSARY_KEY: md} if md else {}
