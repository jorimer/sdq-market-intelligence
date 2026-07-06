import { useEffect, useState } from "react";
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
            <span className="text-muted ml-1 text-xs">{t("insurance.mmm", "MMM")}</span>
          </div>
          <div className="w-14 shrink-0 text-right mono tabular-nums text-sm text-muted">
            {fmtPct(m.pct, 1)}
          </div>
        </div>
      ))}
    </div>
  );
}

function MarketTab({ pulse }: { pulse: InsurancePulse }) {
  const { t } = useTranslation();
  const [audience, setAudience] = useAudiencePref("sdq.insurance.audience", INSURANCE_AUDIENCES);
  const hc = pulse.health_coverage;
  const gy = pulse.growth_years;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile
          label={t("insurance.premiums", "Primas netas cobradas")}
          value={fmtNum((pulse.total_premiums_rd ?? 0) / 1e9, 1)}
          unit={`RD$ ${t("insurance.mmm", "MMM")} · ${pulse.latest_year ?? ""}`}
        />
        <StatTile
          label={gy ? t("insurance.growthSpan", `Crecimiento ${gy[0]}–${gy[1]} (compuesto)`) : t("insurance.growth", "Crecimiento")}
          value={pulse.growth_pct == null ? "—" : `${fmtNum(pulse.growth_pct, 1)}%`}
        />
        <StatTile
          label={t("insurance.activeInsurers", "Aseguradoras activas")}
          value={pulse.active_insurers ?? "—"}
        />
        <StatTile
          label={t("insurance.healthCoverage", "Cobertura de salud (SFS)")}
          value={hc?.afiliados_total == null ? "—" : fmtNum(hc.afiliados_total / 1e6, 2)}
          unit={hc?.afiliados_total == null ? undefined : `${t("insurance.millions", "MM afiliados")} · ${hc.period ?? ""}`}
        />
      </div>

      <Card>
        <CardHead
          icon={ShieldCheck}
          title={t("insurance.mixTitle", "Mezcla del mercado por ramo")}
          subtitle={t("insurance.mixSub", `Concentración top-4: ${fmtPct(pulse.top4_concentration_pct, 1)} · fuente SIS`)}
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

      {hc && (
        <Card>
          <CardHead
            title={t("insurance.healthTitle", "Cobertura de salud · Seguro Familiar de Salud")}
            subtitle={t("insurance.healthSub", `SISALRIL / CNSS · ${hc.period ?? ""}`)}
          />
          <div className="grid grid-cols-3 gap-4 mt-3">
            <StatTile label={t("insurance.total", "Total afiliados")} value={fmtNum((hc.afiliados_total ?? 0) / 1e6, 2)} unit="MM" />
            <StatTile label={t("insurance.contributivo", "Contributivo")} value={fmtNum((hc.afiliados_contributivo ?? 0) / 1e6, 2)} unit="MM" />
            <StatTile label={t("insurance.subsidiado", "Subsidiado")} value={fmtNum((hc.afiliados_subsidiado ?? 0) / 1e6, 2)} unit="MM" />
          </div>
        </Card>
      )}

      <AiInsightCard
        title={t("insurance.insightTitle", "Lectura del mercado asegurador")}
        subtitle={t("insurance.insightSubtitle", `Período ${pulse.period ?? ""}`)}
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

function IsfTab({ rows, note }: { rows: InsuranceRankRow[]; note: string | null }) {
  const { t } = useTranslation();
  if (!rows.length) {
    return (
      <StateBlock
        kind="empty"
        title={t("insurance.isfEmptyTitle", "ISF pendiente")}
        message={note ?? t("insurance.isfEmpty", "Los estados financieros auditados no están ingeridos todavía.")}
      />
    );
  }
  return (
    <Card>
      <CardHead
        title={t("insurance.isfTitle", "Índice de Solidez de Aseguradora (ISF)")}
        subtitle={t("insurance.isfSub", "0-100 sobre estados financieros auditados · SIS")}
      />
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-line">
              <th className="py-2 pr-3 font-medium">#</th>
              <th className="py-2 pr-3 font-medium">{t("insurance.insurer", "Aseguradora")}</th>
              <th className="py-2 pr-3 font-medium text-right">ISF</th>
              <th className="py-2 pr-3 font-medium">{t("insurance.band", "Banda")}</th>
              <th className="py-2 pr-3 font-medium text-right">{t("insurance.coverage", "Cobertura")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.slug} className="border-b border-line/60">
                <td className="py-2 pr-3 mono tabular-nums text-muted">{r.rank}</td>
                <td className="py-2 pr-3 text-ink truncate max-w-[16rem]">{r.slug.replace(/_/g, " ")}</td>
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
    </Card>
  );
}

function ArsTab({ rows, note, caveat }: { rows: ArsRankRow[]; note: string | null; caveat: string }) {
  const { t } = useTranslation();
  if (!rows.length) {
    return (
      <StateBlock
        kind="empty"
        title={t("insurance.arsEmptyTitle", "ISARS pendiente")}
        message={note ?? t("insurance.arsEmpty", "La sincronización de ARS (BDFINAC) no se ha ejecutado.")}
      />
    );
  }
  return (
    <Card>
      <CardHead
        title={t("insurance.arsTitle", "Índice de Solidez de ARS (ISARS)")}
        subtitle={t("insurance.arsSub", "Administradoras de Riesgos de Salud · SISALRIL (BDFINAC)")}
      />
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-line">
              <th className="py-2 pr-3 font-medium">#</th>
              <th className="py-2 pr-3 font-medium">{t("insurance.ars", "ARS")}</th>
              <th className="py-2 pr-3 font-medium">{t("insurance.category", "Categoría")}</th>
              <th className="py-2 pr-3 font-medium text-right">ISARS</th>
              <th className="py-2 pr-3 font-medium">{t("insurance.band", "Banda")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.slug} className="border-b border-line/60">
                <td className="py-2 pr-3 mono tabular-nums text-muted">{r.rank}</td>
                <td className="py-2 pr-3 text-ink">{r.name}</td>
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

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [p, r, a] = await Promise.all([
          getInsurancePulse(),
          getInsuranceRankings(),
          // ARS is a newer surface; tolerate its absence so the page still renders.
          getArsRankings().catch(() => ({ rankings: [], note: null, caveat: "" })),
        ]);
        if (!alive) return;
        setPulse(p);
        setRankings({ rows: r.rankings, note: r.note });
        setArs({ rows: a.rankings, note: a.note, caveat: a.caveat });
        setStatus("ready");
      } catch {
        if (alive) setStatus("error");
      }
    })();
    return () => { alive = false; };
  }, []);

  return (
    <div>
      <PageHead
        eyebrow={t("insurance.eyebrow", "Seguros · SIS · SISALRIL")}
        title={t("insurance.title", "Seguros")}
        sub={t("insurance.subtitle", "Mercado asegurador dominicano: primas por ramo, solidez de aseguradoras (ISF) y cobertura de salud (SFS).")}
      />

      {status === "loading" && <LoadingGrid />}
      {status === "error" && (
        <StateBlock kind="error" message={t("insurance.errorMsg", "No se pudo cargar el mercado asegurador.")} />
      )}
      {status === "ready" && pulse && (
        <>
          <div className="mb-5">
            <Tabs
              tabs={[
                { id: "mercado", label: t("insurance.tabMarket", "Mercado") },
                { id: "solidez", label: t("insurance.tabIsf", "Solidez (ISF)") },
                { id: "ars", label: t("insurance.tabArs", "ARS (salud)") },
              ]}
              active={tab}
              onChange={setTab}
            />
          </div>
          {tab === "mercado" && (
            pulseHasData(pulse)
              ? <MarketTab pulse={pulse} />
              : <StateBlock kind="empty" message={t("insurance.emptyMsg", "Aún no hay dato de mercado ingerido. Ejecute la sincronización de seguros.")} />
          )}
          {tab === "solidez" && <IsfTab rows={rankings.rows} note={rankings.note} />}
          {tab === "ars" && <ArsTab rows={ars.rows} note={ars.note} caveat={ars.caveat} />}
        </>
      )}
    </div>
  );
}
