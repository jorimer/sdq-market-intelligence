import { useEffect, useState } from "react";
import { Sliders, RotateCcw, Zap } from "lucide-react";
import { BankSelector } from "../components/BankSelector";
import { RadarChart } from "../components/RadarChart";
import { ScoreGauge } from "../components/ScoreGauge";
import { RatingBadge } from "../components/RatingBadge";
import { PageHead, Card, CardHead, StateBlock, Delta } from "@/shared/ui/primitives";
import {
  listPeriods,
  runScoring,
  simulate,
  ScoringResult,
  SubComponents,
  SUB_KEYS,
  SUB_LABELS,
} from "../api";

const PRESETS: Record<string, SubComponents> = {
  Optimista: { solidez: 90, calidad: 85, eficiencia: 80, liquidez: 85, diversificacion: 80 },
  Base: { solidez: 65, calidad: 60, eficiencia: 55, liquidez: 60, diversificacion: 55 },
  Adverso: { solidez: 40, calidad: 35, eficiencia: 30, liquidez: 35, diversificacion: 30 },
  Estrés: { solidez: 25, calidad: 20, eficiencia: 15, liquidez: 20, diversificacion: 15 },
};

function fromResult(r: ScoringResult): SubComponents {
  return { ...r.sub_components };
}

export function ScenariosPage() {
  const [bankId, setBankId] = useState("");
  const [bankName, setBankName] = useState("");
  const [periods, setPeriods] = useState<string[]>([]);
  const [period, setPeriod] = useState("");
  const [base, setBase] = useState<ScoringResult | null>(null);
  const [sim, setSim] = useState<ScoringResult | null>(null);
  const [sliders, setSliders] = useState<SubComponents>({ ...PRESETS.Base });
  const [loading, setLoading] = useState(false);
  const [simulating, setSimulating] = useState(false);

  useEffect(() => {
    listPeriods().then((p) => {
      setPeriods(p);
      if (p.length) setPeriod(p[0]);
    });
  }, []);

  const loadBase = async () => {
    if (!bankId || !period) return;
    setLoading(true);
    try {
      const r = await runScoring(bankId, period);
      setBase(r);
      setSliders(fromResult(r));
      setSim(null);
    } catch {
      setBase(null);
    } finally {
      setLoading(false);
    }
  };

  const runSim = async () => {
    if (!bankId) return;
    setSimulating(true);
    try {
      setSim(await simulate(sliders, base?.entity_type ?? undefined));
    } catch {
      // silent
    } finally {
      setSimulating(false);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow="iSRM · what-if"
        title="Escenarios"
        sub="Modela el rating ajustando los sub-componentes (iSRM). Carga la base de una entidad y simula."
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
          <button onClick={loadBase} disabled={!bankId || loading} className="btn btn-primary">
            <Sliders className="w-4 h-4" />
            {loading ? "Cargando…" : "Cargar base"}
          </button>
        </div>
      </Card>

      {!base ? (
        <StateBlock kind="empty" message="Selecciona una entidad y carga su base para iniciar la simulación." />
      ) : (
        <div className="grid lg:grid-cols-3 gap-5">
          {/* Sliders */}
          <Card>
            <CardHead title="Ajustar sub-componentes" subtitle={bankName} />
            <div className="space-y-4">
              {SUB_KEYS.map((key) => (
                <div key={key}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-body">{SUB_LABELS[key]}</span>
                    <span className="mono font-semibold text-ink">{sliders[key].toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={0.5}
                    value={sliders[key]}
                    onChange={(e) => setSliders((s) => ({ ...s, [key]: parseFloat(e.target.value) }))}
                    className="w-full accent-accent"
                  />
                </div>
              ))}
            </div>
            <div className="mt-4">
              <p className="text-xs font-medium text-muted mb-2">Presets</p>
              <div className="grid grid-cols-2 gap-2">
                {Object.keys(PRESETS).map((p) => (
                  <button
                    key={p}
                    onClick={() => setSliders({ ...PRESETS[p] })}
                    className="text-xs px-2 py-1.5 rounded-[10px] border border-line hover:bg-surface2 text-body"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-2 mt-4">
              <button onClick={runSim} disabled={simulating} className="btn btn-primary flex-1">
                <Zap className="w-4 h-4" />
                {simulating ? "Simulando…" : "Simular"}
              </button>
              <button
                onClick={() => { setSliders(fromResult(base)); setSim(null); }}
                className="btn btn-ghost"
                title="Restablecer"
              >
                <RotateCcw className="w-4 h-4" />
              </button>
            </div>
          </Card>

          {/* Radar */}
          <Card>
            <CardHead title="Base vs. simulado" subtitle="Perfil de sub-componentes" />
            <RadarChart
              data={base.sub_components}
              comparisonData={sim?.sub_components}
              comparisonLabel="Simulado"
            />
          </Card>

          {/* Gauges */}
          <Card className="space-y-5">
            <div className="text-center">
              <p className="text-xs text-muted mb-2">Base</p>
              <div className="flex flex-col items-center">
                <ScoreGauge score={base.overall_score} size={120} />
                <div className="mt-2"><RatingBadge tier={base.rating_tier} size="md" /></div>
              </div>
            </div>
            {sim && (
              <div className="border-t border-line pt-5 text-center">
                <p className="text-xs text-muted mb-2">Simulado</p>
                <div className="flex flex-col items-center">
                  <ScoreGauge score={sim.overall_score} size={120} />
                  <div className="mt-2"><RatingBadge tier={sim.rating_tier} size="md" /></div>
                </div>
                <div className="mt-3">
                  <Delta value={sim.overall_score - base.overall_score} />
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
