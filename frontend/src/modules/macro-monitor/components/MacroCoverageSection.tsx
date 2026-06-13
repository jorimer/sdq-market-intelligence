import { useCallback, useEffect, useRef, useState } from "react";
import { Layers, Play, Loader2, AlertTriangle, XCircle } from "lucide-react";
import { Card, CardHead, StatTile, Chip, StateBlock } from "@/shared/ui/primitives";
import { getExcelCoverage, runExcelBatch, ExcelCoverage } from "../api";

const SECTOR_LABEL: Record<string, string> = {
  sector_real: "Sector real",
  precios: "Precios",
  sector_externo: "Sector externo",
  sector_monetario_financiero: "Monetario y financiero",
  sector_turismo: "Turismo",
  mercado_cambiario: "Mercado cambiario",
  mercado_de_trabajo: "Mercado de trabajo",
};

/** Corpus-wide coverage: run the engine over the catalog (background) and report
 * how it resolved — heuristic vs Claude, by frequency — plus the files flagged
 * for review or that failed. */
export function MacroCoverageSection() {
  const [cov, setCov] = useState<ExcelCoverage | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const [limit, setLimit] = useState<number | "">(20);
  const [persist, setPersist] = useState(false);
  const [note, setNote] = useState("");
  // When the batch runs in the Celery worker, the web process's `is_running` flag
  // stays false (the in-memory status lives in the worker) — so we also drive live
  // updates off the persisted `reported` count climbing toward the catalog total.
  const [polling, setPolling] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastRep = useRef(-1);
  const stale = useRef(0);

  const load = useCallback(async () => {
    try {
      const c = await getExcelCoverage();
      setCov(c);
      setStatus("ready");
      if (c.reported === lastRep.current) stale.current += 1;
      else {
        stale.current = 0;
        lastRep.current = c.reported;
      }
      // Stop polling once it's clearly done: all reported, or the count has been
      // flat for ~20s while the worker reports it isn't running.
      const finished =
        !c.status.is_running &&
        (c.reported >= c.total_catalog || (c.reported > 0 && stale.current >= 5));
      if (finished) setPolling(false);
      return c;
    } catch {
      setStatus("error");
      return null;
    }
  }, []);

  // First load: if a batch is already in flight (count below total), start polling.
  useEffect(() => {
    load().then((c) => {
      if (c && (c.status.is_running || (c.reported > 0 && c.reported < c.total_catalog))) {
        setPolling(true);
      }
    });
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load]);

  useEffect(() => {
    const active = cov?.status?.is_running || polling;
    if (active && !timer.current) {
      timer.current = setInterval(load, 4000);
    } else if (!active && timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, [cov?.status?.is_running, polling, load]);

  const run = async () => {
    setBusy(true);
    setNote("");
    try {
      const res = await runExcelBatch({ limit: limit === "" ? undefined : limit, persist });
      setNote(res.message);
      lastRep.current = -1;
      stale.current = 0;
      setPolling(true); // keep the panel live even when it runs in the Celery worker
      await load();
    } catch (e: unknown) {
      const s = (e as { response?: { status?: number } })?.response?.status;
      setNote(s === 403 ? "Requiere rol de administrador." : "No se pudo lanzar el barrido.");
    } finally {
      setBusy(false);
    }
  };

  if (status === "error") {
    return <StateBlock kind="error" message="No se pudo cargar la cobertura del corpus." />;
  }

  const st = cov?.status;
  // "active" = either the worker reports running, or we're polling a Celery run
  // whose progress shows up as the persisted count climbing toward the total.
  const active = !!st?.is_running || polling;
  const byStatus = cov?.by_status ?? {};
  const total = cov?.total_catalog ?? 0;
  const reported = cov?.reported ?? 0;
  const pct = st?.is_running && st.total
    ? Math.round((st.done / st.total) * 100)
    : total
      ? Math.round((reported / total) * 100)
      : 0;

  return (
    <Card>
      <CardHead
        icon={Layers}
        title="Cobertura del corpus"
        subtitle="Barrido del motor sobre el catálogo: qué resolvió y qué quedó para revisión"
        right={
          active ? (
            <span className="chip text-warn flex items-center gap-1">
              <Loader2 size={12} className="animate-spin" /> {reported}/{total}
            </span>
          ) : (
            <span className="chip text-muted">{reported}/{total} reportados</span>
          )
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatTile label="Reportados" value={cov?.reported ?? 0} />
        <StatTile label="OK" value={byStatus.ok ?? 0} />
        <StatTile label="Marcados" value={byStatus.flagged ?? 0} />
        <StatTile label="Fallidos" value={byStatus.failed ?? 0} />
      </div>

      {/* método + frecuencia */}
      {cov && (cov.reported > 0) && (
        <div className="flex flex-wrap gap-2 mb-4 text-xs">
          {Object.entries(cov.by_method).map(([m, n]) => (
            <span key={m} className="rounded-full bg-surface2 px-2.5 py-1">
              {m === "claude" ? "vía Claude" : m === "heuristic" ? "heurística" : m}:{" "}
              <span className="mono text-ink font-semibold">{n}</span>
            </span>
          ))}
          {Object.entries(cov.by_frequency).map(([f, n]) => (
            <span key={f} className="rounded-full bg-surface2 px-2.5 py-1 text-muted">
              {f}: <span className="mono text-ink font-semibold">{n}</span>
            </span>
          ))}
        </div>
      )}

      {active && (
        <div className="mb-4">
          <div className="h-1.5 rounded-full bg-surface2 overflow-hidden">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-xs text-muted mt-2">
            Barrido en progreso ({reported}/{total} · {pct}%). Puedes salir de esta pantalla; el proceso sigue.
          </p>
        </div>
      )}

      {/* controles */}
      <div className="flex flex-wrap items-center gap-3 mb-2">
        <label className="flex items-center gap-2 text-xs text-muted">
          Límite
          <input
            type="number"
            className="field mono w-20"
            value={limit}
            min={1}
            placeholder="todos"
            onChange={(e) => setLimit(e.target.value === "" ? "" : Number(e.target.value))}
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-body cursor-pointer select-none">
          <input
            type="checkbox"
            checked={persist}
            onChange={(e) => setPersist(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          Persistir series (bcrd.xls.*)
        </label>
        <button onClick={run} disabled={busy || active} className="btn btn-primary">
          {busy || active ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          {active ? "En progreso…" : limit === "" ? "Correr todo el catálogo" : `Correr barrido (${limit})`}
        </button>
      </div>
      {note && <p className="text-xs text-muted bg-surface2 px-3 py-2 rounded-[10px] mb-2">{note}</p>}

      {/* atención: marcados + fallidos */}
      {cov && cov.attention.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold text-muted mb-2">
            Para revisión ({cov.attention.length})
          </div>
          <div className="overflow-x-auto -mx-1 max-h-80 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface">
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-1 font-medium">Archivo</th>
                  <th className="py-2 px-1 font-medium">Sector</th>
                  <th className="py-2 px-1 font-medium">Estado</th>
                  <th className="py-2 px-1 font-medium">Detalle</th>
                </tr>
              </thead>
              <tbody>
                {cov.attention.map((a, i) => (
                  <tr key={i} className="border-b border-line/60 last:border-0 align-top">
                    <td className="py-2 px-1 mono text-[12px] text-ink">{a.filename}</td>
                    <td className="py-2 px-1 text-xs text-body">
                      {a.sector ? SECTOR_LABEL[a.sector] ?? a.sector : "—"}
                    </td>
                    <td className="py-2 px-1">
                      {a.status === "failed" ? (
                        <Chip tone="alert">
                          <XCircle size={12} /> fallido
                        </Chip>
                      ) : (
                        <Chip tone="warn">
                          <AlertTriangle size={12} /> marcado
                        </Chip>
                      )}
                    </td>
                    <td className="py-2 px-1 text-xs text-muted">
                      {a.status === "failed"
                        ? a.error
                        : a.flags
                            .slice(0, 3)
                            .map((f) => `${f.code.split(".").slice(-1)[0]}: ${f.flags.join(", ")}`)
                            .join(" · ") ||
                          (a.n_series === 0
                            ? "sin series extraídas (revisar layout)"
                            : `${a.n_flagged} de ${a.n_series} series marcadas`)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
