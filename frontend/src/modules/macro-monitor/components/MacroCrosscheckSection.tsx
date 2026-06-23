import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck, Loader2, CheckCircle2, XCircle, MinusCircle } from "lucide-react";
import { Card, CardHead, Chip } from "@/shared/ui/primitives";
import { getCrosscheck, CrosscheckResult } from "../api";

/** Validation against ground truth: compare the Excel-extracted series to the live
 * BCRD API series, period by period. The strongest correctness signal. */
export function MacroCrosscheckSection() {
  const { t } = useTranslation();
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
      setErr(s === 403 ? t("datos.macro.adminRequired") : t("datos.macro.crosscheck.crossError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHead
        icon={ShieldCheck}
        title={t("datos.macro.crosscheck.title")}
        subtitle={t("datos.macro.crosscheck.sub")}
        right={
          <button onClick={run} disabled={busy} className="btn btn-soft">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
            {busy ? t("datos.macro.crosscheck.crossing") : t("datos.macro.crosscheck.validate")}
          </button>
        }
      />

      {err && <div className="text-sm p-3 rounded-[10px] bg-alert-soft text-alert">{err}</div>}

      {!results && !err && (
        <p className="text-sm text-muted">
          {t("datos.macro.crosscheck.intro")}
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
                        {r.transform === "yoy" ? ` · ${t("datos.macro.crosscheck.yoy")}` : ""}
                      </div>
                    )}
                  </div>
                  {r.error ? (
                    <Chip tone="alert">
                      <XCircle size={12} /> {t("datos.macro.crosscheck.errorChip")}
                    </Chip>
                  ) : noOverlap ? (
                    <Chip tone="muted">
                      <MinusCircle size={12} /> {t("datos.macro.crosscheck.noOverlap")}
                    </Chip>
                  ) : r.ok ? (
                    <Chip tone="ok">
                      <CheckCircle2 size={12} /> {t("datos.macro.crosscheck.matches", { match: r.n_match, compared: r.n_compared })}
                    </Chip>
                  ) : (
                    <Chip tone="warn">
                      <XCircle size={12} /> {t("datos.macro.crosscheck.differ", { mismatch: r.n_mismatch })}
                    </Chip>
                  )}
                </div>

                {r.error ? (
                  <p className="text-xs text-alert mt-1.5">{r.error}</p>
                ) : noOverlap ? (
                  <p className="text-xs text-muted mt-1.5">
                    {t("datos.macro.crosscheck.noOverlapNote", { obs: r.api_obs ?? 0, note: r.note ?? "" })}
                  </p>
                ) : (
                  <div className="text-xs text-muted mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                    <span>
                      {t("datos.macro.crosscheck.range", { min: r.period_min, max: r.period_max, points: r.n_compared })}
                    </span>
                    <span>
                      {t("datos.macro.crosscheck.maxErr")} <span className="mono text-ink">{r.max_abs_err}</span>
                    </span>
                  </div>
                )}

                {r.examples && r.examples.length > 0 && (
                  <div className="mt-2 text-xs">
                    <div className="text-faint mb-1">{t("datos.macro.crosscheck.differences")}</div>
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
