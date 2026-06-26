import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Boxes, Lock, Eye, Download, Mail, FileText } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Chip,
  StateBlock,
  Skeleton,
} from "@/shared/ui/primitives";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { Markdown } from "@/shared/ui/Markdown";
import {
  getProductCatalog,
  getProductReport,
  getProductScopeOptions,
  downloadProductPdf,
  downloadProductSample,
  type ProductCatalog,
  type CatalogSector,
  type CatalogLevel,
  type ProductReport,
  type ScopeOption,
} from "../api";

/** Correo de contacto interino para el upsell (se reemplaza por el checkout en Fase B). */
const SALES_EMAIL = "ventas@sdqconsulting.com.do";

/** ¿El nivel necesita una entidad nombrada (Insight / Deep Dive)? */
function isNamed(tier: string): boolean {
  return tier === "insight" || tier === "deep_dive";
}

export function ProductCatalogPage() {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [viewing, setViewing] = useState<{ sector: CatalogSector; level: CatalogLevel } | null>(null);

  const load = () =>
    getProductCatalog()
      .then((c) => { setCatalog(c); setStatus("ready"); })
      .catch(() => setStatus("error"));

  useEffect(() => { load(); }, []);

  const planLabel = (tier: string) => t(`platform.catalog.plan.${tier}`, { defaultValue: tier });

  return (
    <div>
      <PageHead
        eyebrow={t("platform.catalog.eyebrow")}
        title={t("platform.catalog.title")}
        sub={t("platform.catalog.sub")}
      />

      {status === "loading" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
        </div>
      ) : status === "error" ? (
        <StateBlock kind="error" message={t("platform.catalog.loadError")} />
      ) : catalog && catalog.sectors.length > 0 ? (
        <>
          <p className="text-xs text-muted mb-4">
            {t("platform.catalog.yourPlan")}{" "}
            <Chip tone="ok">{planLabel(catalog.user_tier)}</Chip>
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {catalog.sectors.map((sector) => (
              <Card key={sector.sector_key}>
                <CardHead icon={Boxes} title={sector.display_name} />
                <div className="space-y-2">
                  {sector.levels.map((level) => (
                    <LevelRow
                      key={level.tier}
                      sector={sector}
                      level={level}
                      planLabel={planLabel}
                      onView={() => setViewing({ sector, level })}
                      onDownload={(scope) =>
                        downloadProductPdf(sector.sector_key, level.tier, scope ? { scope } : {})
                      }
                      onSampleDownloaded={load}
                      t={t}
                    />
                  ))}
                </div>
              </Card>
            ))}
          </div>
        </>
      ) : (
        <StateBlock kind="empty" message={t("platform.catalog.empty")} />
      )}

      {viewing && (
        <ProductReportDrawer
          sector={viewing.sector}
          level={viewing.level}
          onClose={() => setViewing(null)}
          t={t}
        />
      )}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function LevelRow({ sector, level, planLabel, onView, onDownload, onSampleDownloaded, t }: {
  sector: CatalogSector;
  level: CatalogLevel;
  planLabel: (tier: string) => string;
  onView: () => void;
  onDownload: (scope?: string) => void;
  onSampleDownloaded: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any;
}) {
  const [sampling, setSampling] = useState(false);
  const tierLabel = t(`platform.catalog.tier.${level.tier}`, { defaultValue: level.tier });

  const onSample = async () => {
    setSampling(true);
    try {
      await downloadProductSample(sector.sector_key, level.tier);
    } finally {
      setSampling(false);
      onSampleDownloaded(); // recarga: el botón desaparece (muestra ya gastada)
    }
  };
  const mailto = () => {
    const subject = encodeURIComponent(
      t("platform.catalog.mailSubject", { product: sector.display_name, level: tierLabel }));
    const body = encodeURIComponent(
      t("platform.catalog.mailBody", {
        product: sector.display_name, level: tierLabel, plan: planLabel(level.required_tier),
      }));
    window.location.href = `mailto:${SALES_EMAIL}?subject=${subject}&body=${body}`;
  };

  return (
    <div className="flex items-center gap-3 rounded-lg border border-line p-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-ink truncate">{tierLabel}</span>
          {level.price_band && <Chip tone="muted">{level.price_band}</Chip>}
          {level.staff_preview && (
            <Chip tone="warn">
              <Eye className="w-3 h-3" /> {t("platform.catalog.staffPreview")}
            </Chip>
          )}
        </div>
        <div className="text-[11px] text-faint truncate" title={level.audience}>{level.audience}</div>
      </div>
      {level.unlocked ? (
        <div className="flex items-center gap-1.5 shrink-0">
          <button onClick={onView} className="btn btn-ghost !py-1 !px-2 text-xs">
            <Eye className="w-3.5 h-3.5" /> {t("platform.catalog.view")}
          </button>
          {!isNamed(level.tier) && (
            <button onClick={() => onDownload()} className="btn btn-ghost !py-1 !px-2 text-xs">
              <Download className="w-3.5 h-3.5" /> {t("platform.catalog.download")}
            </button>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-end gap-1 shrink-0">
          <Chip tone="warn">
            <Lock className="w-3 h-3" /> {t("platform.catalog.requiresPlan", { plan: planLabel(level.required_tier) })}
          </Chip>
          {level.sample_available && (
            <button onClick={onSample} disabled={sampling} className="btn btn-ghost !py-1 !px-2 text-xs disabled:opacity-40">
              <FileText className="w-3.5 h-3.5" /> {t("platform.catalog.sample")}
            </button>
          )}
          <button onClick={mailto} className="btn btn-ghost !py-1 !px-2 text-xs">
            <Mail className="w-3.5 h-3.5" /> {t("platform.catalog.requestAccess")}
          </button>
        </div>
      )}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ProductReportDrawer({ sector, level, onClose, t }: {
  sector: CatalogSector;
  level: CatalogLevel;
  onClose: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any;
}) {
  const named = isNamed(level.tier);
  const [scope, setScope] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [options, setOptions] = useState<ScopeOption[]>([]);
  const [report, setReport] = useState<ProductReport | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">(named ? "idle" : "loading");
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const tierLabel = t(`platform.catalog.tier.${level.tier}`, { defaultValue: level.tier });

  const fetchReport = (s?: string) => {
    setStatus("loading");
    setErrMsg(null);
    getProductReport(sector.sector_key, level.tier, s ? { scope: s } : {})
      .then((r) => { setReport(r); setStatus("ready"); })
      .catch((e) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const detail = (e as any)?.response?.data?.detail;
        setErrMsg(typeof detail === "string" ? detail : t("platform.catalog.reportError"));
        setStatus("error");
      });
  };

  // Pulse (sin entidad) carga directo; los niveles nombrados esperan el scope y, si el
  // sector expone su universo, ofrecen un selector (en vez de obligar a escribir el nombre).
  useEffect(() => {
    if (!named) {
      fetchReport();
      return;
    }
    getProductScopeOptions(sector.sector_key)
      .then(setOptions)
      .catch(() => setOptions([])); // sin opciones → input libre (fallback)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Selección en dos pasos: primero el TIPO de entidad (de `group`), luego la entidad de
  // ese tipo. Tipos en orden de aparición; si las opciones no traen `group`, se cae a un
  // solo selector de entidad.
  const entityTypes = options.reduce<string[]>((acc, o) => {
    const g = o.group || "";
    if (g && !acc.includes(g)) acc.push(g);
    return acc;
  }, []);
  const hasTypes = entityTypes.length > 0;
  const entitiesForType = options.filter((o) => (o.group || "") === typeFilter);

  return (
    <InsightDrawerShell
      eyebrow={`${sector.display_name} · ${tierLabel}`}
      title={report?.entity_name || sector.display_name}
      onClose={onClose}
    >
      {named && status !== "ready" && (
        <form
          onSubmit={(e) => { e.preventDefault(); if (scope.trim()) fetchReport(scope.trim()); }}
          className="space-y-2"
        >
          <label className="text-xs text-muted block">{t("platform.catalog.scopeLabel")}</label>
          {options.length > 0 ? (
            <div className="space-y-2">
              {/* Paso 1: tipo de entidad (solo si las opciones traen tipo). */}
              {hasTypes && (
                <select
                  value={typeFilter}
                  onChange={(e) => { setTypeFilter(e.target.value); setScope(""); }}
                  className="field w-full"
                >
                  <option value="">{t("platform.catalog.typeSelectPlaceholder")}</option>
                  {entityTypes.map((g) => (
                    <option key={g} value={g}>{t(`banking.entityType.${g}`, g)}</option>
                  ))}
                </select>
              )}
              {/* Paso 2: entidad del tipo elegido (deshabilitado hasta elegir tipo). */}
              <div className="flex gap-2">
                <select
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                  disabled={hasTypes && !typeFilter}
                  className="field flex-1 disabled:opacity-50"
                >
                  <option value="">{t("platform.catalog.scopeSelectPlaceholder")}</option>
                  {(hasTypes ? entitiesForType : options).map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                <button type="submit" disabled={!scope.trim()} className="btn btn-primary shrink-0 disabled:opacity-40">
                  {t("platform.catalog.view")}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                placeholder={t("platform.catalog.scopePlaceholder")}
                className="field flex-1"
              />
              <button type="submit" disabled={!scope.trim()} className="btn btn-primary shrink-0 disabled:opacity-40">
                {t("platform.catalog.view")}
              </button>
            </div>
          )}
        </form>
      )}

      {status === "loading" && <Skeleton className="h-64" />}
      {status === "error" && <StateBlock kind="error" message={errMsg || t("platform.catalog.reportError")} />}

      {status === "ready" && report && (
        <>
          {report.commercial.staff_preview && (
            <div className="flex items-center gap-1.5 text-[11px] text-warn bg-warn-soft rounded-[8px] px-2.5 py-1.5">
              <Eye className="w-3.5 h-3.5 shrink-0" /> {t("platform.catalog.staffPreviewBanner")}
            </div>
          )}
          {report.commercial.watermark && (
            <p className="text-[11px] text-faint">{report.commercial.watermark}</p>
          )}
          {report.period && (
            <p className="text-xs text-muted">{t("platform.catalog.period", { v: report.period })}</p>
          )}
          {report.commercial.sections.map((sec) => {
            const text = report.narratives[sec];
            if (!text) return null;
            return (
              <div key={sec} className="space-y-1.5">
                <div className="text-[11px] uppercase tracking-wide text-faint">
                  {t(`platform.catalog.section.${sec}`, { defaultValue: sec.replace(/_/g, " ") })}
                </div>
                <Markdown text={text} />
              </div>
            );
          })}
          <div className="pt-2 border-t border-line">
            <button
              onClick={() => downloadProductPdf(sector.sector_key, level.tier, named && scope ? { scope } : {})}
              className="btn btn-ghost text-sm"
            >
              <Download className="w-4 h-4" /> {t("platform.catalog.download")}
            </button>
          </div>
        </>
      )}
    </InsightDrawerShell>
  );
}
