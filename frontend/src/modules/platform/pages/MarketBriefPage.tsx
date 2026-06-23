import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles, RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  StateBlock,
  Chip,
  Skeleton,
} from "@/shared/ui/primitives";
import { AiInsightBody } from "@/shared/ui/AiInsightBody";
import { bandFor, riskBandFor, type Band, type Tone } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { useAuth } from "@/shared/auth/AuthContext";
import { getMarketBrief, runMarketBrief, type MarketBriefReport, type BriefAxis } from "../api";

/* ──────────────────────────────────────────────────────────────────
 * Market Brief — síntesis cross-eje de RD. Lee el brief CACHEADO (lo genera la
 * Operación "market-brief", agendable). Muestra el pulso por eje (dato real) +
 * la narrativa de Claude. "Regenerar" (admin) dispara la operación.
 * ────────────────────────────────────────────────────────────────── */

const IRMP_EJE = "Regulatorio & político";

const LOCALES: Record<string, string> = { es: "es-DO", en: "en-US", fr: "fr-FR" };

function fmtDate(iso: string | undefined, lang: string): string {
  return iso
    ? new Date(iso).toLocaleString(LOCALES[lang] ?? "es-DO", { dateStyle: "medium", timeStyle: "short" })
    : "—";
}

const ESG_EJE = "ESG & clima";

/** Tono de la banda ESG del modelo (cortes propios 60/40 — NO los de bandFor). */
function esgTone(band: string): Tone {
  const b = band.toLowerCase();
  if (b.startsWith("alt")) return "ok"; // Alta resiliencia
  if (b.startsWith("mod")) return "warn"; // Moderada
  return "alert"; // Baja
}

/** Banda coloreada por eje. El tono debe respetar la dirección y los cortes del
 * eje: IRMP es riesgo (riskBandFor, cuyos cortes coinciden con la banda del
 * modelo); ESG trae banda propia con cortes distintos (tono desde su string); el
 * resto no trae banda del modelo → bandFor da label y tono consistentes. */
function bandOf(axis: BriefAxis): Band | null {
  if (axis.score == null) return null;
  if (axis.eje === IRMP_EJE) {
    const b = riskBandFor(axis.score);
    return { label: axis.band ?? b.label, tone: b.tone };
  }
  if (axis.eje === ESG_EJE && axis.band) {
    return { label: axis.band, tone: esgTone(axis.band) };
  }
  const b = bandFor(axis.score);
  return { label: axis.band ?? b.label, tone: b.tone };
}

function dirTone(direction?: string): Tone {
  if (direction === "favorable") return "ok";
  if (direction === "adverso") return "alert";
  return "muted";
}
function DirIcon({ direction }: { direction?: string }) {
  if (direction === "favorable") return <TrendingUp className="w-3.5 h-3.5 text-ok" />;
  if (direction === "adverso") return <TrendingDown className="w-3.5 h-3.5 text-alert" />;
  return <Minus className="w-3.5 h-3.5 text-faint" />;
}

/* ── Tile por eje ────────────────────────────────────────────────── */
function AxisTile({ axis }: { axis: BriefAxis }) {
  const { t } = useTranslation();
  if (!axis.available) {
    return (
      <Card className="flex flex-col">
        <div className="text-sm font-semibold text-ink truncate">{axis.eje}</div>
        <div className="flex-1 grid place-items-center py-4">
          <Chip tone="muted">{t("platform.marketBrief.noData")}</Chip>
        </div>
      </Card>
    );
  }

  const band = bandOf(axis);

  // Macro: factores con dirección (no tiene score único)
  if (axis.eje === "Macro & fiscal" && axis.detail?.factores) {
    const factores = (axis.detail.factores as Array<{ label: string; reading: string; direction: string }>).slice(0, 4);
    return (
      <Card className="flex flex-col">
        <div className="text-sm font-semibold text-ink truncate">{axis.eje}</div>
        <div className="text-xs text-muted mb-2">{axis.headline}</div>
        <div className="space-y-1.5">
          {factores.map((f, i) => (
            <div key={i} className="flex items-center gap-2">
              <DirIcon direction={f.direction} />
              <span className="text-xs text-body truncate flex-1">{f.label}</span>
              <Chip tone={dirTone(f.direction)}>{f.direction}</Chip>
            </div>
          ))}
        </div>
      </Card>
    );
  }

  // Sectorial: top / bottom (no tiene score único)
  if (axis.eje === "Sectorial" && axis.detail?.mas_atractivos) {
    const top = axis.detail.mas_atractivos as Array<{ sector: string; iai: number }>;
    const bot = axis.detail.menos_atractivos as Array<{ sector: string; iai: number }>;
    return (
      <Card className="flex flex-col">
        <div className="text-sm font-semibold text-ink truncate">{axis.eje}</div>
        <div className="text-xs text-muted mb-2">{axis.headline}</div>
        <div className="space-y-1">
          {top.slice(0, 2).map((s, i) => (
            <div key={`t${i}`} className="flex items-center justify-between gap-2 text-xs">
              <span className="flex items-center gap-1.5 truncate text-body">
                <TrendingUp className="w-3 h-3 text-ok shrink-0" /> {s.sector}
              </span>
              <span className="mono text-ink tabular-nums">{fmtNum(s.iai, 1)}</span>
            </div>
          ))}
          {bot.slice(-2).map((s, i) => (
            <div key={`b${i}`} className="flex items-center justify-between gap-2 text-xs">
              <span className="flex items-center gap-1.5 truncate text-body">
                <TrendingDown className="w-3 h-3 text-alert shrink-0" /> {s.sector}
              </span>
              <span className="mono text-ink tabular-nums">{fmtNum(s.iai, 1)}</span>
            </div>
          ))}
        </div>
      </Card>
    );
  }

  // Score-axes: número grande + banda
  return (
    <Card className="flex flex-col">
      <div className="text-sm font-semibold text-ink truncate">{axis.eje}</div>
      <div className="text-xs text-muted truncate">{axis.headline}</div>
      <div className="flex items-baseline gap-2 mt-2">
        <span className="font-display text-3xl font-extrabold text-ink mono tabular-nums">
          {axis.score == null ? "—" : fmtNum(axis.score, 1)}
        </span>
        {band && <Chip tone={band.tone}>{band.label}</Chip>}
      </div>
      {axis.score_label && <div className="text-[11px] text-faint mt-1">{axis.score_label}</div>}
    </Card>
  );
}

/* ── Página ──────────────────────────────────────────────────────── */
export function MarketBriefPage() {
  const { t, i18n } = useTranslation();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const [report, setReport] = useState<MarketBriefReport | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getMarketBrief());
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
      const res = await runMarketBrief();
      if (!res.started) {
        setBusy(false);
        return;
      }
      let ticks = 0;
      poll.current = window.setInterval(async () => {
        ticks += 1;
        try {
          const r = await getMarketBrief();
          if (r.computed && r.generated_at && r.generated_at !== before) {
            setReport(r);
            setBusy(false);
            stopPoll();
          } else if (ticks > 40) {
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

  const regenBtn = isAdmin && (
    <button onClick={regenerate} disabled={busy} className="btn btn-ghost !py-1.5">
      <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} />
      {busy ? t("platform.marketBrief.generating") : t("platform.marketBrief.regenerate")}
    </button>
  );

  const head = (
    <PageHead
      eyebrow={t("platform.marketBrief.eyebrow")}
      title={t("platform.marketBrief.title")}
      sub={t("platform.marketBrief.sub")}
      right={status === "ready" && report?.computed ? regenBtn : undefined}
    />
  );

  if (status === "loading")
    return (
      <div>
        {head}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <Skeleton className="h-64" />
      </div>
    );

  if (status === "error")
    return <div>{head}<StateBlock kind="error" message={t("platform.marketBrief.error")} /></div>;

  if (!report?.computed) {
    return (
      <div>
        {head}
        <StateBlock
          kind="empty"
          title={t("platform.marketBrief.emptyTitle")}
          message={isAdmin ? t("platform.marketBrief.emptyAdmin") : t("platform.marketBrief.emptyViewer")}
          action={isAdmin ? (
            <button onClick={regenerate} disabled={busy} className="btn btn-primary">
              <Sparkles className="w-4 h-4" />
              {busy ? t("platform.marketBrief.generating") : t("platform.marketBrief.generate")}
            </button>
          ) : undefined}
        />
      </div>
    );
  }

  const axes = report.snapshot?.axes ?? [];

  return (
    <div>
      {head}

      <div className="flex items-center justify-between gap-3 mb-3">
        <span className="text-xs text-muted">
          {report.snapshot?.pais} · {t("platform.marketBrief.axesWithData", { count: report.n_ejes_con_dato ?? axes.filter((a) => a.available).length })}
          {report.generated_at && <> · {t("platform.marketBrief.generatedAt", { date: fmtDate(report.generated_at, i18n.language) })}</>}
        </span>
      </div>

      {/* Pulso por eje */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-5">
        {axes.map((axis) => <AxisTile key={axis.eje} axis={axis} />)}
      </div>

      {/* Brief narrativo */}
      <Card>
        <CardHead
          icon={Sparkles}
          title={t("platform.marketBrief.briefTitle")}
          subtitle={t("platform.marketBrief.briefSubtitle")}
        />
        <AiInsightBody
          loading={false}
          ai={report.brief ?? null}
          unavailableHint={t("platform.marketBrief.unavailable")}
        />
      </Card>
    </div>
  );
}
