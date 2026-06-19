import { useCallback, useEffect, useRef, useState } from "react";
import { Scale, RefreshCw, AlertTriangle } from "lucide-react";
import { CardHead, StatTile, StateBlock } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { REGION_NAMES } from "../data";
import { getConvergentValidity, runConvergentValidity, ConvergentReport } from "../api";

export function ValidationTab() {
  const [report, setReport] = useState<ConvergentReport | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getConvergentValidity());
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
      const res = await runConvergentValidity();
      if (!res.started) {
        setBusy(false);
        return;
      }
      let ticks = 0;
      poll.current = window.setInterval(async () => {
        ticks += 1;
        try {
          const r = await getConvergentValidity();
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

  if (status === "loading") return <StateBlock kind="loading" message="Cargando validación…" />;
  if (status === "error") return <StateBlock kind="error" message="No se pudo cargar la validación." />;
  if (!report?.has_report || !report.has_data || report.spearman == null) {
    return (
      <div>
        <div className="flex justify-end mb-3">{regenBtn}</div>
        <StateBlock
          kind="empty"
          message="La validación aún no se ha calculado. Usa «Regenerar» (necesita el IDM con scores persistidos)."
        />
      </div>
    );
  }

  const pairs = report.pairs ?? [];
  const ci = report.spearman_ci;

  return (
    <div>
      <CardHead
        icon={Scale}
        title="Validez convergente"
        subtitle="Ranking regional del IDM vs IDH regional del PNUD (IDHr)"
        right={regenBtn}
      />

      <div className="mb-4 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">Validez convergente, no backtest temporal.</span>{" "}
          {report.disclaimer}
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label="Spearman ρ" value={fmtNum(report.spearman, 3)} />
        <StatTile label="IC 95%" value={ci ? `${fmtNum(ci[0], 2)} – ${fmtNum(ci[1], 2)}` : "—"} />
        <StatTile label="Regiones" value={report.n_regions ?? "—"} />
        <StatTile label="Referencia" value="IDHr · PNUD" />
      </div>

      <div className="rounded-[10px] border border-line overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface2 text-[11px] uppercase tracking-wide text-muted">
              <th className="text-left px-3 py-2">Región</th>
              <th className="text-right px-3 py-2">IDM</th>
              <th className="text-right px-3 py-2">Rango IDM</th>
              <th className="text-right px-3 py-2">IDHr</th>
              <th className="text-right px-3 py-2">Rango IDHr</th>
              <th className="text-right px-3 py-2">Δ rango</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p) => (
              <tr key={p.region} className="border-t border-line/60">
                <td className="px-3 py-2 text-ink truncate">{REGION_NAMES[p.region] ?? p.region}</td>
                <td className="px-3 py-2 text-right mono tabular-nums text-body">{fmtNum(p.idm_score, 1)}</td>
                <td className="px-3 py-2 text-right mono tabular-nums text-body">{p.idm_rank}</td>
                <td className="px-3 py-2 text-right mono tabular-nums text-body">{fmtNum(p.idhr, 3)}</td>
                <td className="px-3 py-2 text-right mono tabular-nums text-body">{p.idhr_rank}</td>
                <td
                  className={`px-3 py-2 text-right mono tabular-nums ${
                    Math.abs(p.rank_diff) >= 3 ? "text-warn font-semibold" : "text-faint"
                  }`}
                >
                  {p.rank_diff > 0 ? `+${p.rank_diff}` : p.rank_diff}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-faint">
        {report.source}
        {report.generated_at && (
          <> · {new Date(report.generated_at).toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" })}</>
        )}
      </p>
    </div>
  );
}
