import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck, RefreshCw, AlertTriangle, BarChart3 } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getSectorValidation, runSectorGateE, SectorGateEReport } from "../api";

function fmtDate(iso?: string): string {
  return iso
    ? new Date(iso).toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" })
    : "—";
}
function fmtRho(x: number | null | undefined): string {
  return x == null ? "—" : (x >= 0 ? "+" : "") + x.toFixed(3);
}
function fmtPp(x: number | null | undefined): string {
  return x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)} pp`;
}

/** A signal is "significant" only when the bootstrap CI excludes zero. */
function ciExcludesZero(ci?: [number | null, number | null]): boolean {
  if (!ci || ci[0] == null || ci[1] == null) return false;
  return (ci[0] > 0 && ci[1] > 0) || (ci[0] < 0 && ci[1] < 0);
}

/** Per-year Spearman as a centered diverging bar (−1 … +1). */
function YearBars({ rows }: { rows: NonNullable<SectorGateEReport["by_year"]> }) {
  return (
    <div className="space-y-2.5 mt-1">
      {rows.map((r) => {
        const v = r.spearman ?? 0;
        const w = Math.min(50, Math.abs(v) * 50);
        return (
          <div key={r.year} className="flex items-center gap-3">
            <span className="w-12 shrink-0 mono text-xs text-ink">{r.year}</span>
            <div className="relative flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
              <div className="absolute left-1/2 top-0 h-full w-px bg-grid" />
              <div
                className="absolute top-0 h-full bg-accent"
                style={
                  v >= 0
                    ? { left: "50%", width: `${w}%` }
                    : { right: "50%", width: `${w}%` }
                }
              />
            </div>
            <span className="w-24 shrink-0 text-right mono text-xs text-body tabular-nums">
              {fmtRho(r.spearman)} <span className="text-faint">· n={r.n}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function ValidationTab() {
  const [report, setReport] = useState<SectorGateEReport | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getSectorValidation());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, [load]);

  const stopPoll = () => {
    if (poll.current) {
      window.clearInterval(poll.current);
      poll.current = null;
    }
  };

  const regenerate = async () => {
    if (busy) return;
    stopPoll();
    setBusy(true);
    const before = report?.generated_at;
    try {
      const res = await runSectorGateE();
      if (!res.started) {
        setBusy(false);
        return;
      }
      let ticks = 0;
      poll.current = window.setInterval(async () => {
        ticks += 1;
        try {
          const r = await getSectorValidation();
          if (r.generated_at && r.generated_at !== before) {
            setReport(r);
            setBusy(false);
            stopPoll();
          } else if (ticks > 30) {
            setBusy(false);
            stopPoll();
          }
        } catch {
          setBusy(false);
          stopPoll();
        }
      }, 3000);
    } catch {
      setBusy(false);
      stopPoll();
    }
  };

  const regenBtn = (
    <button onClick={regenerate} disabled={busy} className="btn btn-ghost !py-1.5">
      <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} />
      {busy ? "Generando…" : "Regenerar"}
    </button>
  );

  if (status === "loading") return <StateBlock kind="loading" message="Cargando backtest…" />;
  if (status === "error") return <StateBlock kind="error" message="No se pudo cargar el backtest." />;
  if (!report?.has_report || report.has_data === false) {
    return (
      <div>
        <div className="flex justify-end mb-3">{regenBtn}</div>
        <StateBlock
          kind="empty"
          message={
            report?.reason ??
            "El backtest aún no se ha calculado. Usa «Regenerar» para validar el IAI contra el empleo."
          }
        />
      </div>
    );
  }

  const sig = ciExcludesZero(report.spearman_ci);
  const ci = report.spearman_ci;
  const qs = report.quintile_spread;

  return (
    <div>
      {/* Disclaimer honesto — prominente */}
      <div className="mb-4 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">Validación direccional, no grado-Basilea.</span>{" "}
          {report.disclaimer}
        </p>
      </div>

      <div className="flex items-center justify-between mb-3 gap-3">
        <span className="text-xs text-muted">
          Outcome: <span className="text-body">{report.outcome}</span> ·{" "}
          {report.resolution}
          {report.generated_at && <> · {fmtDate(report.generated_at)}</>}
        </span>
        {regenBtn}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label="Spearman ρ (IAI_T → Δempleo T+1)" value={fmtRho(report.spearman)} />
        <StatTile
          label="IC 95% (bootstrap)"
          value={ci && ci[0] != null ? `${fmtRho(ci[0])} … ${fmtRho(ci[1])}` : "—"}
        />
        <StatTile
          label="ρ parcial (control crecimiento)"
          value={`${fmtRho(report.spearman_partial_growth)}${
            report.spearman_partial_n ? ` · n=${report.spearman_partial_n}` : ""
          }`}
        />
        <StatTile
          label="Observaciones"
          value={`${fmtNum(report.n_observations, 0)} · ${report.n_branches} ramas`}
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHead
            icon={ShieldCheck}
            title="IC de rango por año"
            subtitle={`¿el IAI ordena el crecimiento del empleo del año siguiente? · ${report.years?.[0]}–${report.years?.[1]}`}
            right={
              <Chip tone={sig ? "ok" : "warn"}>{sig ? "Significativo" : "No significativo"}</Chip>
            }
          />
          {report.by_year && <YearBars rows={report.by_year} />}
          <p className="mt-3 text-xs text-muted">
            {sig ? (
              <>
                El IC excluye el cero: el IAI <span className="font-medium">discrimina</span> el
                crecimiento del empleo en T+1.
              </>
            ) : (
              <>
                El IC <span className="font-medium">cruza el cero</span>: la señal es nula/débil. El
                empleo formal lo dominan shocks macro comunes y el IAI aún es ~mitad rúbrica en
                negocios/talento. Honestidad sobre la fuerza de la señal, no maquillaje.
              </>
            )}
          </p>
        </Card>

        <Card>
          <CardHead
            icon={BarChart3}
            title="Spread por quintil del IAI"
            subtitle="Crecimiento medio del empleo: quintil IAI alto vs bajo"
          />
          {qs ? (
            <div className="space-y-3 mt-1">
              <StatTile label="Quintil IAI alto" value={fmtPp(qs.top_iai_mean_growth)} />
              <StatTile label="Quintil IAI bajo" value={fmtPp(qs.bottom_iai_mean_growth)} />
              <div className="border-t border-grid pt-3">
                <StatTile label="Spread (alto − bajo)" value={fmtPp(qs.spread)} />
              </div>
              <p className="text-xs text-muted">
                Dirección {qs.spread > 0 ? "positiva" : "negativa"} ({fmtPp(qs.spread)}), pero el IC
                de rango manda sobre la significancia.
              </p>
            </div>
          ) : (
            <StateBlock kind="empty" message="Panel insuficiente para el spread." />
          )}
        </Card>
      </div>
    </div>
  );
}
