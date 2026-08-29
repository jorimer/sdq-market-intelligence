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

from datetime import timedelta
from typing import Dict, Optional

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


def _periodo_posterior(texto: str, corte: str) -> bool:
    """¿*texto* menciona una fecha ISO POSTERIOR a *corte*? Conservador: sin fecha → False.

    Sirve para no imprimir, en un informe fechado al corte, una lectura del dato que habla
    de un período que todavía no había ocurrido.
    """
    import re as _re

    if not corte:
        return False
    c = str(corte)[:10]
    for m in _re.finditer(r"\d{4}-\d{2}(?:-\d{2})?", str(texto or "")):
        f = m.group(0)
        if len(f) == 7:            # 'YYYY-MM' → compara al mismo grano
            if f > c[:7]:
                return True
        elif f > c:
            return True
    return False


def _fecha_del_corte(as_of: str):
    """El corte como `date`, o ``None``. Acepta ``YYYY``, ``YYYY-MM`` y ``YYYY-MM-DD``.

    Un producto anual pide su período como AÑO (`2025`); uno trimestral, como fecha. Los dos
    tienen que poder anclar su frescura.
    """
    from datetime import date as _date

    t = str(as_of or "").strip()
    try:
        if len(t) == 4:
            return _date(int(t), 12, 31)
        if len(t) == 7:
            a, m = int(t[:4]), int(t[5:7])
            return _date(a + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
        return _date.fromisoformat(t[:10])
    except (ValueError, TypeError):
        return None


_CADENCIA_ES = {"monthly": "mensual", "quarterly": "trimestral", "annual": "anual",
                "daily": "diaria", "weekly": "semanal"}


def _frescura_md(sig, as_of: Optional[str], hoy=None) -> str:
    """La frescura ANCLADA AL CORTE del informe, no al día en que se genera.

    **El defecto.** Se imprimía `freshness_days` tal cual, y ese número se computa contra
    `date.today()`. Dos generaciones del MISMO informe daban 240 y 150 días sin que el dato
    hubiera cambiado: la cifra envejecía sola dentro de un documento fechado. En material que
    se manda a un tercero, eso es un número que se vuelve falso solo con esperar.

    **Qué dice ahora.** La fecha real del dato más reciente —`hoy − freshness_days`, que SÍ es
    estable— comparada contra el corte:

    * si no hay dato posterior al corte, el informe declara que su dato ES el del corte;
    * si lo hay, se DICE, con cuánto: que exista un corte más nuevo que el pedido es
      información legítima para quien lee un informe fechado, y callarlo dejaría creer que
      este es el último disponible.

    Sin corte —una vista no fechada— se conserva la lectura de plataforma, que ahí es la
    correcta: la pregunta es «¿qué tan al día está el eje HOY?».

    *hoy* existe para poder PROBAR la invariante: que el mismo dato y el mismo corte producen
    el mismo texto se genere cuando se genere. Sin la costura, un test tendría que mover el
    reloj del proceso, y el defecto que este arreglo cierra es precisamente uno de reloj.
    """
    from datetime import date as _date

    hoy = hoy or _date.today()
    # `cadence` es una CLAVE de máquina —la usa `_CADENCE_THRESHOLDS` para elegir umbrales—,
    # así que no se traduce el valor: se traduce al escribirlo. Sin esto, un documento en
    # español salía diciendo «Cadencia: quarterly».
    cadence = _CADENCIA_ES.get((sig.cadence if sig else None) or "", None) or "—"
    if not sig or sig.freshness_days is None:
        return f"**Cadencia:** {cadence}."

    d = int(sig.freshness_days)
    corte = _fecha_del_corte(as_of) if as_of else None
    if corte is None:
        # Vista sin corte: la frescura describe el estado de la plataforma hoy.
        return (f"**Cadencia:** {cadence}. **Frescura:** el dato más reciente tiene "
                + ("menos de un día." if d == 0 else
                   "un día." if d == 1 else f"{d} días."))

    fecha_del_dato = hoy - timedelta(days=d)
    posterior = (fecha_del_dato - corte).days
    if posterior <= 0:
        return (f"**Cadencia:** {cadence}. **Frescura:** el dato más reciente de este informe "
                "es el del corte; no hay observación posterior en el panel.")
    return (f"**Cadencia:** {cadence}. **Frescura:** el dato de este informe es el del corte. "
            f"El panel ya registra observaciones hasta {fecha_del_dato.isoformat()} "
            f"({posterior} días después), que este informe no incorpora: el corte manda.")


def _methodology_md(sig, val, as_of: Optional[str] = None) -> str:
    """Markdown de Metodología desde ``DataHealth`` (sig) + ``ValidationState`` (val).

    ``as_of`` es el CORTE del informe. Con él, la metodología deja de hablar del estado
    actual de la plataforma y habla del informe: la frescura se ancla al corte y se omite
    una "lectura del dato" que mencione un período posterior. Un informe "al 31-dic-2025"
    que declara cobertura a marzo-2026 es la misma inconsistencia que la trayectoria que ya
    se recortó, solo que en la sección de metodología.
    """
    lines = []
    if as_of:
        # La frase anterior afirmaba que TODAS las cifras y capas de contexto correspondían al
        # corte. No es cierto y se publicó así: un Deep Dive de seguros con corte 2024 traía la
        # capa de mercado en 2025 y afiliación a marzo-2026. El corte manda sobre la entidad
        # evaluada; las capas agregadas se publican con SU período, que es información, no ruido.
        lines.append(f"**Corte del informe:** {as_of}. Las cifras y posiciones de la entidad "
                     "evaluada corresponden a esa fecha. Las capas de contexto agregado —mercado, "
                     "mezcla, cobertura sectorial— llevan el período de su propia fuente, "
                     "indicado donde se presentan.")
    sources = ", ".join(s for s in (sig.sources or ()) if s) if sig else ""
    lines.append(f"**Fuentes de dato:** {sources or '—'}.")
    lines.append(_frescura_md(sig, as_of))
    if sig and sig.coverage is not None:
        lines.append(f"**Cobertura:** {_pct(sig.coverage)} del índice se sostiene en dato real; "
                     "lo no cubierto se declara como rúbrica o brecha — nunca se fabrica.")
    detail = getattr(sig, "detail", None) if sig else None
    if detail and not _periodo_posterior(detail, as_of or ""):
        lines.append(f"**Lectura del dato:** {detail}")
    if val is not None:
        note = f" {val.notes}" if getattr(val, "notes", None) else ""
        score = getattr(val, "score", None)
        score_txt = f" (score de validación {score:.2f})" if isinstance(score, (int, float)) else ""
        lines.append(f"**Validación:**{note}{score_txt}")
    return "\n\n".join(lines)


def _provenance_md(product) -> str:
    """Párrafo de procedencia por-variable desde ``variable_signals`` del producto.

    Se construye un ``AxisRegistry`` efímero solo con lo que el producto declara — sin DB
    y sin recorrer el catálogo completo (esto corre dentro del render de un reporte).
    Producto sin ``variable_signals`` → cadena vacía: silencio honesto, nunca inventar."""
    fn = getattr(product, "variable_signals", None)
    if not callable(fn):
        return ""
    try:
        from shared.registry.provenance import provenance_paragraph
        from shared.registry.signals import AxisRegistry

        raw = fn()
        signals = tuple(raw.get("signals", ()) if isinstance(raw, dict) else (raw or ()))
        if not signals:
            return ""
        axis = AxisRegistry(
            sector_key=getattr(product, "sector_key", ""), display_name="",
            source="", implemented=True, signals=signals,
        )
        return provenance_paragraph(axis)
    except Exception:  # noqa: BLE001 — sección informativa; jamás rompe el reporte
        return ""


def _sources_md(sig) -> str:
    """Lista de fuentes (Deep Dive). Enriquecible con URL/licencia/fecha vía lineage (futuro)."""
    sources = [s for s in (sig.sources or ()) if s] if sig else []
    if not sources:
        return "Fuentes no declaradas para este producto."
    out = ["Datos oficiales de acceso público; cada cifra material se ancla a su fuente:"]
    out += [f"- {s}" for s in sources]
    return "\n".join(out)


def standard_sections(product, tier: ProductTier,
                      as_of: Optional[str] = None) -> Dict[str, str]:
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
    methodology = _methodology_md(sig, val, as_of)
    # Procedencia POR VARIABLE, generada del registro en vivo — nunca prosa escrita a
    # mano (lección Hallazgo 7: la prosa que afirma procedencia envejece con cada
    # conector; la generada no puede divergir del estado real porque ES el estado real).
    provenance = _provenance_md(product)
    if provenance:
        methodology += f"\n\n**Procedencia por variable:** {provenance}"
    out: Dict[str, str] = {METHODOLOGY_KEY: methodology}
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
