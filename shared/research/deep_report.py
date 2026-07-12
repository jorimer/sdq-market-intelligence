"""Reporte profundo — el motor de research reutiliza TODA la narrativa Deep Dive del
producto y le agrega la capa a-medida (orquestador v3).

Por qué: a US$7–10k por encargo, el entregable debe superar un Deep Dive, no ser un
resumen. En vez de re-escribir, este módulo:
1. Pide el CONTENIDO Deep Dive completo de la entidad vía ``assemble_product_content``
   (todas las secciones ya narradas por el Cerebro del producto + su procedencia).
2. Antepone la RESPUESTA A LA PREGUNTA (la capa de research: el ángulo que el comprador
   pidió, p.ej. liquidez) y aumenta Limitaciones con la brecha prospectiva.
3. Arma gráficos/tablas desde el snapshot real.
El resultado = Deep Dive íntegro + capa de research = más profundo que un Deep Dive.

Anti-Frankenstein: usa el contrato del registro (``get_product`` + ``assemble_product_content``);
no importa el módulo del sector. Los títulos de sección son data local (no se importa el
módulo solo por rótulos)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.products.registry import CATALOG_BY_KEY, get_product
from shared.products.tiers import ProductTier
from shared.research.data_pull import EnginePull
from shared.research.models import DeclaredGap
from shared.research.narrate import narrate_answer
from shared.research.resolve import ResolvedEntity

logger = logging.getLogger("sdq.research.deep_report")

# Rótulos de sección (data local — copiada, no importada del módulo). Cubre las claves
# Deep Dive de banca + las estándar + la capa de research. Fallback: key.title().
SECTION_TITLES: Dict[str, str] = {
    "respuesta_a_su_pregunta": "Respuesta a su pregunta",
    "executive_summary": "Resumen ejecutivo",
    "solidez_financiera": "Solidez financiera",
    "calidad_activos": "Calidad de activos",
    "eficiencia_rentabilidad": "Eficiencia y rentabilidad",
    "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
    "comparative": "Posición vs pares",
    "entorno_operativo": "Entorno operativo",
    "soporte_soberano": "Soporte y techo soberano",
    "risk_assessment": "Evaluación de riesgo",
    "early_warning": "Alerta temprana",
    "recommendation": "Recomendaciones",
    "limitations": "Limitaciones",
    "std_methodology": "Metodología y fuentes",
    "std_sources": "Fuentes y referencias",
}

# Secciones deterministas del producto (no pasan por el Cerebro) → siempre reales.
_ALWAYS_KEEP = {"early_warning", "limitations", "std_methodology", "std_sources"}


def _looks_real(text: str) -> bool:
    """Heurística anti-slop: una sección de análisis real CITA cifras. Los fallbacks del
    Cerebro (genérico o por-sección) son prosa genérica sin números de la entidad. Sin
    ``model_used`` en el dict de narrativas, esto distingue análisis real de relleno."""
    import re
    return len(re.findall(r"\d", text or "")) >= 4

_SUB_LABELS = {
    "solidez": "Solidez", "calidad": "Calidad de activos", "eficiencia": "Eficiencia",
    "liquidez": "Liquidez", "diversificacion": "Diversificación",
}


@dataclass
class DeepReport:
    entity_label: str
    sector_key: str
    period: Optional[str]
    ordered_keys: List[str] = field(default_factory=list)
    sections: Dict[str, str] = field(default_factory=dict)
    titles: Dict[str, str] = field(default_factory=dict)
    charts: List[dict] = field(default_factory=list)
    tables: List[Tuple[str, List[List[str]]]] = field(default_factory=list)
    headline: str = ""
    sources: List[str] = field(default_factory=list)


def _fmt(v: Any) -> str:
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def _charts_from_payload(payload: Dict[str, Any]) -> List[dict]:
    """Gráficos de marca desde el scoring_result real (barras de sub-componentes + línea de
    trayectoria si viene). Robusto: omite lo que no reconoce, no fabrica."""
    sr = (payload or {}).get("scoring_result") or {}
    charts: List[dict] = []
    sub = sr.get("sub_components") or {}
    if sub:
        items = [(_SUB_LABELS.get(k, k.title()), round(float(v), 1))
                 for k, v in sub.items() if isinstance(v, (int, float))]
        if items:
            charts.append({"title": "Sub-componentes del rating (0–100)", "items": items})
    tr = (sr.get("trayectorias") or {}).get("overall")
    series = _as_series(tr)
    if len(series) >= 2:
        charts.append({"title": "Trayectoria del score", "kind": "line", "items": series})
    return charts


def _as_series(tr: Any) -> List[Tuple[str, float]]:
    """Normaliza una trayectoria a ``[(período, valor)]`` desde varias formas posibles."""
    out: List[Tuple[str, float]] = []
    if isinstance(tr, dict):
        for k, v in tr.items():
            if isinstance(v, (int, float)):
                out.append((str(k), round(float(v), 1)))
    elif isinstance(tr, (list, tuple)):
        for it in tr:
            if isinstance(it, dict):
                p = it.get("period") or it.get("periodo") or it.get("label")
                val = it.get("score") if it.get("score") is not None else it.get("value")
                if p is not None and isinstance(val, (int, float)):
                    out.append((str(p), round(float(val), 1)))
            elif isinstance(it, (list, tuple)) and len(it) == 2 and isinstance(it[1], (int, float)):
                out.append((str(it[0]), round(float(it[1]), 1)))
    return out


def _tables_from_payload(payload: Dict[str, Any]) -> List[Tuple[str, List[List[str]]]]:
    """Tablas de marca desde el snapshot real (concentración del sistema si viene)."""
    peer = (payload or {}).get("peer_block") or {}
    tables: List[Tuple[str, List[List[str]]]] = []
    if peer.get("cr5") is not None:
        tables.append((f"Concentración del sistema · {peer.get('metric_label', 'activos')}",
                       [["Métrica", "Valor"],
                        ["CR5 (5 mayores)", _fmt(peer.get("cr5"))],
                        ["CR10 (10 mayores)", _fmt(peer.get("cr10"))],
                        ["HHI", _fmt(peer.get("hhi"))]]))
    return tables


def _headline(payload: Dict[str, Any]) -> str:
    sr = (payload or {}).get("scoring_result") or {}
    tier, score = sr.get("rating_tier"), sr.get("overall_score")
    if tier and isinstance(score, (int, float)):
        return f"{tier} · {score:.1f}/100"
    return ""


async def build_deep_report(question: str, db: Optional[Session],
                            entities: List[ResolvedEntity], pulls: List[EnginePull],
                            forward_gaps: List[DeclaredGap]) -> Optional[DeepReport]:
    """Reporte profundo de la PRIMERA entidad con Deep Dive disponible. ``None`` si ninguna
    entidad produce contenido profundo (→ el orquestador usa el ensamblado liviano)."""
    if db is None or not entities:
        return None
    from shared.products.assembler import assemble_product_content

    for ent in entities:
        product = get_product(ent.sector_key, db)
        if product is None:
            continue
        try:
            content = await assemble_product_content(
                product, ProductTier.deep_dive, period="", scope=ent.scope_value, lang="es")
        except Exception as e:  # noqa: BLE001 — entidad sin Deep Dive → siguiente
            logger.info("Deep Dive de %s (%s) no disponible: %s", ent.sector_key, ent.label, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            continue

        entry = CATALOG_BY_KEY.get(ent.sector_key)
        source = entry.source if entry else ent.sector_key

        # Capa de research: la respuesta directa a la pregunta (con su ángulo), arriba de todo.
        live = [p for p in pulls if p.sector_key == ent.sector_key and p.ok]
        lead = await narrate_answer(question, live,
                                    forward_gaps=[g.note for g in forward_gaps]) if live else None

        sections: Dict[str, str] = {}
        ordered: List[str] = []
        if lead:
            sections["respuesta_a_su_pregunta"] = f"**Pregunta:** {question}\n\n{lead}"
            ordered.append("respuesta_a_su_pregunta")

        # Regla anti-slop (CLAUDE.md frontend §6): una sección del Deep Dive reutilizada solo
        # entra si trae CONTENIDO REAL. Las que volvieron como fallback estático (Cerebro sin
        # cupo/caché fría) se OMITEN — nunca se muestra relleno genérico. Con la caché tibia
        # del producto (lo normal), las secciones reales del Deep Dive sí pasan el filtro.
        order = list(content.section_order) or list(content.narratives.keys())
        for k in order:
            text = content.narratives.get(k)
            if not text or k in sections:
                continue
            if k in _ALWAYS_KEEP or _looks_real(text):
                sections[k] = text
                ordered.append(k)
            # si no, es fallback del Cerebro (caché fría / sin cupo) → se omite (anti-slop)

        # Aumenta Limitaciones con la brecha prospectiva declarada (§4), sin fabricar.
        if forward_gaps:
            extra = "\n\n**Fuera de alcance (declarado):**\n" + "\n".join(
                f"- {g.note}" for g in forward_gaps)
            if "limitations" in sections:
                sections["limitations"] += extra
            else:
                sections["limitations"] = extra.strip()
                ordered.append("limitations")

        titles = {k: SECTION_TITLES.get(k, k.replace("_", " ").title()) for k in ordered}
        return DeepReport(
            entity_label=ent.label, sector_key=ent.sector_key, period=content.snapshot.period,
            ordered_keys=ordered, sections=sections, titles=titles,
            charts=_charts_from_payload(content.snapshot.payload),
            tables=_tables_from_payload(content.snapshot.payload),
            headline=_headline(content.snapshot.payload), sources=[source],
        )
    return None
