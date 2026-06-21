import { useState } from "react";
import { Target, Sparkles, Anchor } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Chip,
  Gauge,
  StateBlock,
  Skeleton,
} from "@/shared/ui/primitives";
import { AiInsightBody } from "@/shared/ui/AiInsightBody";
import { bandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { scoreDeal, type DealScoreResult } from "../api";

/* ──────────────────────────────────────────────────────────────────
 * Deal Scoring — RÚBRICA DECLARADA (cold-start), anclada a los 7 ejes.
 * NO es un modelo entrenado: el score es un índice de cierre/atractivo, no una
 * probabilidad. El XGBoost del spec se activa cuando el dataset cosechado gane el
 * umbral de IC en CV. Badge honesto en cada resultado.
 * ────────────────────────────────────────────────────────────────── */

const DEAL_TYPES = ["capital_raise", "real_estate", "ma_valuation", "debt_portfolio", "venture", "financing", "advisory", "other"];
const SECTORS = ["real_estate", "tourism", "mining_energy", "technology", "fintech", "agriculture", "cpg", "other"];
const STAGES = ["initial", "due_diligence", "term_sheet", "legal"];

const FACTOR_LABELS: Record<string, string> = {
  promoter: "Promotor (track record)", financial: "Calidad financiera",
  market: "Validación de mercado", regulatory: "Preparación regulatoria",
  stage: "Etapa del deal", climate: "Clima (IRC)", momentum: "Momentum",
};

interface FormState {
  deal_name: string; deal_type: string; sector: string; country: string; deal_stage: string;
  deal_size_usd: string; equity_required_pct: string; promoter_track_record: string;
  financial_quality: string; market_validation: string; regulatory_readiness: string;
  days_since_first_contact: string;
}
const EMPTY: FormState = {
  deal_name: "", deal_type: "capital_raise", sector: "fintech", country: "DO", deal_stage: "due_diligence",
  deal_size_usd: "", equity_required_pct: "", promoter_track_record: "", financial_quality: "",
  market_validation: "", regulatory_readiness: "", days_since_first_contact: "",
};

function num(s: string): number | null {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : null;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-muted">{label}</span>
      {hint && <span className="text-[11px] text-faint ml-1">{hint}</span>}
      <div className="mt-1">{children}</div>
    </label>
  );
}

export function DealScoringPage() {
  const [form, setForm] = useState<FormState>(EMPTY);
  const [result, setResult] = useState<DealScoreResult | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");

  const set = (k: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const run = async () => {
    setStatus("loading");
    setResult(null);
    try {
      const r = await scoreDeal({
        deal_name: form.deal_name || "Sin nombre",
        deal_type: form.deal_type, sector: form.sector,
        country: form.country.trim().toUpperCase(), deal_stage: form.deal_stage,
        deal_size_usd: num(form.deal_size_usd), equity_required_pct: num(form.equity_required_pct),
        promoter_track_record: num(form.promoter_track_record), financial_quality: num(form.financial_quality),
        market_validation: num(form.market_validation), regulatory_readiness: num(form.regulatory_readiness),
        days_since_first_contact: num(form.days_since_first_contact), with_ai: true,
      });
      setResult(r);
      setStatus("idle");
    } catch {
      setStatus("error");
    }
  };

  const band = result ? bandFor(result.score) : null;
  const anchors = result ? Object.entries(result.anchor_sources) : [];

  return (
    <div>
      <PageHead
        eyebrow="Herramientas"
        title="Deal Scoring"
        sub="Índice de cierre/atractivo de una oportunidad, anclado a la inteligencia real de los 7 ejes (IRMP del país, IAI del sector, IRC del clima). Rúbrica declarada — no un modelo entrenado todavía."
      />

      <div className="grid lg:grid-cols-2 gap-5">
        {/* Formulario */}
        <Card>
          <CardHead icon={Target} title="Datos del deal" subtitle="Las señales de analista son opcionales: si no las das, se anclan al eje correspondiente." />
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <Field label="Nombre"><input className="field w-full" value={form.deal_name} onChange={set("deal_name")} placeholder="Nombre del deal" /></Field>
            </div>
            <Field label="Tipo"><select className="field w-full" value={form.deal_type} onChange={set("deal_type")}>{DEAL_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}</select></Field>
            <Field label="Sector"><select className="field w-full" value={form.sector} onChange={set("sector")}>{SECTORS.map((t) => <option key={t} value={t}>{t}</option>)}</select></Field>
            <Field label="País" hint="ISO-2"><input className="field w-full" value={form.country} onChange={set("country")} placeholder="DO" /></Field>
            <Field label="Etapa"><select className="field w-full" value={form.deal_stage} onChange={set("deal_stage")}>{STAGES.map((t) => <option key={t} value={t}>{t}</option>)}</select></Field>
            <Field label="Tamaño (USD)"><input className="field w-full" type="number" value={form.deal_size_usd} onChange={set("deal_size_usd")} placeholder="5000000" /></Field>
            <Field label="Equity requerido %"><input className="field w-full" type="number" value={form.equity_required_pct} onChange={set("equity_required_pct")} placeholder="30" /></Field>
            <Field label="Días desde 1er contacto"><input className="field w-full" type="number" value={form.days_since_first_contact} onChange={set("days_since_first_contact")} placeholder="45" /></Field>
            <div className="col-span-2 border-t border-line pt-3 mt-1">
              <p className="text-xs text-muted mb-2">Señales de analista (0–100, opcionales)</p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Track record promotor"><input className="field w-full" type="number" value={form.promoter_track_record} onChange={set("promoter_track_record")} placeholder="—" /></Field>
                <Field label="Calidad financiera"><input className="field w-full" type="number" value={form.financial_quality} onChange={set("financial_quality")} placeholder="—" /></Field>
                <Field label="Validación de mercado" hint="o IAI"><input className="field w-full" type="number" value={form.market_validation} onChange={set("market_validation")} placeholder="ancla a IAI" /></Field>
                <Field label="Prep. regulatoria" hint="o IRMP"><input className="field w-full" type="number" value={form.regulatory_readiness} onChange={set("regulatory_readiness")} placeholder="ancla a IRMP" /></Field>
              </div>
            </div>
          </div>
          <div className="mt-4">
            <button onClick={run} disabled={status === "loading"} className="btn btn-primary">
              <Target className="w-4 h-4" /> {status === "loading" ? "Scoreando…" : "Scorear deal"}
            </button>
          </div>
        </Card>

        {/* Resultado */}
        <div className="space-y-5">
          {status === "error" && <StateBlock kind="error" message="No se pudo scorear el deal." />}
          {status === "loading" && <Skeleton className="h-64" />}
          {status === "idle" && !result && (
            <StateBlock kind="empty" message="Completá los datos del deal y scoreá para ver el índice + drivers + lectura de IA." />
          )}
          {result && band && (
            <>
              <Card className="flex flex-col items-center text-center">
                <Gauge score={result.score} band={band} size={130} />
                <div className="mt-3 flex items-center gap-2">
                  <Chip tone={band.tone}>{band.label}</Chip>
                  <Chip tone="muted">confianza {result.confidence}</Chip>
                </div>
                <div className="mt-3">
                  <Chip tone="warn">Rúbrica declarada · no modelo entrenado</Chip>
                </div>
                <p className="text-[11px] text-faint mt-2 max-w-xs">
                  Índice de cierre/atractivo (no una probabilidad). {result.components_present}/{result.components_total} componentes con dato.
                </p>
              </Card>

              {anchors.length > 0 && (
                <Card>
                  <CardHead icon={Anchor} title="Anclas de eje usadas" subtitle="El score integra la inteligencia real de la plataforma" />
                  <div className="flex flex-wrap gap-2">
                    {anchors.map(([k, v]) => <Chip key={k} tone="accent">{v}</Chip>)}
                  </div>
                </Card>
              )}

              <Card>
                <CardHead icon={Target} title="Drivers del score" subtitle="Cada componente con su valor, origen y aporte" />
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-2 font-medium">Componente</th>
                        <th className="py-2 px-2 font-medium">Origen</th>
                        <th className="py-2 px-2 font-medium text-right">Valor</th>
                        <th className="py-2 px-2 font-medium text-right">Aporte</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.key_factors.map((f) => (
                        <tr key={f.factor} className="border-b border-line/60">
                          <td className="py-2 px-2 text-ink">{FACTOR_LABELS[f.factor] ?? f.factor}</td>
                          <td className="py-2 px-2 text-xs text-muted">{f.source}</td>
                          <td className="py-2 px-2 text-right mono text-ink tabular-nums">{fmtNum(f.value, 1)}</td>
                          <td className="py-2 px-2 text-right mono text-body tabular-nums">{fmtNum(f.contribution, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <Card>
                <CardHead icon={Sparkles} title="Lectura ejecutiva (IA)" subtitle="Análisis del deal anclado en los drivers y el contexto de eje" />
                <AiInsightBody
                  loading={false}
                  ai={result.ai_insight}
                  unavailableHint="La lectura de IA no está disponible (clave de Anthropic no configurada). El score y los drivers de arriba son la rúbrica declarada."
                />
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
