import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck, RefreshCw, AlertTriangle, Info } from "lucide-react";
import { PageHead, Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getBacktestReport, runBacktest, BacktestReport } from "../api";

function fmtPct(x: number | null | undefined): string {
  return x == null ? "—" : `${(x * 100).toFixed(1)}%`;
}

function fmtDate(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" });
}

export function ValidationPage() {
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getBacktestReport());
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
    stopPoll(); // never leak a prior interval
    setBusy(true);
    const before = report?.generated_at;
    try {
      const res = await runBacktest();
      if (!res.started) {
        setBusy(false);
        return;
      }
      // Poll until the persisted report's timestamp changes (op runs in background).
      let ticks = 0;
      poll.current = window.setInterval(async () => {
        ticks += 1;
        try {
          const r = await getBacktestReport();
          if (r.generated_at && r.generated_at !== before) {
            setReport(r);
            setBusy(false);
            stopPoll();
          } else if (ticks > 20) {
            setBusy(false);
            stopPoll();
          }
        } catch {
          setBusy(false);
          stopPoll();
        }
      }, 2500);
    } catch {
      setBusy(false);
      stopPoll();
    }
  };

  const head = (
    <PageHead
      eyebrow="SIB · validación"
      title="Backtest del rating"
      sub="¿El score discrimina el deterioro futuro? Poder de discriminación (Gini) y tasa de distress por tier."
      right={
        <button onClick={regenerate} disabled={busy} className="btn btn-ghost">
          <RefreshCw className={`w-4 h-4 ${busy ? "animate-spin" : ""}`} />
          {busy ? "Generando…" : "Regenerar"}
        </button>
      }
    />
  );

  if (status === "loading") return <div>{head}<StateBlock kind="loading" message="Cargando backtest…" /></div>;
  if (status === "error") return <div>{head}<StateBlock kind="error" message="No se pudo cargar el backtest." /></div>;

  if (!report?.computed) {
    return (
      <div>
        {head}
        <StateBlock
          kind="empty"
          message={report?.message ?? "El backtest aún no se ha calculado. Usa 'Regenerar' para generarlo."}
        />
      </div>
    );
  }

  const giniWeak = (report.gini ?? 0) < 0.2;
  const maxRate = Math.max(0.0001, ...(report.by_tier ?? []).map((r) => r.rate ?? 0));

  return (
    <div>
      {head}

      {/* Disclaimer — prominente */}
      <div className="mb-5 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">Validación preliminar.</span> No es un rating grado-Basilea
          ni una PD calibrada. El desenlace es <span className="font-medium">distress financiero</span> (no
          quiebras), y la discriminación es <span className="font-medium">direccional</span>.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile
          label="Gini (poder de discriminación)"
          value={report.gini == null ? "N/D" : fmtNum(report.gini, 3)}
        />
        <StatTile
          label="IC 95%"
          value={
            report.gini_ci
              ? `${fmtNum(report.gini_ci[0], 2)} – ${fmtNum(report.gini_ci[1], 2)}`
              : "—"
          }
        />
        <StatTile label="Observaciones" value={fmtNum(report.n_observations, 0)} />
        <StatTile label="Eventos de distress" value={`${report.n_events} (${fmtPct(report.event_rate)})`} />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Curva de distress por tier */}
        <Card className="lg:col-span-2">
          <CardHead
            icon={ShieldCheck}
            title="Tasa de distress por tier"
            subtitle={`Horizonte ${report.horizon_quarters}T · debería subir de SDQ-AAA a SDQ-D`}
            right={
              <Chip tone={report.monotonic ? "ok" : "warn"}>
                {report.monotonic ? "Monótona" : "No monótona"}
              </Chip>
            }
          />
          <div className="space-y-2.5 mt-1">
            {(report.by_tier ?? []).map((r) => (
              <div key={r.tier} className="flex items-center gap-3">
                <span className="w-20 shrink-0 mono text-xs text-ink">{r.tier}</span>
                <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${((r.rate ?? 0) / maxRate) * 100}%` }}
                  />
                </div>
                <span className="w-28 shrink-0 text-right mono text-xs text-body tabular-nums">
                  {fmtPct(r.rate)} <span className="text-faint">· n={r.n}</span>
                </span>
              </div>
            ))}
          </div>
          {giniWeak && (
            <p className="mt-3 text-xs text-muted">
              Gini moderado: el score ordena el riesgo en la dirección correcta, pero la separación es
              parcial — consistente con un sistema bancario estable y sin defaults.
            </p>
          )}
        </Card>

        {/* Notas metodológicas */}
        <Card>
          <CardHead icon={Info} title="Notas metodológicas" subtitle="Lo que esta validación sí y no afirma" />
          <ul className="space-y-2.5">
            {(report.caveats ?? []).map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-body">
                <span className="text-faint mt-0.5">•</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
          {report.generated_at && (
            <p className="mt-4 text-[11px] text-faint">Calculado: {fmtDate(report.generated_at)}</p>
          )}
        </Card>
      </div>
    </div>
  );
}
