import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Target, Sparkles, Anchor, Database, Save, Upload, GraduationCap } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Chip,
  Gauge,
  StatTile,
  StateBlock,
  Skeleton,
} from "@/shared/ui/primitives";
import { AiInsightBody } from "@/shared/ui/AiInsightBody";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { bandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { useAuth } from "@/shared/auth/AuthContext";
import {
  scoreDeal, saveDeal, importDeals, getLearningCurve, DEAL_AUDIENCES,
  type DealScoreResult, type LearningCurve,
} from "../api";

/* ──────────────────────────────────────────────────────────────────
 * Deal Scoring — RÚBRICA DECLARADA (cold-start), anclada a los 7 ejes.
 * NO es un modelo entrenado: el score es un índice de cierre/atractivo, no una
 * probabilidad. El XGBoost del spec se activa cuando el dataset cosechado gane el
 * umbral de IC en CV. Badge honesto en cada resultado.
 * ────────────────────────────────────────────────────────────────── */

const DEAL_TYPES = ["capital_raise", "real_estate", "ma_valuation", "debt_portfolio", "venture", "financing", "advisory", "other"];
const SECTORS = ["real_estate", "tourism", "mining_energy", "technology", "fintech", "agriculture", "cpg", "other"];
const STAGES = ["initial", "due_diligence", "term_sheet", "legal"];

/** Etiqueta de driver traducida (fallback al key crudo si falta). */
function factorLabel(t: TFunction, key: string): string {
  return t(`platform.dealScoring.factors.${key}`, { defaultValue: key });
}

interface FormState {
  deal_name: string; deal_type: string; sector: string; country: string; deal_stage: string;
  deal_size_usd: string; equity_required_pct: string; promoter_track_record: string;
  financial_quality: string; market_validation: string; regulatory_readiness: string;
  days_since_first_contact: string;
}
const EMPTY: FormState = {
  deal_name: "", deal_type: "capital_raise", sector: "fintech", country: "DO", deal_stage: "due_diligence",
  deal_size_usd: "", equity_required_pct: "", promoter_track_record: "", financial_quality: "",
  market_validation: "", regulatory_readiness: "", days_since_first_contact: "",
};

function num(s: string): number | null {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : null;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-muted">{label}</span>
      {hint && <span className="text-[11px] text-faint ml-1">{hint}</span>}
      <div className="mt-1">{children}</div>
    </label>
  );
}

export function DealScoringPage() {
  const { t } = useTranslation();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const [form, setForm] = useState<FormState>(EMPTY);
  const [audience, setAudience] = useAudiencePref("sdq.deal.audience", DEAL_AUDIENCES);
  const [result, setResult] = useState<DealScoreResult | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [curve, setCurve] = useState<LearningCurve | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadCurve = () => getLearningCurve().then(setCurve).catch(() => setCurve(null));
  useEffect(() => { loadCurve(); }, []);

  const set = (k: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const harvest = async () => {
    setSavedMsg(null);
    try {
      const payload = {
        deal_name: form.deal_name || `Deal ${new Date().toISOString().slice(0, 10)}`,
        deal_type: form.deal_type, sector: form.sector,
        country: form.country.trim().toUpperCase(), deal_stage: form.deal_stage,
        deal_size_usd: num(form.deal_size_usd), equity_required_pct: num(form.equity_required_pct),
        promoter_track_record: num(form.promoter_track_record), financial_quality: num(form.financial_quality),
        market_validation: num(form.market_validation), regulatory_readiness: num(form.regulatory_readiness),
        days_since_first_contact: num(form.days_since_first_contact),
      };
      const r = await saveDeal(payload);
      setSavedMsg(t("platform.dealScoring.saved", { total: r.total }));
      loadCurve();
    } catch (e) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      setSavedMsg((e as any)?.response?.status === 409 ? t("platform.dealScoring.saveConflict") : t("platform.dealScoring.saveError"));
    }
  };

  const onImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportMsg(t("platform.dealScoring.importing"));
    try {
      const r = await importDeals(file);
      setImportMsg(t("platform.dealScoring.imported", { inserted: r.inserted, updated: r.updated, skipped: r.skipped, total: r.total }));
      loadCurve();
    } catch {
      setImportMsg(t("platform.dealScoring.importError"));
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const run = async (aud: string = audience) => {
    setStatus("loading");
    setResult(null);
    try {
      const r = await scoreDeal({
        deal_name: form.deal_name || "Sin nombre",
        deal_type: form.deal_type, sector: form.sector,
        country: form.country.trim().toUpperCase(), deal_stage: form.deal_stage,
        deal_size_usd: num(form.deal_size_usd), equity_required_pct: num(form.equity_required_pct),
        promoter_track_record: num(form.promoter_track_record), financial_quality: num(form.financial_quality),
        market_validation: num(form.market_validation), regulatory_readiness: num(form.regulatory_readiness),
        days_since_first_contact: num(form.days_since_first_contact), with_ai: true, audience: aud,
      });
      setResult(r);
      setStatus("idle");
    } catch {
      setStatus("error");
    }
  };

  const band = result ? bandFor(result.score) : null;
  const anchors = result ? Object.entries(result.anchor_sources) : [];

  return (
    <div>
      <PageHead
        eyebrow={t("platform.dealScoring.eyebrow")}
        title={t("platform.dealScoring.title")}
        sub={t("platform.dealScoring.sub")}
      />

      <div className="grid lg:grid-cols-2 gap-5">
        {/* Formulario */}
        <Card>
          <CardHead icon={Target} title={t("platform.dealScoring.formTitle")} subtitle={t("platform.dealScoring.formSubtitle")} />
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <Field label={t("platform.dealScoring.fName")}><input className="field w-full" value={form.deal_name} onChange={set("deal_name")} placeholder={t("platform.dealScoring.phName")} /></Field>
            </div>
            <Field label={t("platform.dealScoring.fType")}><select className="field w-full" value={form.deal_type} onChange={set("deal_type")}>{DEAL_TYPES.map((v) => <option key={v} value={v}>{v}</option>)}</select></Field>
            <Field label={t("platform.dealScoring.fSector")}><select className="field w-full" value={form.sector} onChange={set("sector")}>{SECTORS.map((v) => <option key={v} value={v}>{v}</option>)}</select></Field>
            <Field label={t("platform.dealScoring.fCountry")} hint={t("platform.dealScoring.hintIso")}><input className="field w-full" value={form.country} onChange={set("country")} placeholder="DO" /></Field>
            <Field label={t("platform.dealScoring.fStage")}><select className="field w-full" value={form.deal_stage} onChange={set("deal_stage")}>{STAGES.map((v) => <option key={v} value={v}>{v}</option>)}</select></Field>
            <Field label={t("platform.dealScoring.fSize")}><input className="field w-full" type="number" value={form.deal_size_usd} onChange={set("deal_size_usd")} placeholder="5000000" /></Field>
            <Field label={t("platform.dealScoring.fEquity")}><input className="field w-full" type="number" value={form.equity_required_pct} onChange={set("equity_required_pct")} placeholder="30" /></Field>
            <Field label={t("platform.dealScoring.fDays")}><input className="field w-full" type="number" value={form.days_since_first_contact} onChange={set("days_since_first_contact")} placeholder="45" /></Field>
            <div className="col-span-2 border-t border-line pt-3 mt-1">
              <p className="text-xs text-muted mb-2">{t("platform.dealScoring.analystSignals")}</p>
              <div className="grid grid-cols-2 gap-3">
                <Field label={t("platform.dealScoring.fPromoter")}><input className="field w-full" type="number" min={0} max={100} value={form.promoter_track_record} onChange={set("promoter_track_record")} placeholder={t("platform.dealScoring.phDash")} /></Field>
                <Field label={t("platform.dealScoring.fFinancial")}><input className="field w-full" type="number" min={0} max={100} value={form.financial_quality} onChange={set("financial_quality")} placeholder={t("platform.dealScoring.phDash")} /></Field>
                <Field label={t("platform.dealScoring.fMarket")} hint={t("platform.dealScoring.hintOrIai")}><input className="field w-full" type="number" min={0} max={100} value={form.market_validation} onChange={set("market_validation")} placeholder={t("platform.dealScoring.phAnchorIai")} /></Field>
                <Field label={t("platform.dealScoring.fRegulatory")} hint={t("platform.dealScoring.hintOrIrmp")}><input className="field w-full" type="number" min={0} max={100} value={form.regulatory_readiness} onChange={set("regulatory_readiness")} placeholder={t("platform.dealScoring.phAnchorIrmp")} /></Field>
              </div>
            </div>
          </div>
          <div className="mt-4">
            <button onClick={() => run()} disabled={status === "loading"} className="btn btn-primary">
              <Target className="w-4 h-4" /> {status === "loading" ? t("platform.dealScoring.scoring") : t("platform.dealScoring.scoreBtn")}
            </button>
          </div>
        </Card>

        {/* Resultado */}
        <div className="space-y-5">
          {status === "error" && <StateBlock kind="error" message={t("platform.dealScoring.scoreError")} />}
          {status === "loading" && <Skeleton className="h-64" />}
          {status === "idle" && !result && (
            <StateBlock kind="empty" message={t("platform.dealScoring.emptyResult")} />
          )}
          {result && band && (
            <>
              <Card className="flex flex-col items-center text-center">
                <Gauge score={result.score} band={band} size={130} />
                <div className="mt-3 flex items-center gap-2">
                  <Chip tone={band.tone}>{band.label}</Chip>
                  <Chip tone="muted">{t("platform.dealScoring.confidence", { level: result.confidence })}</Chip>
                </div>
                <div className="mt-3">
                  <Chip tone="warn">{t("platform.dealScoring.rubricBadge")}</Chip>
                </div>
                <p className="text-[11px] text-faint mt-2 max-w-xs">
                  {t("platform.dealScoring.componentsNote", { present: result.components_present, total: result.components_total })}
                </p>
                <button onClick={harvest} className="btn btn-ghost !py-1.5 mt-3">
                  <Save className="w-3.5 h-3.5" /> {t("platform.dealScoring.save")}
                </button>
                {savedMsg && <p className="text-xs text-muted mt-2">{savedMsg}</p>}
              </Card>

              {anchors.length > 0 && (
                <Card>
                  <CardHead icon={Anchor} title={t("platform.dealScoring.anchorsTitle")} subtitle={t("platform.dealScoring.anchorsSubtitle")} />
                  <div className="flex flex-wrap gap-2">
                    {anchors.map(([k, v]) => <Chip key={k} tone="accent">{v}</Chip>)}
                  </div>
                </Card>
              )}

              <Card>
                <CardHead icon={Target} title={t("platform.dealScoring.driversTitle")} subtitle={t("platform.dealScoring.driversSubtitle")} />
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-2 font-medium">{t("platform.dealScoring.colComponent")}</th>
                        <th className="py-2 px-2 font-medium">{t("platform.dealScoring.colSource")}</th>
                        <th className="py-2 px-2 font-medium text-right">{t("platform.dealScoring.colValue")}</th>
                        <th className="py-2 px-2 font-medium text-right">{t("platform.dealScoring.colContribution")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.key_factors.map((f) => (
                        <tr key={f.factor} className="border-b border-line/60">
                          <td className="py-2 px-2 text-ink">{factorLabel(t, f.factor)}</td>
                          <td className="py-2 px-2 text-xs text-muted">{f.source}</td>
                          <td className="py-2 px-2 text-right mono text-ink tabular-nums">{fmtNum(f.value, 1)}</td>
                          <td className="py-2 px-2 text-right mono text-body tabular-nums">{fmtNum(f.contribution, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <Card>
                <CardHead
                  icon={Sparkles}
                  title={t("platform.dealScoring.aiTitle")}
                  subtitle={t("platform.dealScoring.aiSubtitle")}
                  right={
                    <AudienceTabs
                      value={audience}
                      onChange={(a) => { setAudience(a); run(a); }}
                      options={DEAL_AUDIENCES}
                      labelPrefix="deal.audience"
                      ariaLabelKey="deal.audienceLabel"
                    />
                  }
                />
                <AiInsightBody
                  loading={false}
                  ai={result.ai_insight}
                  unavailableHint={t("platform.dealScoring.aiUnavailable")}
                />
              </Card>
            </>
          )}
        </div>
      </div>

      {/* Estado del modelo — curva de aprendizaje (rúbrica → entrenado) */}
      <div className="mt-5">
        <Card>
          <CardHead
            icon={GraduationCap}
            title={t("platform.dealScoring.modelTitle")}
            subtitle={t("platform.dealScoring.modelSubtitle")}
            right={isAdmin ? (
              <>
                <input ref={fileRef} type="file" accept=".csv" onChange={onImport} className="hidden" />
                <button onClick={() => fileRef.current?.click()} className="btn btn-ghost !py-1.5">
                  <Upload className="w-3.5 h-3.5" /> {t("platform.dealScoring.importCsv")}
                </button>
              </>
            ) : undefined}
          />
          {!curve ? (
            <Skeleton className="h-20" />
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-3">
                <StatTile label={t("platform.dealScoring.stState")} value={curve.status === "modelo" ? t("platform.dealScoring.stModel") : t("platform.dealScoring.stRubric")} />
                <StatTile label={t("platform.dealScoring.stLabels")} value={`${curve.n_labeled}`} />
                <StatTile label={t("platform.dealScoring.stExAnte")} value={`${curve.n_ex_ante}`} unit={t("platform.dealScoring.stExAnteUnit")} />
                <StatTile label={t("platform.dealScoring.stAuc")} value={curve.computed && curve.cv_auc != null ? fmtNum(curve.cv_auc, 3) : "—"} />
              </div>
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <Chip tone={curve.ready_for_model ? "ok" : "warn"}>
                  {curve.ready_for_model ? t("platform.dealScoring.modelViable") : t("platform.dealScoring.stillRubric")}
                </Chip>
                <Chip tone="muted">{t("platform.dealScoring.closedLost", { closed: curve.n_closed, lost: curve.n_lost })}</Chip>
                {curve.computed && curve.auc_ci?.[0] != null && (
                  <Chip tone="muted">
                    {t("platform.dealScoring.ciFloor", { lo: fmtNum(curve.auc_ci[0], 3), hi: fmtNum(curve.auc_ci[1], 3), floor: curve.graduation_floor })}
                  </Chip>
                )}
                <span className="text-xs text-faint flex items-center gap-1"><Database className="w-3 h-3" /> {t("platform.dealScoring.graduatesForward")}</span>
              </div>
              <p className="text-sm text-body">{curve.message}</p>
              {curve.caveats && (
                <ul className="mt-2 space-y-1 text-xs text-faint list-disc pl-4">
                  {curve.caveats.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              )}
              {curve.retrospective_diagnostic && (
                <div className="mt-3 rounded-lg border border-line bg-subtle/40 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip tone="warn">{t("platform.dealScoring.retroBadge")}</Chip>
                    <span className="text-xs text-muted tabular-nums">
                      {t("platform.dealScoring.retroAuc", { auc: fmtNum(curve.retrospective_diagnostic.cv_auc, 3) })}
                      {curve.retrospective_diagnostic.auc_ci?.[0] != null && (
                        <> · {t("platform.dealScoring.retroCi", { lo: fmtNum(curve.retrospective_diagnostic.auc_ci[0], 3), hi: fmtNum(curve.retrospective_diagnostic.auc_ci[1], 3) })}</>
                      )}
                      {" "}· N={curve.retrospective_diagnostic.n}
                    </span>
                  </div>
                  <p className="mt-1.5 text-xs text-faint">{curve.retrospective_diagnostic.note}</p>
                </div>
              )}
              {importMsg && <p className="text-xs text-muted mt-3">{importMsg}</p>}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
