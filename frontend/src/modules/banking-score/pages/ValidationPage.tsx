import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck, RefreshCw, AlertTriangle, Info } from "lucide-react";
import { PageHead, Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getBacktestReport, runBacktest, BacktestReport } from "../api";

function fmtPct(x: number | null | undefined): string {
  return x == null ? "—" : `${(x * 100).toFixed(1)}%`;
}

const DATE_LOCALE: Record<string, string> = { es: "es-DO", en: "en-US", fr: "fr-FR" };

function fmtDate(iso: string | undefined, lang: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(DATE_LOCALE[lang] ?? "es-DO", { dateStyle: "medium", timeStyle: "short" });
}

export function ValidationPage() {
  const { t, i18n } = useTranslation();
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
      eyebrow={t("banking.valEyebrow")}
      title={t("banking.valTitle")}
      sub={t("banking.valSub")}
      right={
        <button onClick={regenerate} disabled={busy} className="btn btn-ghost">
          <RefreshCw className={`w-4 h-4 ${busy ? "animate-spin" : ""}`} />
          {busy ? t("banking.valBtnGenerating") : t("banking.valBtnRegenerate")}
        </button>
      }
    />
  );

  if (status === "loading") return <div>{head}<StateBlock kind="loading" message={t("banking.valLoading")} /></div>;
  if (status === "error") return <div>{head}<StateBlock kind="error" message={t("banking.valErrorLoad")} /></div>;

  if (!report?.computed) {
    return (
      <div>
        {head}
        <StateBlock
          kind="empty"
          message={report?.message ?? t("banking.valEmpty")}
        />
      </div>
    );
  }

  const giniWeak = (report.gini ?? 0) < 0.2;
  // La tabla por banda NO se presenta como ordenamiento cuando no ordena. No se oculta —un
  // parcial escondido desaparece sin aviso—: se muestra rotulada por lo que es, una tasa
  // observada por banda, con la inversión concreta nombrada arriba.
  const ordenaRiesgo = report.by_tier_ordena_riesgo ?? report.monotonic ?? true;
  const inversion = (report.monotonic_violations ?? [])[0];
  const maxRate = Math.max(0.0001, ...(report.by_tier ?? []).map((r) => r.rate ?? 0));

  return (
    <div>
      {head}

      {/* Disclaimer — prominente */}
      <div className="mb-5 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">{t("banking.valDiscBold")}</span>{t("banking.valDiscPre")}
          <span className="font-medium">{t("banking.valDiscDistress")}</span>{t("banking.valDiscMid")}
          <span className="font-medium">{t("banking.valDiscDirectional")}</span>.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile
          label={t("banking.valStatGini")}
          value={report.gini == null ? t("banking.na") : fmtNum(report.gini, 3)}
        />
        <StatTile
          label={t("banking.valStatCi")}
          value={
            report.gini_ci
              ? `${fmtNum(report.gini_ci[0], 2)} – ${fmtNum(report.gini_ci[1], 2)}`
              : "—"
          }
        />
        <StatTile label={t("banking.valStatObs")} value={fmtNum(report.n_observations, 0)} />
        <StatTile label={t("banking.valStatEvents")} value={`${report.n_events} (${fmtPct(report.event_rate)})`} />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Curva de distress por tier */}
        <Card className="lg:col-span-2">
          <CardHead
            icon={ShieldCheck}
            title={ordenaRiesgo ? t("banking.valTierTitle") : t("banking.valTierTitleNoOrder")}
            subtitle={
              ordenaRiesgo
                ? t("banking.valTierSubtitle", { q: report.horizon_quarters })
                : t("banking.valTierSubtitleNoOrder", { q: report.horizon_quarters })
            }
            right={
              <Chip tone={report.monotonic ? "ok" : "warn"}>
                {report.monotonic ? t("banking.valMonotonic") : t("banking.valNonMonotonic")}
              </Chip>
            }
          />
          {!ordenaRiesgo && (
            <div className="mb-3 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3">
              <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
              <p className="text-xs text-body">
                <span className="font-semibold text-ink">{t("banking.valTierNoOrderBold")}</span>{" "}
                {inversion
                  ? t("banking.valTierNoOrderDetail", {
                      mejor: inversion.mejor,
                      mejorN: inversion.mejor_n,
                      mejorRate: fmtPct(inversion.mejor_rate),
                      peor: inversion.peor,
                      peorN: inversion.peor_n,
                      peorRate: fmtPct(inversion.peor_rate),
                    })
                  : t("banking.valTierNoOrderPlain")}
              </p>
            </div>
          )}
          <div className="space-y-2.5 mt-1">
            {(report.by_tier ?? []).map((r) => (
              <div key={r.tier} className="flex items-center gap-3">
                <span className="w-20 shrink-0 mono text-xs text-ink">{r.tier}</span>
                <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${ordenaRiesgo ? "bg-accent" : "bg-warn"}`}
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
              {t("banking.valGiniWeak")}
            </p>
          )}
        </Card>

        {/* Notas metodológicas */}
        <Card>
          <CardHead icon={Info} title={t("banking.valNotesTitle")} subtitle={t("banking.valNotesSubtitle")} />
          <ul className="space-y-2.5">
            {(report.caveats ?? []).map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-body">
                <span className="text-faint mt-0.5">•</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
          {report.generated_at && (
            <p className="mt-4 text-[11px] text-faint">{t("banking.valComputedAt", { date: fmtDate(report.generated_at, i18n.language) })}</p>
          )}
        </Card>
      </div>
    </div>
  );
}
