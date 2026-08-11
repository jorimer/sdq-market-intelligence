import { useState } from "react";
import { useTranslation } from "react-i18next";
import { GitCompare, Plus, X } from "lucide-react";
import { BankSelector } from "../components/BankSelector";
import { RadarChart } from "../components/RadarChart";
import { PerfilCompacto } from "../components/PerfilSDQ";
import { ScoreGauge } from "../components/ScoreGauge";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { PageHead, Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { useBankPeriods, evaluatePeriod, PeriodNoticeBox, type PeriodVerdict } from "../components/EntityPeriodNotice";
import { fmtNum } from "@/shared/lib/format";
import { useApp, periodToDate } from "@/shared/context/AppContext";
import {
  runScoring,
  getCompareInsight,
  ScoringResult,
  SUB_KEYS,
} from "../api";

const MAX = 4;

interface Slot {
  id: string;
  name: string;
}

export function ComparePage() {
  const { t } = useTranslation();
  const { period, periods } = useApp();
  const periodEnd = periodToDate(period);
  const [slots, setSlots] = useState<Slot[]>([{ id: "", name: "" }]);
  const [results, setResults] = useState<{ name: string; r: ScoringResult }[]>([]);
  const [comparedIds, setComparedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const valid = slots.filter((s) => s.id);

  // Per-entity period coverage: some entities may lack the global period (data not
  // yet loaded, or annual reporters). Flag them and block the compare until resolved.
  const { periodsOf } = useBankPeriods(valid.map((s) => s.id));
  const unavailable: { name: string; verdict: Extract<PeriodVerdict, { available: false }> }[] = [];
  for (const s of valid) {
    const p = periodsOf(s.id);
    if (p === undefined) continue; // still loading
    const v = evaluatePeriod(period, p, periods);
    if (!v.available) unavailable.push({ name: s.name, verdict: v });
  }
  const blocked = unavailable.length > 0;

  const run = async () => {
    if (valid.length < 2) return;
    setLoading(true);
    try {
      const rs = await Promise.all(valid.map((s) => runScoring(s.id, periodEnd)));
      setResults(rs.map((r, i) => ({ name: valid[i].name, r })));
      setComparedIds(valid.map((s) => s.id));
    } catch {
      setResults([]);
      setComparedIds([]);
    } finally {
      setLoading(false);
    }
  };

  const gridCols =
    results.length === 2 ? "grid-cols-2" : results.length === 3 ? "grid-cols-3" : "grid-cols-4";

  return (
    <div>
      <PageHead
        eyebrow={t("banking.cmpEyebrow")}
        title={t("banking.cmpTitle")}
        sub={t("banking.cmpSub")}
      />

      <Card className="mb-5">
        <p className="text-sm text-muted mb-3">{t("banking.cmpSelectPrompt")}</p>
        <div className="space-y-2.5 mb-4">
          {slots.map((slot, idx) => (
            <div key={idx} className="flex items-center gap-3">
              <div className="w-72">
                <BankSelector
                  value={slot.id}
                  onChange={(id, name) =>
                    setSlots((s) => s.map((v, i) => (i === idx ? { id, name } : v)))
                  }
                />
              </div>
              {slots.length > 1 && (
                <button
                  onClick={() => setSlots((s) => s.filter((_, i) => i !== idx))}
                  className="text-faint hover:text-alert"
                  title={t("banking.cmpRemoveTitle")}
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-4">
          {slots.length < MAX && (
            <button
              onClick={() => setSlots((s) => [...s, { id: "", name: "" }])}
              className="text-sm text-accent-ink hover:underline flex items-center gap-1"
            >
              <Plus className="w-3.5 h-3.5" /> {t("banking.cmpAddEntity")}
            </button>
          )}
          <div className="text-xs text-muted pb-2.5">
            {t("banking.scoringPeriod")} <span className="mono text-body">{periodEnd}</span>
          </div>
          <button onClick={run} disabled={valid.length < 2 || loading || blocked} className="btn btn-primary">
            <GitCompare className="w-4 h-4" />
            {loading ? t("banking.cmpComparing") : t("banking.cmpCompare")}
          </button>
        </div>
        {unavailable.map((u, i) => (
          <PeriodNoticeBox key={i} verdict={u.verdict} entityName={u.name} className="mt-3" />
        ))}
      </Card>

      {results.length === 0 ? (
        <StateBlock kind="empty" message={t("banking.cmpEmpty")} />
      ) : (
        <div className="space-y-5">
          <div className={`grid gap-4 ${gridCols}`}>
            {results.map(({ name, r }) => (
              <Card key={name} className="flex flex-col items-center text-center">
                <p className="text-sm text-ink mb-2 truncate w-full">{name}</p>
                <ScoreGauge score={r.overall_score} size={100} />
                <div className="mt-2"><PerfilCompacto ejecucion={r.ejecucion} bandaEjecucion={r.banda_ejecucion}
                    resiliencia={r.resiliencia} bandaResiliencia={r.banda_resiliencia} size="sm" /></div>
              </Card>
            ))}
          </div>

          <Card>
            <CardHead title={t("banking.cmpProfileTitle")} subtitle={t("banking.cmpProfileSubtitle")} />
            <RadarChart
              data={results[0].r.sub_components}
              comparisonData={results[1]?.r.sub_components}
              comparisonLabel={results[1]?.name}
            />
          </Card>

          <Card>
            <CardHead icon={GitCompare} title={t("banking.cmpDetailTitle")} />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted border-b border-line">
                    <th className="py-2 px-2 font-medium">{t("banking.cmpColSubcomponent")}</th>
                    {results.map(({ name }) => (
                      <th key={name} className="py-2 px-2 font-medium text-right truncate">{name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {SUB_KEYS.map((key) => (
                    <tr key={key} className="border-b border-line/60">
                      <td className="py-2 px-2 text-body">{t(`sub.${key}`)}</td>
                      {results.map(({ name, r }) => (
                        <td key={name} className="py-2 px-2 text-right mono text-ink">
                          {fmtNum(r.sub_components[key], 1)}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr className="border-t-2 border-line">
                    <td className="py-2 px-2 font-semibold text-ink">{t("banking.cmpScoreGeneral")}</td>
                    {results.map(({ name, r }) => (
                      <td key={name} className="py-2 px-2 text-right mono font-bold text-ink">
                        {fmtNum(r.overall_score, 1)}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          {comparedIds.length >= 2 && (
            <AiInsightCard
              title={t("banking.cmpInsightTitle")}
              subtitle={t("banking.cmpInsightSubtitle")}
              icon={GitCompare}
              depsKey={`${comparedIds.join("-")}|${periodEnd}`}
              fetcher={() => getCompareInsight(comparedIds, periodEnd)}
            />
          )}
        </div>
      )}
    </div>
  );
}
