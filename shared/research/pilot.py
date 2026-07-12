"""Instrumentación del piloto manual (Fase 2) — captura de cobertura por pregunta.

docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §5 Fase 2: correr 3-5 preguntas reales de compradores
y medir, por pregunta, la cobertura real (%real/rúbrica/brecha) y si el gate de honestidad
sobrevive. Esto es instrumentación de BUILD, no validación de mercado.

Las métricas de cobertura las calcula el motor (deterministas). Las columnas que dependen
del proceso —horas ahorradas vs. el DD actual y costo de IA por pregunta— NO se inventan:
quedan como campos que el analista/dueño completa al correr el piloto (§8.2). El costo de
IA es 0 en el núcleo determinista actual; se poblará cuando se enchufe el Cerebro.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.gate import DEFAULT_GAP_THRESHOLD
from shared.research.models import GATE_REPORT
from shared.research.orchestrator import answer_question


@dataclass
class PilotRow:
    """Métricas de una pregunta del piloto (lo automático) + campos manuales (a llenar)."""

    question: str
    gate: str
    coverage_real: float
    anchored_fraction: float
    n_sub: int
    state_counts: Dict[str, int]
    n_sources: int
    # Campos que el analista completa al correr el piloto (no se fabrican).
    hours_manual_dd: Optional[float] = None   # horas del proceso DD actual para esta pregunta
    hours_with_engine: Optional[float] = None  # horas con el motor asistiendo
    ai_cost_usd: Optional[float] = None        # costo de IA por pregunta (0 en núcleo determinista)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "question": self.question, "gate": self.gate,
            "coverage_real": self.coverage_real,
            "anchored_fraction": self.anchored_fraction,
            "n_sub": self.n_sub, "state_counts": self.state_counts,
            "n_sources": self.n_sources,
            "hours_manual_dd": self.hours_manual_dd,
            "hours_with_engine": self.hours_with_engine,
            "ai_cost_usd": self.ai_cost_usd,
        }
        return d


@dataclass
class PilotReport:
    """Resultado del piloto: filas por pregunta + agregados + markdown exportable."""

    rows: List[PilotRow] = field(default_factory=list)
    gap_threshold: float = DEFAULT_GAP_THRESHOLD

    @property
    def summary(self) -> Dict[str, Any]:
        n = len(self.rows)
        if not n:
            return {"n": 0}
        return {
            "n": n,
            "coverage_real_mean": round(sum(r.coverage_real for r in self.rows) / n, 4),
            "anchored_mean": round(sum(r.anchored_fraction for r in self.rows) / n, 4),
            "report_rate": round(sum(1 for r in self.rows if r.gate == GATE_REPORT) / n, 4),
            "scoping_rate": round(sum(1 for r in self.rows if r.gate != GATE_REPORT) / n, 4),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {"gap_threshold": self.gap_threshold, "summary": self.summary,
                "rows": [r.to_dict() for r in self.rows]}

    def to_markdown(self) -> str:
        s = self.summary
        out = ["# Piloto manual — Motor de Research Custom (Fase 2)\n"]
        if not s.get("n"):
            out.append("_Sin preguntas._")
            return "\n".join(out)
        out.append(f"Preguntas: **{s['n']}** · cobertura real media: "
                   f"**{s['coverage_real_mean']:.0%}** · con ancla: "
                   f"**{s['anchored_mean']:.0%}** · informe completo: "
                   f"**{s['report_rate']:.0%}** · scoping: **{s['scoping_rate']:.0%}**")
        out.append(f"\nUmbral de gate: {self.gap_threshold:.0%} de brecha.\n")
        out.append("| # | Pregunta | Gate | % real | % ancla | sub | real/rúb/brecha | "
                   "fuentes | h DD actual | h con motor | costo IA US$ |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(self.rows, 1):
            c = r.state_counts
            hm = "—" if r.hours_manual_dd is None else f"{r.hours_manual_dd:g}"
            he = "—" if r.hours_with_engine is None else f"{r.hours_with_engine:g}"
            ac = "—" if r.ai_cost_usd is None else f"{r.ai_cost_usd:g}"
            out.append(f"| {i} | {r.question[:60]} | {r.gate} | {r.coverage_real:.0%} | "
                       f"{r.anchored_fraction:.0%} | {r.n_sub} | "
                       f"{c.get(REAL,0)}/{c.get(RUBRIC,0)}/{c.get(GAP,0)} | {r.n_sources} | "
                       f"{hm} | {he} | {ac} |")
        out.append("\n_Las columnas de horas y costo IA las completa el analista al correr "
                   "el piloto (no se fabrican). El ahorro de horas y el tier nuevo se deciden "
                   "en Fases 5-6 con estos números — no antes (§8.4)._")
        return "\n".join(out)


async def run_pilot(questions: List[str], db: Optional[Session] = None, *,
                    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
                    per_q_k: int = 4) -> PilotReport:
    """Corre el motor sobre las *questions* del piloto y captura las métricas de cobertura."""
    rows: List[PilotRow] = []
    for q in questions:
        ans = await answer_question(q, db=db, gap_threshold=gap_threshold, per_q_k=per_q_k)
        rows.append(PilotRow(
            question=q, gate=ans.gate, coverage_real=ans.coverage_real,
            anchored_fraction=ans.anchored_fraction, n_sub=len(ans.sub_questions),
            state_counts=ans.state_counts, n_sources=len(ans.sources),
            ai_cost_usd=0.0,  # núcleo determinista: sin costo de IA todavía
        ))
    return PilotReport(rows=rows, gap_threshold=gap_threshold)
