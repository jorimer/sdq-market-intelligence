import { useState } from "react";
import { ShieldCheck, Loader2, CheckCircle2, XCircle, MinusCircle } from "lucide-react";
import { Card, CardHead, Chip } from "@/shared/ui/primitives";
import { getCrosscheck, CrosscheckResult } from "../api";

/** Validation against ground truth: compare the Excel-extracted series to the live
 * BCRD API series, period by period. The strongest correctness signal. */
export function MacroCrosscheckSection() {
  const [results, setResults] = useState<CrosscheckResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    setBusy(true);
    setErr("");
    try {
      const { results } = await getCrosscheck();
      setResults(results);
    } catch (e: unknown) {
      const s = (e as { response?: { status?: number } })?.response?.status;
      setErr(s === 403 ? "Requiere rol de administrador." : "No se pudo correr el cruce.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHead
        icon={ShieldCheck}
        title="Validación contra el API"
        subtitle="Compara las series del Excel con las del API del BCRD, mes a mes"
        right={
          <button onClick={run} disabled={busy} className="btn btn-soft">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
            {busy ? "Cruzando…" : "Validar contra el API"}
          </button>
        }
      />

      {err && <div className="text-sm p-3 rounded-[10px] bg-alert-soft text-alert">{err}</div>}

      {!results && !err && (
        <p className="text-sm text-muted">
          Cruza el dato extraído del histórico Excel contra el que el API del BCRD reporta
          (IPC vía variación interanual —invariante a la base—, reservas). Si coinciden, el
          motor extrae correctamente.
        </p>
      )}

      {results && (
        <div className="space-y-2.5">
          {results.map((r, i) => {
            const noOverlap = !r.error && (r.n_compared ?? 0) === 0;
            return (
              <div key={i} className="rounded-[10px] bg-surface2 p-3">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-ink truncate">{r.label}</div>
                    {r.api_series && (
                      <div className="mono text-[11px] text-faint truncate">
                        {r.api_series}
                        {r.transform === "yoy" ? " · interanual" : ""}
                      </div>
                    )}
                  </div>
                  {r.error ? (
                    <Chip tone="alert">
                      <XCircle size={12} /> error
                    </Chip>
                  ) : noOverlap ? (
                    <Chip tone="muted">
                      <MinusCircle size={12} /> sin solapamiento
                    </Chip>
                  ) : r.ok ? (
                    <Chip tone="ok">
                      <CheckCircle2 size={12} /> {r.n_match}/{r.n_compared} coinciden
                    </Chip>
                  ) : (
                    <Chip tone="warn">
                      <XCircle size={12} /> {r.n_mismatch} difieren
                    </Chip>
                  )}
                </div>

                {r.error ? (
                  <p className="text-xs text-alert mt-1.5">{r.error}</p>
                ) : noOverlap ? (
                  <p className="text-xs text-muted mt-1.5">
                    El API aún no tiene períodos solapados (solo {r.api_obs ?? 0} obs). {r.note}
                  </p>
                ) : (
                  <div className="text-xs text-muted mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                    <span>
                      {r.period_min} → {r.period_max} ({r.n_compared} puntos)
                    </span>
                    <span>
                      error máx · <span className="mono text-ink">{r.max_abs_err}</span>
                    </span>
                  </div>
                )}

                {r.examples && r.examples.length > 0 && (
                  <div className="mt-2 text-xs">
                    <div className="text-faint mb-1">Diferencias:</div>
                    {r.examples.map((e, j) => (
                      <div key={j} className="mono text-body">
                        {e.period}: excel <span className="text-ink">{e.excel}</span> · api{" "}
                        <span className="text-ink">{e.api}</span> (Δ {e.abs_err})
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
