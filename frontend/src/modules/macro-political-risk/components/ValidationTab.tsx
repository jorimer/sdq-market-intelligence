import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck, RefreshCw, AlertTriangle, Scale } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getBacktest, runBacktest, BacktestReport, BacktestMetrics } from "../api";

const COUNTRY: Record<string, string> = {
  DO: "Rep. Dominicana", CR: "Costa Rica", PA: "Panamá", GT: "Guatemala", JM: "Jamaica",
};

function fmtPct(x: number | null | undefined): string {
  return x == null ? "—" : `${(x * 100).toFixed(0)}%`;
}
function fmtDate(iso?: string): string {
  return iso ? new Date(iso).toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" }) : "—";
}

function BandCurve({ m }: { m: BacktestMetrics }) {
  const maxRate = Math.max(0.0001, ...m.distress_by_band.map((r) => r.rate ?? 0));
  return (
    <div className="space-y-2.5 mt-1">
      {m.distress_by_band.map((r) => (
        <div key={r.tier} className="flex items-center gap-3">
          <span className="w-20 shrink-0 mono text-xs text-ink">{r.tier}</span>
          <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
            <div className="h-full rounded-full bg-accent" style={{ width: `${((r.rate ?? 0) / maxRate) * 100}%` }} />
          </div>
          <span className="w-28 shrink-0 text-right mono text-xs text-body tabular-nums">
            {fmtPct(r.rate)} <span className="text-faint">· n={r.n}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

export function ValidationTab() {
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getBacktest());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
    return () => { if (poll.current) window.clearInterval(poll.current); };
  }, [load]);

  const stopPoll = () => { if (poll.current) { window.clearInterval(poll.current); poll.current = null; } };

  const regenerate = async () => {
    if (busy) return;
    stopPoll();
    setBusy(true);
    const before = report?.generated_at;
    try {
      const res = await runBacktest();
      if (!res.started) { setBusy(false); return; }
      let ticks = 0;
      poll.current = window.setInterval(async () => {
        ticks += 1;
        try {
          const r = await getBacktest();
          if (r.generated_at && r.generated_at !== before) {
            setReport(r); setBusy(false); stopPoll();
          } else if (ticks > 30) { setBusy(false); stopPoll(); }
        } catch { setBusy(false); stopPoll(); }
      }, 3000);
    } catch { setBusy(false); stopPoll(); }
  };

  const regenBtn = (
    <button onClick={regenerate} disabled={busy} className="btn btn-ghost !py-1.5">
      <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} />
      {busy ? "Generando… (~1 min)" : "Regenerar"}
    </button>
  );

  if (status === "loading") return <StateBlock kind="loading" message="Cargando backtest…" />;
  if (status === "error") return <StateBlock kind="error" message="No se pudo cargar el backtest." />;
  if (!report?.has_report || !report.governance) {
    return (
      <div>
        <div className="flex justify-end mb-3">{regenBtn}</div>
        <StateBlock kind="empty" message="El backtest aún no se ha calculado. Usa 'Regenerar' (corre en prod, ~1 min)." />
      </div>
    );
  }

  const g = report.governance;
  const c = report.credit;
  const cv = report.convergent_validity;

  return (
    <div>
      {/* Disclaimer honesto — prominente */}
      <div className="mb-4 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">Validación preliminar y direccional, no grado-Basilea.</span>{" "}
          {report.disclaimer}
        </p>
      </div>

      <div className="flex items-center justify-between mb-3 gap-3">
        <span className="text-xs text-muted">
          Outcome: <span className="text-body">inestabilidad política realizada</span> (eventos GDELT).
          Metodología validada en panel amplio LatAm+Caribe ({report.n_countries} países); el producto es
          el peer set regional.
          {report.generated_at && <> · {fmtDate(report.generated_at)}</>}
        </span>
        {regenBtn}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label="Gini (gobernanza)" value={g.gini == null ? "N/D" : fmtNum(g.gini, 3)} />
        <StatTile
          label="IC 95%"
          value={g.gini_ci ? `${fmtNum(g.gini_ci[0], 2)} – ${fmtNum(g.gini_ci[1], 2)}` : "—"}
        />
        <StatTile label="Observaciones" value={`${fmtNum(g.n_observations, 0)} (${report.n_countries} países)`} />
        <StatTile label="Eventos" value={`${g.n_events} (${fmtPct(g.event_rate)})`} />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHead
            icon={ShieldCheck}
            title="Tasa de inestabilidad por banda IRMP"
            subtitle="Debería subir de Bajo a Alto si el índice discrimina"
            right={<Chip tone={g.monotonic ? "ok" : "warn"}>{g.monotonic ? "Monótona" : "No monótona"}</Chip>}
          />
          <BandCurve m={g} />
          {(g.gini == null || g.gini < 0.2) && (
            <p className="mt-3 text-xs text-muted">
              Con N=5 países y pocos eventos, el intervalo de confianza incluye cero: el IRMP{" "}
              <span className="font-medium">no demuestra discriminación</span>. Es un índice explicable
              sobre dato real, no un predictor validado — honestidad sobre N pequeño, no maquillaje.
            </p>
          )}
        </Card>

        <Card>
          <CardHead icon={Scale} title="Validez convergente" subtitle="IRMP vs rating soberano S&P" />
          <div className="mb-3">
            <div className="text-xs text-muted">Correlación de rango (Spearman)</div>
            <div className="text-2xl font-display text-ink tabular-nums">
              {cv?.spearman_irmp_vs_rating == null ? "—" : fmtNum(cv.spearman_irmp_vs_rating, 2)}
            </div>
          </div>
          <div className="space-y-1.5">
            {(cv?.pairs ?? []).map((p) => (
              <div key={p.iso} className="flex items-center justify-between text-xs">
                <span className="text-ink truncate">{COUNTRY[p.iso] ?? p.iso}</span>
                <span className="mono text-body tabular-nums">
                  IRMP {fmtNum(p.irmp, 0)} · {p.rating}
                </span>
              </div>
            ))}
          </div>
          {c && (
            <p className="mt-4 pt-3 border-t border-line/60 text-[11px] text-faint">
              Contraste (outcome de crédito, solapa con inputs): Gini {c.gini == null ? "N/D" : fmtNum(c.gini, 3)}.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
