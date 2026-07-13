"""Reporte de SÍNTESIS CROSS-DOMINIO — el entregable del motor de research (orquestador v3).

Por qué: a US$7–10k por encargo, el entregable debe superar un Deep Dive, no ser un
resumen ni la ficha de un solo sector. ``build_synthesis_report``:
1. Cosecha el dato real de TODOS los motores que la pregunta convoca (entidades + dominios
   de contexto: macro, monetario, …) vía ``pull_entity``/``pull_axis``.
2. Entrega un DICTAMEN INTEGRADO —los mecanismos de transmisión entre dominios, redactado
   por el Cerebro circunscrito a esas cifras— más la evidencia real por motor.
3. Arma gráficos/tablas de marca desde el snapshot del motor primario con entidad.
El resultado = síntesis entre dominios, lo que un Deep Dive individual no puede dar.

Anti-Frankenstein: usa el contrato del registro (vía ``data_pull``); no importa el módulo
del sector. Los títulos de sección son data local (no se importa el módulo solo por rótulos)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.research.data_pull import EnginePull
from shared.research.models import DeclaredGap

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

SECTION_TITLES["metodologia"] = "Metodología y fuentes"
SECTION_TITLES["limitaciones"] = "Limitaciones"
SECTION_TITLES["dictamen"] = "Dictamen integrado"
SECTION_TITLES["evidencia"] = "Evidencia por motor"

_SYNTH_METHODOLOGY = (
    "Este informe INTEGRA el resultado ya computado de varios motores del sistema SDQ "
    "—{engines}— alrededor de la pregunta. No es la ficha de un sector: es la síntesis de "
    "los mecanismos de transmisión entre dominios, que ningún producto individual entrega. "
    "El Cerebro redactó circunscrito a esas cifras (verificador numérico activo: no se cita "
    "ningún número que no trace al dato de un motor). Sin web abierta ni fuentes externas en "
    "vivo. Lo que ningún motor computa se declara como límite, no se rellena.")

_LIMITATIONS_TEXT = (
    "La calificación es una medida de fortaleza financiera intrínseca (standalone) sobre "
    "información pública supervisada a la fecha de corte; no es un rating de crédito ni una "
    "recomendación de inversión. El análisis se circunscribe a los indicadores que el motor "
    "computa; lo prospectivo (proyecciones/escenarios a futuro) no se estima.")

# El rótulo de 'eficiencia' referencia SECTION_TITLES (misma fuente, en este archivo) para
# que el nombre del gráfico y el del encabezado de sección no puedan desalinearse. NO se
# importa el mapa de banking_score: shared/ no importa módulos de sector (anti-Frankenstein).
_SUB_LABELS = {
    "solidez": "Solidez", "calidad": "Calidad de activos",
    "eficiencia": SECTION_TITLES["eficiencia_rentabilidad"],
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
    """Tablas de marca desde el snapshot real: concentración del sistema y —si el motor los
    sirve— PARES NOMBRADOS (posición de la entidad vs competidores concretos con su score).
    Es la comparación que un percentil anónimo no da."""
    payload = payload or {}
    peer = payload.get("peer_block") or {}
    tables: List[Tuple[str, List[List[str]]]] = []
    if peer.get("cr5") is not None:
        tables.append((f"Concentración del sistema · {peer.get('metric_label', 'activos')}",
                       [["Métrica", "Valor"],
                        ["CR5 (5 mayores)", _fmt(peer.get("cr5"))],
                        ["CR10 (10 mayores)", _fmt(peer.get("cr10"))],
                        ["HHI", _fmt(peer.get("hhi"))]]))
    # Forma banca: peer_block.named_peers (líderes del sistema + del mismo tipo + la entidad).
    np_meta = peer.get("named_peers") or {}
    np_rows = np_meta.get("rows") or []
    if np_rows:
        body: List[List[str]] = [["Pos.", "Entidad", "Tipo", "Score", "Rating"]]
        for r in np_rows:
            name = str(r.get("name", "")) + (" ◀" if r.get("is_subject") else "")
            body.append([str(r.get("rank", "")), name, str(r.get("type", "")),
                         _fmt(r.get("score")), str(r.get("tier", ""))])
        n = np_meta.get("n_system")
        tables.append((f"Posición vs pares nombrados · {n} entidades calificadas" if n
                       else "Posición vs pares nombrados", body))
    # Forma pension/insurance: payload.peers = roster completo con score; el sujeto en 'rating'.
    peers = payload.get("peers")
    rating = payload.get("rating") or {}
    if isinstance(peers, list) and rating:
        ranked = sorted((p for p in peers
                         if isinstance(p, dict) and isinstance(p.get("overall_score"), (int, float))),
                        key=lambda p: p["overall_score"], reverse=True)
        if len(ranked) >= 2:
            subj = rating.get("slug") or rating.get("name")
            body = [["Pos.", "Entidad", "Score", "Banda"]]
            for i, p in enumerate(ranked, start=1):
                mark = " ◀" if subj and subj in (p.get("slug"), p.get("name")) else ""
                body.append([str(i), str(p.get("name") or p.get("slug") or "") + mark,
                             _fmt(p["overall_score"]), str(p.get("band") or "")])
            tables.append(("Ranking nombrado del sistema", body))
    return tables


def _headline(payload: Dict[str, Any]) -> str:
    sr = (payload or {}).get("scoring_result") or {}
    tier, score = sr.get("rating_tier"), sr.get("overall_score")
    if tier and isinstance(score, (int, float)):
        return f"{tier} · {score:.1f}/100"
    return ""


async def build_synthesis_report(question: str, db: Optional[Session], targets,
                                 forward_gaps: List[DeclaredGap],
                                 pulls: Optional[List[EnginePull]] = None) -> Optional[DeepReport]:
    """Research TEMA-PRIMERO: cosecha el dato real de TODOS los motores que la pregunta
    convoca (entidades + dominios de contexto: macro, monetario, …) y entrega un DICTAMEN
    INTEGRADO —los mecanismos de transmisión entre dominios— en vez de la ficha de un sector.
    Es lo que un Deep Dive estructuralmente no puede dar. ``None`` si no hay dato/Cerebro.

    ``pulls``: cosecha ya hecha por el orquestador (evita re-cosechar cada entidad — un
    snapshot de banca son varios queries). Si es ``None``, cosecha aquí (compatibilidad)."""
    from shared.research.data_pull import pull_axis, pull_entity
    from shared.research.narrate import narrate_synthesis

    if pulls is None:
        if db is None:
            return None
        pulls = []
        for ent in targets.entities:
            pulls.append(pull_entity(db, ent))
        for ax in list(targets.axes) + list(targets.context):
            pulls.append(pull_axis(db, ax))
    live = [p for p in pulls if p.ok and p.payload]
    if not live:
        return None

    thesis = await narrate_synthesis(question, live,
                                     forward_gaps=[g.note for g in forward_gaps],
                                     reasons=getattr(targets, "reasons", None))
    if not thesis:
        return None  # sin Cerebro → el orquestador cae al ensamblado liviano

    sections: Dict[str, str] = {"dictamen": f"**Pregunta:** {question}\n\n{thesis}"}
    ordered = ["dictamen"]

    # Evidencia por motor (determinista, cifras reales de cada dominio cosechado).
    ev: List[str] = []
    for p in live:
        ev.append(f"### {p.entity_label} · {p.sector_key}")
        # 6 líneas: banca emite hasta 6 (head, sub-componentes, concentración, posición
        # nombrada, pares, alerta) — con [:4] la línea de pares nombrados se cortaba.
        ev.extend(f"- {e.text}" for e in p.evidence[:6])
    sections["evidencia"] = "\n".join(ev)
    ordered.append("evidencia")

    engines = ", ".join(dict.fromkeys(p.source for p in live))
    sections["metodologia"] = _SYNTH_METHODOLOGY.format(engines=engines)
    ordered.append("metodologia")
    lim = _LIMITATIONS_TEXT
    if forward_gaps:
        lim += "\n\n**Fuera de alcance (declarado):**\n" + "\n".join(
            f"- {g.note}" for g in forward_gaps)
    sections["limitaciones"] = lim
    ordered.append("limitaciones")

    # Gráficos/tablas del motor primario con entidad (si lo hay).
    ent_pull = next((p for p in live if any(p.sector_key == e.sector_key
                     for e in targets.entities)), live[0])
    titles = {k: SECTION_TITLES.get(k, k.replace("_", " ").title()) for k in ordered}
    sources = list(dict.fromkeys(p.source for p in live))
    return DeepReport(
        entity_label=ent_pull.entity_label, sector_key=ent_pull.sector_key,
        period=ent_pull.period, ordered_keys=ordered, sections=sections, titles=titles,
        charts=_charts_from_payload(ent_pull.payload),
        tables=_tables_from_payload(ent_pull.payload),
        headline=_headline(ent_pull.payload), sources=sources,
    )
