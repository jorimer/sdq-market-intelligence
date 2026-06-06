import { useEffect, useState } from "react";
import { Calculator, Radar as RadarIcon, ListChecks } from "lucide-react";
import { BankSelector } from "../components/BankSelector";
import { RadarChart } from "../components/RadarChart";
import { ScoreGauge } from "../components/ScoreGauge";
import { RatingBadge } from "../components/RatingBadge";
import { IndicatorTable } from "../components/IndicatorTable";
import { PageHead, Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import {
  listPeriods,
  runScoring,
  ScoringResult,
  SUB_KEYS,
  SUB_LABELS,
} from "../api";

export function ScoringPage() {
  const [bankId, setBankId] = useState("");
  const [bankName, setBankName] = useState("");
  const [periods, setPeriods] = useState<string[]>([]);
  const [period, setPeriod] = useState("");
  const [result, setResult] = useState<ScoringResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    listPeriods().then((p) => {
      setPeriods(p);
      if (p.length) setPeriod(p[0]);
    });
  }, []);

  const run = async () => {
    if (!bankId || !period) return;
    setLoading(true);
    setError(false);
    try {
      setResult(await runScoring(bankId, period));
    } catch {
      setError(true);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow="SIB · scoring"
        title="Calcular rating"
        sub="Ejecuta el modelo determinista (19 indicadores · 5 sub-componentes) para una entidad y período."
      />

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-64">
            <label className="block text-xs font-medium text-muted mb-1">Entidad</label>
            <BankSelector
              value={bankId}
              onChange={(id, name) => {
                setBankId(id);
                setBankName(name);
              }}
            />
          </div>
          <div className="w-40">
            <label className="block text-xs font-medium text-muted mb-1">Período</label>
            <select value={period} onChange={(e) => setPeriod(e.target.value)} className="field mono">
              {periods.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <button onClick={run} disabled={!bankId || loading} className="btn btn-primary">
            <Calculator className="w-4 h-4" />
            {loading ? "Calculando…" : "Calcular"}
          </button>
        </div>
      </Card>

      {error ? (
        <StateBlock kind="error" message="No se pudo calcular el rating. Verifica que haya datos para el período." />
      ) : !result ? (
        <StateBlock kind="empty" message="Selecciona una entidad y un período, y ejecuta el cálculo." />
      ) : (
        <div className="grid lg:grid-cols-3 gap-5">
          <Card className="flex flex-col items-center text-center">
            <div className="text-xs text-muted mb-2 w-full truncate">{bankName}</div>
            <ScoreGauge score={result.overall_score} size={150} />
            <div className="mt-3">
              <RatingBadge tier={result.rating_tier} size="lg" />
            </div>
          </Card>

          <Card>
            <CardHead icon={RadarIcon} title="Sub-componentes" subtitle="Perfil de la entidad" />
            <RadarChart data={result.sub_components} />
          </Card>

          <Card>
            <CardHead title="Ponderación" subtitle="Solidez 40 · Calidad 30 · Efic. 15 · Liq. 10 · Div. 5" />
            <div className="space-y-3">
              {SUB_KEYS.map((key) => {
                const val = result.sub_components[key];
                return (
                  <div key={key}>
                    <div className="flex items-baseline justify-between mb-1">
                      <span className="text-sm text-ink truncate">{SUB_LABELS[key]}</span>
                      <span className="mono text-sm font-semibold text-ink">{fmtNum(val, 1)}</span>
                    </div>
                    <div className="h-2 rounded-full bg-surface2 overflow-hidden">
                      <div className="h-full rounded-full bg-accent" style={{ width: `${val}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card className="lg:col-span-3">
            <CardHead icon={ListChecks} title="Indicadores" subtitle="19 indicadores normalizados" />
            <IndicatorTable indicators={result.indicators ?? {}} />
          </Card>
        </div>
      )}
    </div>
  );
}
