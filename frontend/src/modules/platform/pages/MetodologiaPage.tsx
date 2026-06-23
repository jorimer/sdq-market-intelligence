import { useEffect, useState } from "react";
import { useTranslation, Trans } from "react-i18next";
import type { TFunction } from "i18next";
import {
  BookOpen,
  Database,
  ShieldCheck,
  Scale,
  Sparkles,
  AlertTriangle,
} from "lucide-react";
import client from "@/shared/api/client";
import {
  PageHead,
  Card,
  CardHead,
  Chip,
  StateBlock,
  Skeleton,
} from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";

/* ──────────────────────────────────────────────────────────────────
 * Metodología — documento vivo de doctrina de SDQ·MIP.
 * Contenido fiel (marco de gates, fuentes, doctrina anti-fabricación,
 * SCQA) + cifras reales tiradas de endpoints existentes (pesos,
 * backtests). Cero fabricación: lo que no está calculado se declara,
 * no se inventa.
 * ────────────────────────────────────────────────────────────────── */

/* Mapas de componentes para el texto enriquecido (Trans). */
const RICH_INK = {
  b: <span className="font-medium text-ink" />,
  i: <span className="italic" />,
  c: <span className="mono text-xs" />,
};
const RICH_MUTED = { b: <span className="font-medium text-muted" /> };

/* ── 1 · Marco de gates A–F (fuente: PLAN_MAESTRO §2) ─────────────── */
const GATE_LETTERS = ["a", "b", "c", "d", "e", "f"] as const;

/* ── 2 · Fuentes y madurez por eje (ground truth, §1) ────────────── */
type DataKind = "real" | "mixed" | "monitor";
const AXES: { n: number; kind: DataKind }[] = [
  { n: 1, kind: "real" },
  { n: 2, kind: "monitor" },
  { n: 3, kind: "mixed" },
  { n: 4, kind: "real" },
  { n: 5, kind: "real" },
  { n: 6, kind: "mixed" },
  { n: 7, kind: "real" },
];

function DataBadge({ kind, t }: { kind: DataKind; t: TFunction }) {
  if (kind === "real") return <Chip tone="ok">{t("platform.methodology.badgeReal")}</Chip>;
  if (kind === "monitor") return <Chip tone="accent">{t("platform.methodology.badgeMonitor")}</Chip>;
  return <Chip tone="warn">{t("platform.methodology.badgeMixed")}</Chip>;
}

/* ── Helpers de backtest ─────────────────────────────────────────── */
type CI = [number | null, number | null] | null | undefined;

/** Una señal es "significativa" solo si su IC bootstrap excluye el cero. */
function ciExcludesZero(ci: CI): boolean {
  if (!ci || ci[0] == null || ci[1] == null) return false;
  return (ci[0] > 0 && ci[1] > 0) || (ci[0] < 0 && ci[1] < 0);
}
function fmtCI(ci: CI, digits = 2): string {
  if (!ci || ci[0] == null || ci[1] == null) return "—";
  return `${fmtNum(ci[0], digits)} … ${fmtNum(ci[1], digits)}`;
}

interface VRow {
  axis: string;
  source: string;
  metric: string;
  value: string;
  ci: string;
  n: string;
  sig: boolean | null; // null → no calculado / no aplica
  verdict: string;
}

function notCalc(t: TFunction, base: Pick<VRow, "axis" | "source" | "metric">): VRow {
  return { ...base, value: "—", ci: "—", n: "—", sig: null, verdict: t("platform.methodology.validation.vNotCalc") };
}

const V = (k: string) => `platform.methodology.validation.${k}`;

/* eslint-disable @typescript-eslint/no-explicit-any */
function mapBanking(t: TFunction, d: any): VRow {
  const base = { axis: t("platform.methodology.axes.n1Name"), source: t(V("mBankingSource")), metric: t(V("mBankingMetric")) };
  if (!d || !d.computed || d.ok === false || d.gini == null) return notCalc(t, base);
  const sig = ciExcludesZero(d.gini_ci);
  return { ...base, value: fmtNum(d.gini, 3), ci: fmtCI(d.gini_ci), n: `${t(V("obs"), { n: fmtNum(d.n_observations, 0) })} · ${t(V("events"), { n: d.n_events })}`, sig, verdict: sig ? t(V("vSignificant")) : t(V("vDirectional")) };
}
function mapIrmp(t: TFunction, d: any): VRow {
  const base = { axis: t("platform.methodology.axes.n4Name"), source: t(V("mIrmpSource")), metric: t(V("mIrmpMetric")) };
  const g = d?.governance;
  if (!d?.has_report || !g || g.gini == null) return notCalc(t, base);
  const sig = ciExcludesZero(g.gini_ci);
  return { ...base, value: fmtNum(g.gini, 3), ci: fmtCI(g.gini_ci), n: `${t(V("obs"), { n: fmtNum(g.n_observations, 0) })} · ${t(V("countries"), { n: d.n_countries ?? "—" })}`, sig, verdict: sig ? t(V("vSignificant")) : t(V("vDirectional")) };
}
function mapSector(t: TFunction, d: any): VRow {
  const base = { axis: t("platform.methodology.axes.n3Name"), source: t(V("mSectorSource")), metric: t(V("mSectorMetric")) };
  if (!d?.has_report || d?.has_data === false || d?.mean_yearly_ic == null) return notCalc(t, base);
  const sig = ciExcludesZero(d.ic_ci);
  return { ...base, value: fmtNum(d.mean_yearly_ic, 2), ci: fmtCI(d.ic_ci), n: `${t(V("obs"), { n: fmtNum(d.n_observations, 0) })} · ${t(V("years"), { n: d.n_years ?? "—" })}`, sig, verdict: sig ? t(V("vSignificant")) : t(V("vInconclusivePower")) };
}
function mapSocial(t: TFunction, d: any): VRow {
  const base = { axis: t("platform.methodology.axes.n6Name"), source: t(V("mSocialSource")), metric: t(V("mSocialMetric")) };
  if (!d || d.spearman == null) return notCalc(t, base);
  const sig = ciExcludesZero(d.spearman_ci);
  return { ...base, value: fmtNum(d.spearman, 2), ci: fmtCI(d.spearman_ci), n: t(V("regions"), { n: d.n_regions ?? "—" }), sig, verdict: sig ? t(V("vSignificant")) : t(V("vDirectional")) };
}
function mapTrade(t: TFunction, d: any): VRow {
  const base = { axis: t("platform.methodology.axes.n5Name"), source: t(V("mTradeSource")), metric: t(V("mTradeMetric")) };
  const ec = d?.export_collapse;
  if (!d?.has_report || !ec || ec.gini == null) return notCalc(t, base);
  const sig = ciExcludesZero(ec.gini_ci);
  return { ...base, value: fmtNum(ec.gini, 3), ci: fmtCI(ec.gini_ci), n: `${t(V("obs"), { n: fmtNum(ec.n_observations, 0) })} · ${t(V("countries"), { n: d.n_countries ?? "—" })}`, sig, verdict: sig ? t(V("vSignificant")) : t(V("vDirectional")) };
}
function mapEsg(t: TFunction, d: any): VRow {
  const base = { axis: t("platform.methodology.axes.n7Name"), source: t(V("mEsgSource")), metric: t(V("mEsgMetric")) };
  if (!d?.computed || d.spearman == null) return notCalc(t, base);
  const sig = ciExcludesZero(d.spearman_ci);
  return { ...base, value: fmtNum(d.spearman, 2), ci: fmtCI(d.spearman_ci), n: t(V("countries"), { n: d.n_countries ?? "—" }), sig, verdict: sig ? t(V("vSignificant")) : t(V("vDirectional")) };
}
/* eslint-enable @typescript-eslint/no-explicit-any */

function macroRow(t: TFunction): VRow {
  return {
    axis: t("platform.methodology.axes.n2Name"),
    source: t(V("mMacroSource")),
    metric: t(V("mMacroMetric")),
    value: "—", ci: "—", n: "—", sig: null,
    verdict: t(V("vMonitor")),
  };
}

function VerdictChip({ sig, label }: { sig: boolean | null; label: string }) {
  const tone = sig === true ? "ok" : sig === false ? "warn" : "muted";
  return <Chip tone={tone}>{label}</Chip>;
}

/* ── 3 · Digest de validación (backtest honesto) ─────────────────── */
function ValidationDigest() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<VRow[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    Promise.allSettled([
      client.get("/banking-score/validation/backtest"),
      client.get("/macro-political-risk/validation/backtest"),
      client.get("/sector-intel/validation"),
      client.get("/social-dev/validation/convergent"),
      client.get("/trade-intel/validation/backtest"),
      client.get("/esg-climate/backtest"),
    ])
      .then(([bank, irmp, sector, social, trade, esg]) => {
        const get = (r: PromiseSettledResult<{ data: unknown }>) =>
          r.status === "fulfilled" ? r.value.data : null;
        const out: VRow[] = [
          mapBanking(t, get(bank)),
          macroRow(t),
          mapSector(t, get(sector)),
          mapIrmp(t, get(irmp)),
          mapTrade(t, get(trade)),
          mapSocial(t, get(social)),
          mapEsg(t, get(esg)),
        ];
        setRows(out);
        // Solo es error si TODO falló (ninguna llamada resolvió).
        const anyOk = [bank, irmp, sector, social, trade, esg].some((r) => r.status === "fulfilled");
        setStatus(anyOk ? "ready" : "error");
      })
      .catch(() => setStatus("error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card>
      <CardHead
        icon={ShieldCheck}
        title={t("platform.methodology.validation.title")}
        subtitle={t("platform.methodology.validation.subtitle")}
      />

      <div className="mb-4 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">{t("platform.methodology.validation.warnLead")}</span>{" "}
          <Trans i18nKey="platform.methodology.validation.warnBody" components={RICH_INK} />
        </p>
      </div>

      {status === "loading" ? (
        <div className="space-y-2">
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
        </div>
      ) : status === "error" ? (
        <StateBlock kind="error" message={t("platform.methodology.validation.error")} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-line">
                <th className="py-2 px-2 font-medium">{t("platform.methodology.colAxis")}</th>
                <th className="py-2 px-2 font-medium">{t("platform.methodology.validation.colMetric")}</th>
                <th className="py-2 px-2 font-medium text-right">{t("platform.methodology.validation.colValue")}</th>
                <th className="py-2 px-2 font-medium text-right">{t("platform.methodology.validation.colCi")}</th>
                <th className="py-2 px-2 font-medium">{t("platform.methodology.validation.colSample")}</th>
                <th className="py-2 px-2 font-medium text-right">{t("platform.methodology.validation.colVerdict")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.axis} className="border-b border-line/60 align-top">
                  <td className="py-2.5 px-2">
                    <div className="text-ink font-medium">{r.axis}</div>
                    <div className="text-xs text-faint">{r.source}</div>
                  </td>
                  <td className="py-2.5 px-2 text-body min-w-[10rem]">{r.metric}</td>
                  <td className="py-2.5 px-2 text-right mono text-ink tabular-nums">{r.value}</td>
                  <td className="py-2.5 px-2 text-right mono text-body tabular-nums whitespace-nowrap">{r.ci}</td>
                  <td className="py-2.5 px-2 text-xs text-muted">{r.n}</td>
                  <td className="py-2.5 px-2 text-right">
                    <VerdictChip sig={r.sig} label={r.verdict} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* ── 4 · Pesos por índice (doctrina versionada) ──────────────────── */
interface WeightBlock {
  axis: string;
  direction: string;
  weights: Record<string, number>;
}

function prettify(t: TFunction, key: string): string {
  return t(`platform.methodology.weights.keys.${key}`, { defaultValue: key.replace(/_/g, " ") });
}

function WeightCard({ block, t }: { block: WeightBlock; t: TFunction }) {
  const entries = Object.entries(block.weights);
  const total = entries.reduce((s, [, w]) => s + w, 0) || 1;
  return (
    <Card>
      <CardHead icon={BookOpen} title={block.axis} subtitle={block.direction} />
      <div className="space-y-2.5">
        {entries.map(([k, w]) => (
          <div key={k} className="flex items-center gap-3">
            <span className="w-40 shrink-0 text-sm text-ink truncate">{prettify(t, k)}</span>
            <div className="flex-1 h-2 rounded-full bg-surface2 overflow-hidden">
              <div className="h-full rounded-full bg-accent" style={{ width: `${(w / total) * 100}%` }} />
            </div>
            <span className="shrink-0 mono text-sm font-semibold text-ink w-12 text-right tabular-nums">
              {Math.round(w * 100)}%
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

const W = (k: string) => `platform.methodology.weights.${k}`;

function WeightsSection() {
  const { t } = useTranslation();
  const [blocks, setBlocks] = useState<WeightBlock[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    Promise.allSettled([
      client.get("/banking-score/weights"),
      client.get("/macro-political-risk/weights"),
      client.get("/sector-intel/weights"),
      client.get("/social-dev/weights"),
      client.get("/esg-climate/weights"),
    ])
      .then(([bank, irmp, sector, social, esg]) => {
        const out: WeightBlock[] = [];
        if (bank.status === "fulfilled")
          out.push({ axis: t(W("bankAxis")), direction: t(W("bankDir")), weights: bank.value.data.weights });
        if (irmp.status === "fulfilled")
          out.push({ axis: t(W("irmpAxis")), direction: t(W("irmpDir")), weights: irmp.value.data.dimension_weights });
        if (sector.status === "fulfilled") {
          out.push({ axis: t(W("iaiAxis")), direction: t(W("iaiDir")), weights: sector.value.data.iai_dimension_weights });
          out.push({ axis: t(W("sgpsAxis")), direction: t(W("sgpsDir")), weights: sector.value.data.sgps_weights });
        }
        if (social.status === "fulfilled")
          out.push({ axis: t(W("socialAxis")), direction: t(W("socialDir")), weights: social.value.data.dimension_weights });
        if (esg.status === "fulfilled")
          out.push({ axis: t(W("esgAxis")), direction: t(W("esgDir")), weights: esg.value.data.dimension_weights });
        setBlocks(out);
        setStatus(out.length ? "ready" : "error");
      })
      .catch(() => setStatus("error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (status === "loading")
    return (
      <div className="grid lg:grid-cols-2 gap-5">
        <Skeleton className="h-56" />
        <Skeleton className="h-56" />
      </div>
    );
  if (status === "error")
    return <StateBlock kind="error" message={t("platform.methodology.weights.error")} />;

  return (
    <div className="grid lg:grid-cols-2 gap-5">
      {blocks.map((b) => <WeightCard key={b.axis} block={b} t={t} />)}
    </div>
  );
}

/* ── Sección con encabezado de doctrina ──────────────────────────── */
function SectionTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div className="mb-3">
      <h2 className="font-display text-lg font-bold text-ink">{children}</h2>
      {hint && <p className="text-sm text-muted mt-0.5 max-w-2xl">{hint}</p>}
    </div>
  );
}

/* ── Página ──────────────────────────────────────────────────────── */
export function MetodologiaPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-10">
      <PageHead
        eyebrow={t("platform.methodology.eyebrow")}
        title={t("platform.methodology.title")}
        sub={t("platform.methodology.sub")}
      />

      {/* 1 · Marco de gates A–F */}
      <section>
        <SectionTitle hint={t("platform.methodology.secGatesHint")}>
          {t("platform.methodology.secGatesTitle")}
        </SectionTitle>
        <Card>
          <div className="grid md:grid-cols-2 gap-x-8 gap-y-4">
            {GATE_LETTERS.map((g) => (
              <div key={g} className="flex items-start gap-3">
                <span className="shrink-0 grid place-items-center w-8 h-8 rounded-[9px] bg-accent-soft text-accent-ink font-display font-bold text-sm">
                  {g.toUpperCase()}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-ink">{t(`platform.methodology.gates.${g}Title`)}</div>
                  <p className="text-xs text-muted mt-0.5">{t(`platform.methodology.gates.${g}Desc`)}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </section>

      {/* 2 · Doctrina anti-fabricación */}
      <section>
        <SectionTitle hint={t("platform.methodology.secDoctrineHint")}>
          {t("platform.methodology.secDoctrineTitle")}
        </SectionTitle>
        <div className="grid lg:grid-cols-2 gap-5">
          <Card>
            <CardHead icon={Scale} title={t("platform.methodology.doctrine.card1Title")} />
            <p className="text-sm text-body">
              <Trans i18nKey="platform.methodology.doctrine.card1Body" components={RICH_INK} />
            </p>
            <ul className="mt-3 space-y-1.5 text-sm text-body list-disc pl-4">
              <li><Trans i18nKey="platform.methodology.doctrine.card1Li1" components={RICH_INK} /></li>
              <li><Trans i18nKey="platform.methodology.doctrine.card1Li2" components={RICH_INK} /></li>
              <li><Trans i18nKey="platform.methodology.doctrine.card1Li3" components={RICH_INK} /></li>
            </ul>
          </Card>
          <Card>
            <CardHead icon={ShieldCheck} title={t("platform.methodology.doctrine.card2Title")} />
            <p className="text-sm text-body">
              <Trans i18nKey="platform.methodology.doctrine.card2Body" components={RICH_INK} />
            </p>
            <p className="mt-3 text-sm text-body">
              {t("platform.methodology.doctrine.card2Body2")}
            </p>
          </Card>
        </div>
      </section>

      {/* 3 · Fuentes y madurez por eje */}
      <section>
        <SectionTitle hint={t("platform.methodology.secSourcesHint")}>
          {t("platform.methodology.secSourcesTitle")}
        </SectionTitle>
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-2 font-medium w-10">{t("platform.methodology.colNum")}</th>
                  <th className="py-2 px-2 font-medium">{t("platform.methodology.colAxis")}</th>
                  <th className="py-2 px-2 font-medium">{t("platform.methodology.colIndex")}</th>
                  <th className="py-2 px-2 font-medium">{t("platform.methodology.colSourceLive")}</th>
                  <th className="py-2 px-2 font-medium text-right">{t("platform.methodology.colData")}</th>
                </tr>
              </thead>
              <tbody>
                {AXES.map((a) => (
                  <tr key={a.n} className="border-b border-line/60">
                    <td className="py-2.5 px-2 mono text-faint tabular-nums">{a.n}</td>
                    <td className="py-2.5 px-2 text-ink font-medium">{t(`platform.methodology.axes.n${a.n}Name`)}</td>
                    <td className="py-2.5 px-2 text-body">{t(`platform.methodology.axes.n${a.n}Index`)}</td>
                    <td className="py-2.5 px-2 text-xs text-muted">{t(`platform.methodology.axes.n${a.n}Source`)}</td>
                    <td className="py-2.5 px-2 text-right"><DataBadge kind={a.kind} t={t} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-start gap-2 text-xs text-faint">
            <Database className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <p>
              <Trans i18nKey="platform.methodology.sourcesNote" components={RICH_MUTED} />
            </p>
          </div>
        </Card>
      </section>

      {/* 4 · Validación honesta */}
      <section>
        <SectionTitle hint={t("platform.methodology.secValidationHint")}>
          {t("platform.methodology.secValidationTitle")}
        </SectionTitle>
        <ValidationDigest />
      </section>

      {/* 5 · Pesos por índice */}
      <section>
        <SectionTitle hint={t("platform.methodology.secWeightsHint")}>
          {t("platform.methodology.secWeightsTitle")}
        </SectionTitle>
        <WeightsSection />
      </section>

      {/* 6 · Insight IA / SCQA */}
      <section>
        <SectionTitle hint={t("platform.methodology.secScqaHint")}>
          {t("platform.methodology.secScqaTitle")}
        </SectionTitle>
        <Card>
          <CardHead
            icon={Sparkles}
            title={t("platform.methodology.scqa.title")}
            subtitle={t("platform.methodology.scqa.subtitle")}
          />
          <div className="grid md:grid-cols-2 gap-x-8 gap-y-3 text-sm text-body">
            <p><Trans i18nKey="platform.methodology.scqa.p1" components={RICH_INK} /></p>
            <p><Trans i18nKey="platform.methodology.scqa.p2" components={RICH_INK} /></p>
          </div>
        </Card>
      </section>
    </div>
  );
}
