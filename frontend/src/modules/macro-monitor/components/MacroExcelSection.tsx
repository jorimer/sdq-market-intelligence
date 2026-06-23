import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { FileSpreadsheet, Sparkles, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import { Card, CardHead, StatTile, Chip, StateBlock } from "@/shared/ui/primitives";
import { MacroCanonicalSection } from "./MacroCanonicalSection";
import { MacroCoverageSection } from "./MacroCoverageSection";
import { MacroCrosscheckSection } from "./MacroCrosscheckSection";
import {
  getExcelCatalog,
  ingestExcel,
  ExcelCatalog,
  ExcelIngestResult,
} from "../api";

const sectorLabel = (t: TFunction, key: string) => t(`datos.macro.sectors.${key}`, { defaultValue: key });

/** Console for the AI-native Excel ingestion engine: catalog coverage, a one-file
 * ingest (dry-run by default) and the extracted series with their validation. */
export function MacroExcelSection() {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<ExcelCatalog | null>(null);
  const [catStatus, setCatStatus] = useState<"loading" | "error" | "ready">("loading");
  const [key, setKey] = useState("");
  const [url, setUrl] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ExcelIngestResult | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    getExcelCatalog()
      .then((c) => {
        setCatalog(c);
        setCatStatus("ready");
      })
      .catch(() => setCatStatus("error"));
  }, []);

  const run = async () => {
    if (!key && !url) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const r = await ingestExcel({ key: key || undefined, url: url || undefined, dryRun });
      setResult(r);
    } catch (e: unknown) {
      const resp = (e as { response?: { status?: number; data?: { detail?: string } } })?.response;
      setError(
        resp?.status === 403
          ? t("datos.macro.adminRequired")
          : resp?.data?.detail || t("datos.macro.excel.ingestError"),
      );
    } finally {
      setBusy(false);
    }
  };

  const pickFeatured = (k: string) => {
    setKey(k);
    setUrl("");
  };

  return (
    <div className="space-y-5">
      {/* Primary: the curated canonical registry (what we actually keep) */}
      <MacroCanonicalSection />

      {/* Correctness: cross-check the canonical series against the live API */}
      <MacroCrosscheckSection />

      {/* ── Secondary: full-corpus discovery & diagnostics (708 archivos) ── */}
      <div className="pt-2">
        <h3 className="font-display text-sm font-bold text-ink">{t("datos.macro.excel.corpusTitle")}</h3>
        <p className="text-xs text-muted mt-0.5">
          {t("datos.macro.excel.corpusNote")}
        </p>
      </div>

      {/* Corpus-wide coverage report (batch runner) */}
      <MacroCoverageSection />

      {/* Catalog stats */}
      {catStatus === "error" ? (
        <StateBlock kind="error" message={t("datos.macro.excel.catalogError")} />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatTile label={t("datos.macro.excel.statFiles")} value={catalog?.total ?? 0} />
          <StatTile label={t("datos.macro.excel.statXls")} value={catalog?.by_ext?.[".xls"] ?? 0} />
          <StatTile label={t("datos.macro.excel.statXlsx")} value={catalog?.by_ext?.[".xlsx"] ?? 0} />
          <StatTile label={t("datos.macro.excel.statSectors")} value={catalog ? Object.keys(catalog.by_sector).length : 0} />
        </div>
      )}

      {catStatus === "ready" && catalog && (
        <Card>
          <CardHead
            icon={FileSpreadsheet}
            title={t("datos.macro.excel.coverageTitle")}
            subtitle={t("datos.macro.excel.coverageSub")}
          />
          <div className="flex flex-wrap gap-2">
            {Object.entries(catalog.by_sector)
              .sort((a, b) => b[1] - a[1])
              .map(([sector, n]) => (
                <span
                  key={sector}
                  className="inline-flex items-center gap-2 rounded-full bg-surface2 px-3 py-1 text-xs"
                >
                  <span className="text-body">{sectorLabel(t, sector)}</span>
                  <span className="mono tabular-nums text-ink font-semibold">{n}</span>
                </span>
              ))}
          </div>
        </Card>
      )}

      {/* Ingest */}
      <Card>
        <CardHead
          icon={Sparkles}
          title={t("datos.macro.excel.ingestTitle")}
          subtitle={t("datos.macro.excel.ingestSub")}
        />

        {catalog && catalog.featured.length > 0 && (
          <div className="mb-4">
            <div className="text-xs font-medium text-muted mb-2">{t("datos.macro.excel.featured")}</div>
            <div className="flex flex-wrap gap-2">
              {catalog.featured.map((f) => (
                <button
                  key={f.key}
                  onClick={() => pickFeatured(f.key)}
                  className={`rounded-full px-3 py-1 text-xs transition ${
                    key === f.key
                      ? "bg-accent-soft text-accent-ink ring-1 ring-accent/30"
                      : "bg-surface2 text-body hover:ring-1 hover:ring-line"
                  }`}
                  title={f.url}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="grid sm:grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="block text-xs font-medium text-muted mb-1">{t("datos.macro.excel.fileFromCatalog")}</span>
            <input
              className="field mono"
              placeholder="imae.xlsx"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                if (e.target.value) setUrl("");
              }}
            />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-muted mb-1">{t("datos.macro.excel.orUrl")}</span>
            <input
              className="field mono"
              placeholder="https://cdn.bancentral.gov.do/…"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (e.target.value) setKey("");
              }}
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-body cursor-pointer select-none">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            {t("datos.macro.excel.dryRun")}
          </label>
          <button onClick={run} disabled={busy || (!key && !url)} className="btn btn-primary">
            {busy ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            {busy ? t("datos.macro.excel.processing") : dryRun ? t("datos.macro.excel.analyze") : t("datos.macro.excel.ingestToSeries")}
          </button>
        </div>

        {error && <div className="mt-3 text-sm p-3 rounded-[10px] bg-alert-soft text-alert">{error}</div>}
      </Card>

      {/* Result */}
      {result && (
        <Card>
          <CardHead
            icon={result.validation_ok ? CheckCircle2 : AlertTriangle}
            title={result.file.split("/").pop() || result.file}
            subtitle={t("datos.macro.excel.inferredBy", { orientation: result.orientation, method: result.method, confidence: result.confidence })}
            right={
              <Chip tone={result.validation_ok ? "ok" : "warn"}>
                {result.validation_ok ? t("datos.macro.excel.validationOk") : t("datos.macro.excel.withFlags")}
              </Chip>
            }
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <StatTile label={t("datos.macro.excel.statObs")} value={result.records} />
            <StatTile label={t("datos.macro.excel.statSeries")} value={result.series_count} />
            <StatTile label={t("datos.macro.excel.statMode")} value={result.dry_run ? t("datos.macro.excel.modeDryRun") : t("datos.macro.excel.modePersisted")} />
            <StatTile label={t("datos.macro.excel.statUpserted")} value={result.touched} />
          </div>

          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-1 font-medium">{t("datos.macro.excel.colSeries")}</th>
                  <th className="py-2 px-1 font-medium text-right">{t("datos.macro.excel.colObs")}</th>
                  <th className="py-2 px-1 font-medium">{t("datos.macro.excel.colRange")}</th>
                  <th className="py-2 px-1 font-medium">{t("datos.macro.excel.colStatus")}</th>
                </tr>
              </thead>
              <tbody>
                {result.series.map((s) => (
                  <tr key={s.code} className="border-b border-line/60 last:border-0 align-top">
                    <td className="py-2 px-1 mono text-[12px] text-ink">{s.code.split(".").slice(2).join(".")}</td>
                    <td className="py-2 px-1 text-right mono tabular-nums">{s.n_obs}</td>
                    <td className="py-2 px-1 mono text-body">
                      {s.period_min ?? "—"} → {s.period_max ?? "—"}
                    </td>
                    <td className="py-2 px-1">
                      {s.ok ? (
                        <Chip tone="ok">{t("datos.macro.excel.statusOk")}</Chip>
                      ) : (
                        <div className="flex flex-col gap-1">
                          {s.flags.map((f, i) => (
                            <Chip key={i} tone="warn">
                              {f}
                            </Chip>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!result.dry_run && (
            <p className="mt-3 text-xs text-muted">
              {t("datos.macro.excel.persistedNote")}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
