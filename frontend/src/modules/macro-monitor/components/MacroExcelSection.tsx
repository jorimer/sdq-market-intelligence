import { useEffect, useState } from "react";
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

const SECTOR_LABEL: Record<string, string> = {
  sector_real: "Sector real",
  precios: "Precios",
  sector_externo: "Sector externo",
  sector_monetario_financiero: "Monetario y financiero",
  sector_turismo: "Turismo",
  mercado_cambiario: "Mercado cambiario",
  mercado_de_trabajo: "Mercado de trabajo",
  sector_fiscal: "Fiscal",
  sistemas_de_pago: "Sistemas de pago",
};

/** Console for the AI-native Excel ingestion engine: catalog coverage, a one-file
 * ingest (dry-run by default) and the extracted series with their validation. */
export function MacroExcelSection() {
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
          ? "Requiere rol de administrador."
          : resp?.data?.detail || "No se pudo ingerir el Excel. Reintenta.",
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
        <h3 className="font-display text-sm font-bold text-ink">Inventario y diagnóstico del corpus</h3>
        <p className="text-xs text-muted mt-0.5">
          Los 708 Excel descubiertos y el barrido del motor — herramienta de descubrimiento y
          revisión, no el dato de producción (eso es el catálogo canónico de arriba).
        </p>
      </div>

      {/* Corpus-wide coverage report (batch runner) */}
      <MacroCoverageSection />

      {/* Catalog stats */}
      {catStatus === "error" ? (
        <StateBlock kind="error" message="No se pudo cargar el catálogo de Excel del BCRD." />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatTile label="Archivos en catálogo" value={catalog?.total ?? 0} />
          <StatTile label="Formato .xls" value={catalog?.by_ext?.[".xls"] ?? 0} />
          <StatTile label="Formato .xlsx" value={catalog?.by_ext?.[".xlsx"] ?? 0} />
          <StatTile label="Sectores" value={catalog ? Object.keys(catalog.by_sector).length : 0} />
        </div>
      )}

      {catStatus === "ready" && catalog && (
        <Card>
          <CardHead
            icon={FileSpreadsheet}
            title="Cobertura del catálogo"
            subtitle="Excel históricos del BCRD descubiertos, por sector"
          />
          <div className="flex flex-wrap gap-2">
            {Object.entries(catalog.by_sector)
              .sort((a, b) => b[1] - a[1])
              .map(([sector, n]) => (
                <span
                  key={sector}
                  className="inline-flex items-center gap-2 rounded-full bg-surface2 px-3 py-1 text-xs"
                >
                  <span className="text-body">{SECTOR_LABEL[sector] ?? sector}</span>
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
          title="Ingesta con el motor AI-native"
          subtitle="Infiere la estructura del Excel, extrae las series y las valida"
        />

        {catalog && catalog.featured.length > 0 && (
          <div className="mb-4">
            <div className="text-xs font-medium text-muted mb-2">Archivos cabecera</div>
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
            <span className="block text-xs font-medium text-muted mb-1">Archivo del catálogo</span>
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
            <span className="block text-xs font-medium text-muted mb-1">…o URL directa del CDN</span>
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
            Solo analizar (dry-run, no escribe en MacroSeries)
          </label>
          <button onClick={run} disabled={busy || (!key && !url)} className="btn btn-primary">
            {busy ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            {busy ? "Procesando…" : dryRun ? "Analizar" : "Ingerir a MacroSeries"}
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
            subtitle={`${result.orientation} · inferido por ${result.method} (confianza ${result.confidence})`}
            right={
              <Chip tone={result.validation_ok ? "ok" : "warn"}>
                {result.validation_ok ? "validación OK" : "con marcas"}
              </Chip>
            }
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <StatTile label="Observaciones" value={result.records} />
            <StatTile label="Series" value={result.series_count} />
            <StatTile label="Modo" value={result.dry_run ? "dry-run" : "persistido"} />
            <StatTile label="Upserted" value={result.touched} />
          </div>

          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-1 font-medium">Serie</th>
                  <th className="py-2 px-1 font-medium text-right">Obs.</th>
                  <th className="py-2 px-1 font-medium">Rango</th>
                  <th className="py-2 px-1 font-medium">Estado</th>
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
                        <Chip tone="ok">OK</Chip>
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
              Persistido bajo códigos <span className="mono">bcrd.xls.*</span>. El cruce contra el API
              y la alineación con las series canónicas llega en la siguiente fase.
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
