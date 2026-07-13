import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  StatTile,
  StateBlock,
  LoadingGrid,
  Chip,
  Tabs,
} from "@/shared/ui/primitives";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { InsurerDrillDrawer } from "../components/InsurerDrillDrawer";
import {
  getInsurancePulse,
  getInsuranceInsight,
  getInsuranceRankings,
  getArsRankings,
  pulseHasData,
  INSURANCE_AUDIENCES,
  ARS_CATEGORY_LABELS,
  InsurancePulse,
  InsuranceRankRow,
  ArsRankRow,
} from "../api";

type Status = "loading" | "error" | "ready";
type BandTone = "ok" | "accent" | "warn" | "alert" | "muted";

function bandTone(band: string | null): BandTone {
  switch (band) {
    case "Sólida": return "ok";
    case "Adecuada": return "accent";
    case "En vigilancia": return "warn";
    case "Frágil": return "alert";
    default: return "muted";
  }
}

/** Mix by ramo as a token-colored proportional bar list (design-compliant, no hex). */
function RamoMixTable({ pulse }: { pulse: InsurancePulse }) {
  const { t } = useTranslation();
  const mix = pulse.mix ?? [];
  const max = Math.max(...mix.map((m) => m.pct ?? 0), 1);
  return (
    <div className="space-y-2">
      {mix.map((m) => (
        <div key={m.ramo} className="flex items-center gap-3">
          <div className="w-40 shrink-0 truncate text-sm text-body">{m.label}</div>
          <div className="flex-1 min-w-0 h-2 rounded-full bg-surface2 overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{ width: `${((m.pct ?? 0) / max) * 100}%`, background: "var(--c1)" }}
            />
          </div>
          <div className="w-28 shrink-0 text-right mono tabular-nums text-sm text-ink">
            {fmtNum((m.amount ?? 0) / 1e9, 1)}
            <span className="text-muted ml-1 text-xs">{t("insurance.mmm")}</span>
          </div>
          <div className="w-14 shrink-0 text-right mono tabular-nums text-sm text-muted">
            {fmtPct(m.pct, 1)}
          </div>
        </div>
      ))}
    </div>
  );
}

/** SFS health-coverage card (SISALRIL/CNSS). Rendered even when the SIS market
 * series are not ingested yet — the two datasets have independent syncs. */
function HealthCoverageCard({ pulse }: { pulse: InsurancePulse }) {
  const { t } = useTranslation();
  const hc = pulse.health_coverage;
  if (!hc) return null;
  return (
    <Card>
      <CardHead
        title={t("insurance.healthTitle")}
        subtitle={t("insurance.healthSub", { period: hc.period ?? "" })}
      />
      <div className="grid grid-cols-3 gap-4 mt-3">
        <StatTile label={t("insurance.total")} value={fmtNum((hc.afiliados_total ?? 0) / 1e6, 2)} unit="MM" />
        <StatTile label={t("insurance.contributivo")} value={fmtNum((hc.afiliados_contributivo ?? 0) / 1e6, 2)} unit="MM" />
        <StatTile label={t("insurance.subsidiado")} value={fmtNum((hc.afiliados_subsidiado ?? 0) / 1e6, 2)} unit="MM" />
      </div>
    </Card>
  );
}

function MarketTab({ pulse }: { pulse: InsurancePulse }) {
  const { t } = useTranslation();
  const [audience, setAudience] = useAudiencePref("sdq.insurance.audience", INSURANCE_AUDIENCES);
  const hc = pulse.health_coverage;
  const gy = pulse.growth_years;

  // El pulse de mercado (SIS) y la cobertura de salud (SISALRIL) tienen syncs
  // INDEPENDIENTES: sin primas ingeridas se muestra el vacío del mercado, pero la
  // tarjeta de salud se pinta igual si su dato existe (antes quedaba oculta).
  if (!pulseHasData(pulse)) {
    return (
      <div className="space-y-5">
        <StateBlock kind="empty" message={t("insurance.emptyMsg")} />
        <HealthCoverageCard pulse={pulse} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile
          label={t("insurance.premiums")}
          value={fmtNum((pulse.total_premiums_rd ?? 0) / 1e9, 1)}
          unit={`RD$ ${t("insurance.mmm")} · ${pulse.latest_year ?? ""}`}
        />
        <StatTile
          label={gy ? t("insurance.growthSpan", { from: gy[0], to: gy[1] }) : t("insurance.growth")}
          value={pulse.growth_pct == null ? "—" : `${fmtNum(pulse.growth_pct, 1)}%`}
        />
        <StatTile
          label={t("insurance.activeInsurers")}
          value={pulse.active_insurers ?? "—"}
        />
        <StatTile
          label={t("insurance.healthCoverage")}
          value={hc?.afiliados_total == null ? "—" : fmtNum(hc.afiliados_total / 1e6, 2)}
          unit={hc?.afiliados_total == null ? undefined : `${t("insurance.millions")} · ${hc.period ?? ""}`}
        />
      </div>

      <Card>
        <CardHead
          icon={ShieldCheck}
          title={t("insurance.mixTitle")}
          subtitle={t("insurance.mixSub", { pct: fmtPct(pulse.top4_concentration_pct, 1) })}
        />
        <div className="mt-3">
          <RamoMixTable pulse={pulse} />
        </div>
        {pulse.data_caveat && (
          <div className="mt-4">
            <Chip tone="muted">{pulse.data_caveat}</Chip>
          </div>
        )}
      </Card>

      <HealthCoverageCard pulse={pulse} />

      <AiInsightCard
        title={t("insurance.insightTitle")}
        subtitle={t("insurance.insightSubtitle", { period: pulse.period ?? "" })}
        depsKey={`${pulse.period ?? "insurance"}:${audience}`}
        fetcher={() => getInsuranceInsight(audience)}
        deepFetcher={(deep) => getInsuranceInsight(audience, deep)}
        actions={
          <AudienceTabs
            value={audience}
            onChange={setAudience}
            options={INSURANCE_AUDIENCES}
            labelPrefix="insurance.audience"
            ariaLabelKey="insurance.audienceLabel"
          />
        }
      />
    </div>
  );
}

function IsfTab({
  rows, note, onSelect,
}: { rows: InsuranceRankRow[]; note: string | null; onSelect: (r: InsuranceRankRow) => void }) {
  const { t } = useTranslation();
  if (!rows.length) {
    return (
      <StateBlock
        kind="empty"
        title={t("insurance.isfEmptyTitle")}
        message={note ?? t("insurance.isfEmpty")}
      />
    );
  }
  return (
    <Card>
      <CardHead
        title={t("insurance.isfTitle")}
        subtitle={t("insurance.isfSub")}
      />
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-line">
              <th scope="col" className="py-2 pr-3 font-medium">#</th>
              <th scope="col" className="py-2 pr-3 font-medium">{t("insurance.insurer")}</th>
              <th scope="col" className="py-2 pr-3 font-medium text-right">ISF</th>
              <th scope="col" className="py-2 pr-3 font-medium">{t("insurance.band")}</th>
              <th scope="col" className="py-2 pr-3 font-medium text-right">{t("insurance.coverage")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.slug}
                className="border-b border-line/60 cursor-pointer hover:bg-surface2/60 transition-colors"
                onClick={() => onSelect(r)}
              >
                <td className="py-2 pr-3 mono tabular-nums text-muted">{r.rank}</td>
                <td className="py-2 pr-3 text-ink truncate max-w-[16rem]">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onSelect(r); }}
                    className="text-left hover:underline focus-visible:underline"
                  >
                    {r.name ?? r.slug.replace(/_/g, " ")}
                  </button>
                </td>
                <td className="py-2 pr-3 text-right mono tabular-nums font-semibold text-ink">
                  {fmtNum(r.overall_score, 1)}
                </td>
                <td className="py-2 pr-3">
                  <Chip tone={bandTone(r.band)}>{r.band ?? "—"}</Chip>
                </td>
                <td className="py-2 pr-3 text-right mono tabular-nums text-muted">
                  {fmtPct((r.coverage ?? 0) * 100, 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted mt-3">{t("insurance.drillHint")}</p>
    </Card>
  );
}

function ArsTab({
  rows, note, caveat, onSelect,
}: { rows: ArsRankRow[]; note: string | null; caveat: string; onSelect: (r: ArsRankRow) => void }) {
  const { t } = useTranslation();
  if (!rows.length) {
    return (
      <StateBlock
        kind="empty"
        title={t("insurance.arsEmptyTitle")}
        message={note ?? t("insurance.arsEmpty")}
      />
    );
  }
  return (
    <Card>
      <CardHead
        title={t("insurance.arsTitle")}
        subtitle={t("insurance.arsSub")}
      />
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-line">
              <th scope="col" className="py-2 pr-3 font-medium">#</th>
              <th scope="col" className="py-2 pr-3 font-medium">{t("insurance.ars")}</th>
              <th scope="col" className="py-2 pr-3 font-medium">{t("insurance.category")}</th>
              <th scope="col" className="py-2 pr-3 font-medium text-right">ISARS</th>
              <th scope="col" className="py-2 pr-3 font-medium">{t("insurance.band")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.slug}
                className="border-b border-line/60 cursor-pointer hover:bg-surface2/60 transition-colors"
                onClick={() => onSelect(r)}
              >
                <td className="py-2 pr-3 mono tabular-nums text-muted">{r.rank}</td>
                <td className="py-2 pr-3 text-ink">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onSelect(r); }}
                    className="text-left hover:underline focus-visible:underline"
                  >
                    {r.name}
                  </button>
                </td>
                <td className="py-2 pr-3 text-body">{ARS_CATEGORY_LABELS[String(r.category)] ?? "—"}</td>
                <td className="py-2 pr-3 text-right mono tabular-nums font-semibold text-ink">
                  {fmtNum(r.overall_score, 1)}
                </td>
                <td className="py-2 pr-3"><Chip tone={bandTone(r.band)}>{r.band ?? "—"}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted mt-3">{caveat}</p>
    </Card>
  );
}

export function InsuranceIntelPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [tab, setTab] = useState<string>("mercado");
  const [pulse, setPulse] = useState<InsurancePulse | null>(null);
  const [rankings, setRankings] = useState<{ rows: InsuranceRankRow[]; note: string | null }>({ rows: [], note: null });
  const [ars, setArs] = useState<{ rows: ArsRankRow[]; note: string | null; caveat: string }>({ rows: [], note: null, caveat: "" });
  const [drill, setDrill] = useState<{ slug: string; name: string; kind: "insurer" | "ars" } | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    // Tolerancia por-recurso (patrón canónico): un endpoint caído no tumba la
    // página entera — cada tab muestra su vacío; error total solo si TODO falla.
    const [p, r, a] = await Promise.all([
      getInsurancePulse().catch(() => null),
      getInsuranceRankings().catch(() => null),
      getArsRankings().catch(() => null),
    ]);
    if (!p && !r && !a) {
      setStatus("error");
      return;
    }
    setPulse(p ?? { has_data: false, period: null, source: "" });
    setRankings({ rows: r?.rankings ?? [], note: r?.note ?? null });
    setArs({ rows: a?.rankings ?? [], note: a?.note ?? null, caveat: a?.caveat ?? "" });
    setStatus("ready");
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHead
        eyebrow={t("insurance.eyebrow")}
        title={t("insurance.title")}
        sub={t("insurance.subtitle")}
      />

      {status === "loading" && <LoadingGrid />}
      {status === "error" && (
        <StateBlock
          kind="error"
          message={t("insurance.errorMsg")}
          action={
            <button type="button" onClick={load} className="btn btn-ghost">
              {t("insurance.retry")}
            </button>
          }
        />
      )}
      {status === "ready" && pulse && (
        <>
          <div className="mb-5">
            <Tabs
              tabs={[
                { id: "mercado", label: t("insurance.tabMarket") },
                { id: "solidez", label: t("insurance.tabIsf") },
                { id: "ars", label: t("insurance.tabArs") },
              ]}
              active={tab}
              onChange={setTab}
            />
          </div>
          {tab === "mercado" && <MarketTab pulse={pulse} />}
          {tab === "solidez" && (
            <IsfTab
              rows={rankings.rows}
              note={rankings.note}
              onSelect={(r) => setDrill({ slug: r.slug, name: r.name ?? r.slug.replace(/_/g, " "), kind: "insurer" })}
            />
          )}
          {tab === "ars" && (
            <ArsTab
              rows={ars.rows}
              note={ars.note}
              caveat={ars.caveat}
              onSelect={(r) => setDrill({ slug: r.slug, name: r.name, kind: "ars" })}
            />
          )}
        </>
      )}

      {drill && (
        <InsurerDrillDrawer
          slug={drill.slug}
          name={drill.name}
          kind={drill.kind}
          onClose={() => setDrill(null)}
        />
      )}
    </div>
  );
}
