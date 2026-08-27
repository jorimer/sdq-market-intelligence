import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Boxes, Lock, Eye, Download, Mail, FileText, ShoppingCart } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Chip,
  StateBlock,
  Skeleton,
} from "@/shared/ui/primitives";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { VigilarButton } from "@/shared/ui/VigilarButton";
import { Markdown } from "@/shared/ui/Markdown";
import { useApp, periodToDate } from "@/shared/context/AppContext";
import { DimensionBars } from "../components/DimensionBars";
import { AportesAlCambio } from "../components/AportesAlCambio";
import {
  getProductCatalog,
  getProductReport,
  reportAportes,
  getProductScopeOptions,
  cierreDeEjercicio,
  esAbortada,
  getProductPeriods,
  downloadProductReport,
  downloadProductSample,
  reportDimensions,
  type ProductCatalog,
  type CatalogSector,
  type CatalogLevel,
  type ProductReport,
  type ScopeOption,
} from "../api";
import { checkoutOrder, checkoutSubscription } from "../billingApi";
import { CheckoutConfirmModal } from "../components/CheckoutConfirmModal";
import { mensajeDeError, pistaTecnica } from "../../../shared/api/errores";

/** Correo de contacto interino para el upsell (se reemplaza por el checkout en Fase B). */
const SALES_EMAIL = "ventas@sdqconsulting.com.do";

/** Dimensión de riesgo del ISA (pensiones) con los campos de retorno ajustado por riesgo
 * (Diferido B). Sólo la dim `riesgo` los trae, y sólo si hay serie NAV + TPM. */
interface RiskDim {
  key: string;
  raw?: number | null;
  sharpe?: number | null;
  annual_return_pct?: number | null;
  risk_free_pct?: number | null;
  vol_window_months?: number | null;
}

export function ProductCatalogPage() {
  const { t } = useTranslation();
  // El catálogo respeta el período global del topbar (antes salía siempre el último).
  const { period } = useApp();
  const periodEnd = periodToDate(period);
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
          periodEnd={periodEnd}
          onClose={() => setViewing(null)}
          t={t}
        />
      )}
    </div>
  );
}

function LevelRow({ sector, level, planLabel, onView, onSampleDownloaded, t }: {
  sector: CatalogSector;
  level: CatalogLevel;
  planLabel: (tier: string) => string;
  onView: () => void;
  onSampleDownloaded: () => void;
  t: TFunction;
}) {
  const [sampling, setSampling] = useState(false);
  const [buying, setBuying] = useState(false);
  const [buyErr, setBuyErr] = useState<string | null>(null);
  const [subInterval, setSubInterval] = useState<"monthly" | "annual">("monthly");
  // Confirmación de checkout (desglose + PayPal) antes de redirigir.
  const [confirm, setConfirm] = useState<null | { kind: "order" | "sub" }>(null);
  const tierLabel = t(`platform.catalog.tier.${level.tier}`, { defaultValue: level.tier });

  const payErr = (e: unknown) => {
    const code = (e as { response?: { status?: number } })?.response?.status;
    setBuyErr(code === 503
      ? t("platform.catalog.payUnavailable", { defaultValue: "Pagos en línea aún no disponibles." })
      : code === 400 ? t("platform.catalog.noPrice", { defaultValue: "Este producto aún no tiene precio." })
      : t("platform.catalog.payError", { defaultValue: "No se pudo iniciar el pago." }));
    setBuying(false);
    throw e as Error;  // el modal muestra su propio estado de error
  };
  // El pago pasa por el modal de confirmación (medio de pago PayPal + desglose + país + RNC).
  const onConfirmOrder = async (country: string, taxId?: string) => {
    setBuying(true); setBuyErr(null);
    try { window.location.href = (await checkoutOrder(`deep_dive:${sector.sector_key}`, country, taxId)).approval_url; }
    catch (e) { payErr(e); }
  };
  const onConfirmSubscribe = async (country: string, taxId?: string) => {
    setBuying(true); setBuyErr(null);
    try { window.location.href = (await checkoutSubscription(`insight:${sector.sector_key}`, subInterval, country, taxId)).approval_url; }
    catch (e) { payErr(e); }
  };

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
          {/* La descarga pasa SIEMPRE por el drawer (elige período/entidad antes de
              generar) — nunca con el período global del topbar. */}
          <button onClick={onView} className="btn btn-ghost !py-1 !px-2 text-xs">
            <Eye className="w-3.5 h-3.5" /> {t("platform.catalog.view")}
          </button>
          <button onClick={onView} className="btn btn-ghost !py-1 !px-2 text-xs">
            <Download className="w-3.5 h-3.5" /> {t("platform.catalog.download")}
          </button>
        </div>
      ) : (
        <div className="flex flex-col items-end gap-1 shrink-0">
          <Chip tone="warn">
            <Lock className="w-3 h-3" /> {t("platform.catalog.requiresPlan", { plan: planLabel(level.required_tier) })}
          </Chip>
          {level.tier === "deep_dive" ? (
            <>
              <button onClick={() => setConfirm({ kind: "order" })} disabled={buying} className="btn btn-primary !py-1 !px-2 text-xs disabled:opacity-40">
                <ShoppingCart className="w-3.5 h-3.5" /> {t("platform.catalog.buy", { defaultValue: "Comprar" })}
              </button>
              <span className="text-[10px] text-faint">{t("platform.catalog.plusTax", { defaultValue: "Precio + impuestos · pago con PayPal" })}</span>
            </>
          ) : level.tier === "insight" ? (
            <>
              <div className="flex items-center gap-1">
                <select className="field !py-0.5 !px-1 text-xs" value={subInterval}
                  onChange={(e) => setSubInterval(e.target.value as "monthly" | "annual")}>
                  <option value="monthly">{t("platform.catalog.monthly", { defaultValue: "Mensual" })}</option>
                  <option value="annual">{t("platform.catalog.annual", { defaultValue: "Anual" })}</option>
                </select>
                <button onClick={() => setConfirm({ kind: "sub" })} disabled={buying} className="btn btn-primary !py-1 !px-2 text-xs disabled:opacity-40">
                  <ShoppingCart className="w-3.5 h-3.5" /> {t("platform.catalog.subscribe", { defaultValue: "Suscribirme" })}
                </button>
              </div>
              <span className="text-[10px] text-faint">{t("platform.catalog.plusTaxSub", { defaultValue: "Suscripción + impuestos · pago con PayPal" })}</span>
            </>
          ) : null}
          {buyErr && <span className="text-[11px] text-alert max-w-[170px] text-right">{buyErr}</span>}
          {confirm && (
            <CheckoutConfirmModal
              sku={confirm.kind === "order" ? `deep_dive:${sector.sector_key}` : `insight:${sector.sector_key}`}
              interval={confirm.kind === "order" ? "once" : subInterval}
              title={`${sector.display_name} · ${tierLabel}`}
              subtitle={confirm.kind === "order" ? undefined : (subInterval === "monthly" ? "Suscripción mensual" : "Suscripción anual")}
              onConfirm={confirm.kind === "order" ? onConfirmOrder : onConfirmSubscribe}
              onClose={() => setConfirm(null)}
            />
          )}
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

function ProductReportDrawer({ sector, level, periodEnd, onClose, t }: {
  sector: CatalogSector;
  level: CatalogLevel;
  periodEnd: string;
  onClose: () => void;
  t: TFunction;
}) {
  // Pide entidad solo si el producto la necesita (banca); los de sujeto fijo cargan directo.
  const needsScope = level.requires_scope;
  // Rótulos según QUÉ se elige: "country" (país, panel: macro/ESG) o "entity" (banco).
  const isCountry = level.scope_kind === "country";
  const scopeLabel = t(isCountry ? "platform.catalog.scopeLabelCountry" : "platform.catalog.scopeLabel");
  const typePlaceholder = t(isCountry ? "platform.catalog.regionSelectPlaceholder" : "platform.catalog.typeSelectPlaceholder");
  const entityPlaceholder = t(isCountry ? "platform.catalog.countrySelectPlaceholder" : "platform.catalog.scopeSelectPlaceholder");
  const groupLabel = (g: string) =>
    isCountry ? t(`platform.catalog.region.${g}`, g) : t(`banking.entityType.${g}`, g);
  const [scope, setScope] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [options, setOptions] = useState<ScopeOption[]>([]);
  // Períodos REALES del producto (más reciente primero); "" = usa el período global del topbar.
  const [periods, setPeriods] = useState<string[]>([]);
  const [selPeriod, setSelPeriod] = useState("");
  const [activeScope, setActiveScope] = useState<string | undefined>(undefined);
  const [report, setReport] = useState<ProductReport | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">(needsScope ? "idle" : "loading");
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [errPista, setErrPista] = useState<string | null>(null);
  const tierLabel = t(`platform.catalog.tier.${level.tier}`, { defaultValue: level.tier });

  // Cada petición lleva su NÚMERO DE ORDEN y su abortador. Sin esto, cambiar de período
  // mientras un informe se genera encendía otra generación sin apagar la anterior: el
  // registro de producción mostró TRES corridas del mismo Deep Dive solapadas, lanzadas con
  // 22 y 47 s de diferencia, cada una de ~100 s. Se cobraron las tres y no se entregó
  // ninguna. Y la que volvía última escribía en pantalla aunque ya no fuera la pedida — así
  // apareció un cartel de error sobre un período que el usuario ya había abandonado.
  const nOrden = useRef(0);
  const enVuelo = useRef<AbortController | null>(null);

  // Al cerrar el drawer se aborta lo que quede en vuelo: nadie va a leer esa respuesta.
  useEffect(() => () => enVuelo.current?.abort(), []);

  const runReport = (p: string, s?: string) => {
    enVuelo.current?.abort();
    const abortador = new AbortController();
    enVuelo.current = abortador;
    const mio = ++nOrden.current;
    /** ¿Sigue siendo ésta la petición vigente? Si no, su respuesta NO toca la pantalla. */
    const vigente = () => mio === nOrden.current;

    setStatus("loading");
    setErrMsg(null);
    setErrPista(null);
    setActiveScope(s);
    getProductReport(sector.sector_key, level.tier,
      { period: p || periodEnd, ...(s ? { scope: s } : {}) }, abortador.signal)
      .then((r) => { if (vigente()) { setReport(r); setStatus("ready"); } })
      .catch((e) => {
        // Abortar es algo que hicimos NOSOTROS: no es un fallo y no lleva cartel.
        if (esAbortada(e) || !vigente()) return;
        // La PISTA va al lado del mensaje, no dentro: cuando el backend no manda motivo
        // —un corte del proxy, un fallo de red— el cartel genérico deja el diagnóstico en
        // cero, y «502» y «sin respuesta» se arreglan de maneras opuestas.
        setErrMsg(mensajeDeError(e, t("platform.catalog.reportError")));
        setErrPista(pistaTecnica(e));
        setStatus("error");
      });
  };
  // Submit del selector de entidad (banca) → usa el período elegido.
  const fetchReport = (s?: string) => runReport(selPeriod, s);

  // Cambio de período: re-carga si ya hay reporte (no-scope siempre; scope solo tras elegir entidad).
  const onPeriodChange = (p: string) => {
    setSelPeriod(p);
    if (!needsScope || activeScope) runReport(p, activeScope);
  };

  useEffect(() => {
    // Períodos del producto (best-effort) → selector; default = el más reciente.
    getProductPeriods(sector.sector_key)
      .then((ps) => {
        setPeriods(ps);
        const def = ps[0] || "";
        setSelPeriod(def);
        if (!needsScope) runReport(def);
      })
      .catch(() => { if (!needsScope) runReport(""); });
    // Si necesita entidad (banca), trae el universo y muestra el selector en dos pasos.
    if (needsScope) {
      getProductScopeOptions(sector.sector_key)
        .then(setOptions)
        .catch(() => setOptions([])); // sin opciones → input libre (fallback)
    }
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
      {needsScope && status !== "ready" && (
        <form
          onSubmit={(e) => { e.preventDefault(); if (scope.trim()) fetchReport(scope.trim()); }}
          className="space-y-2"
        >
          <label className="text-xs text-muted block">{scopeLabel}</label>
          {options.length > 0 ? (
            <div className="space-y-2">
              {/* Paso 1: tipo/región (solo si las opciones traen agrupador). */}
              {hasTypes && (
                <select
                  value={typeFilter}
                  onChange={(e) => { setTypeFilter(e.target.value); setScope(""); }}
                  className="field w-full"
                >
                  <option value="">{typePlaceholder}</option>
                  {entityTypes.map((g) => (
                    <option key={g} value={g}>{groupLabel(g)}</option>
                  ))}
                </select>
              )}
              {/* Paso 2: sujeto del grupo elegido (deshabilitado hasta elegir grupo). */}
              <div className="flex gap-2">
                <select
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                  disabled={hasTypes && !typeFilter}
                  className="field flex-1 disabled:opacity-50"
                >
                  <option value="">{entityPlaceholder}</option>
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

      {periods.length > 0 && (
        <div className="mb-3 flex items-center gap-2">
          <label className="text-xs text-muted shrink-0">{t("platform.catalog.periodLabel")}</label>
          <select
            value={selPeriod}
            onChange={(e) => onPeriodChange(e.target.value)}
            className="field"
          >
            {/* Cada corte se rotula por lo que ES: una fecha. Diciembre llegó a mostrarse
                como «cierre anual YYYY» y el efecto fue que el cuarto trimestre pareciera
                sustituido por un informe del año que ese corte no entrega. El año se ofrece
                abajo, como lo que es: otro producto. */}
            {periods.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
      )}

      {/* Diciembre es el cierre del ejercicio, así que es AHÍ donde alguien va a buscar el
          año. En vez de reetiquetar el corte —que prometería lo que no da—, se nombra el
          producto que sí lo responde. `cierreDeEjercicio` sólo matchea fechas: el producto
          anual se pide por año (`2025`), de modo que este aviso no puede aparecer dentro de
          él diciéndole al lector que vaya donde ya está. */}
      {cierreDeEjercicio(selPeriod) && (
        <p className="mb-3 text-[11px] leading-snug text-muted">
          {t("platform.catalog.cierreEjercicioNota", {
            anio: cierreDeEjercicio(selPeriod),
            defaultValue: "Este informe es la lectura AL 31 de diciembre de {{anio}}: cómo "
              + "está la entidad en esa fecha. Cómo le fue durante el ejercicio es la "
              + "Revisión Anual, un producto aparte del catálogo.",
          })}
        </p>
      )}

      {status === "loading" && <Skeleton className="h-64" />}
      {status === "error" && (
        <>
          <StateBlock kind="error" message={errMsg || t("platform.catalog.reportError")} />
          {errPista && (
            <p className="mt-1 text-center text-[11px] text-faint">
              {t("platform.catalog.errorPista", { pista: errPista,
                 defaultValue: "Detalle técnico: {{pista}}" })}
            </p>
          )}
        </>
      )}

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
          {/* Titular de portada (ISA · rentab. real · Sharpe): mismo string que el PDF,
              stasheado en el payload por el producto. Sólo se muestra si el producto lo llena. */}
          {(() => {
            const p = report.payload as Record<string, unknown>;
            const headline = typeof p.headline_line === "string" ? p.headline_line : null;
            const caveat = typeof p.caveat === "string" ? p.caveat : null;
            if (!headline && !caveat) return null;
            return (
              <div className="rounded-[10px] border border-line bg-surface2 p-3">
                {headline && (
                  <p className="font-display text-base font-extrabold text-ink">{headline}</p>
                )}
                {caveat && (
                  <p className="mt-1 text-[11px] leading-snug text-muted">{caveat}</p>
                )}
              </div>
            );
          })()}
          {/* Retorno ajustado por riesgo (Diferido B): tira con σ / Sharpe / retorno / TPM,
              leída de la dimensión `riesgo` del ISA. Presentación — el score es la σ. */}
          {(() => {
            const rating = (report.payload as { rating?: { dimensions?: RiskDim[] } }).rating;
            const risk = rating?.dimensions?.find((d) => d.key === "riesgo");
            if (!risk || risk.sharpe == null) return null;
            const stats = [
              { label: t("platform.catalog.risk.sharpe"), value: risk.sharpe != null ? risk.sharpe.toFixed(2) : "—" },
              { label: t("platform.catalog.risk.vol"), value: risk.raw != null ? `${risk.raw.toFixed(2)}%` : "—" },
              { label: t("platform.catalog.risk.return"), value: risk.annual_return_pct != null ? `${risk.annual_return_pct.toFixed(1)}%` : "—" },
              { label: t("platform.catalog.risk.free"), value: risk.risk_free_pct != null ? `${risk.risk_free_pct.toFixed(1)}%` : "—" },
            ];
            return (
              <div className="rounded-[10px] bg-surface2 p-3">
                <div className="text-[11px] uppercase tracking-wide text-faint">{t("platform.catalog.risk.title")}</div>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {stats.map((s) => (
                    <div key={s.label}>
                      <div className="text-[11px] uppercase tracking-wide text-faint">{s.label}</div>
                      <div className="mono tabular-nums text-lg font-semibold text-ink">{s.value}</div>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] leading-snug text-muted">
                  {t("platform.catalog.risk.caveat", { n: risk.vol_window_months ?? "—" })}
                </p>
              </div>
            );
          })()}
          {(() => {
            const dims = reportDimensions(report)
              .map((d) => ({
                label: d.label ?? t(`platform.catalog.dim.${d.key}`, { defaultValue: d.key }),
                score: d.score,
              }));
            return dims.length >= 2 ? (
              <DimensionBars title={t("platform.catalog.dimensionsTitle")} data={dims} />
            ) : null;
          })()}
          {/* Las barras muestran el NIVEL de cada dimensión; esto muestra el MOVIMIENTO y de
              quién fue. La tabla se computaba desde hacía tiempo y se dibujaba SOLO en el PDF:
              el mismo producto decía cosas distintas en pantalla y al descargarlo. */}
          <AportesAlCambio ventanas={reportAportes(report)} />
          {(() => { let n = 0; return report.commercial.sections.map((sec) => {
            const text = report.narratives[sec];
            if (!text) return null;
            n += 1;
            return (
              <div key={sec} className="space-y-1.5">
                <div className="text-[11px] uppercase tracking-wide text-faint">
                  {n}. {t(`platform.catalog.section.${sec}`, { defaultValue: sec.replace(/_/g, " ") })}
                </div>
                <Markdown text={text} />
              </div>
            );
          }); })()}
          <div className="pt-2 border-t border-line flex flex-wrap gap-2">
            {/* Descarga con el MISMO período/entidad que el reporte mostrado (selPeriod +
                activeScope), nunca el período global del topbar. */}
            <button
              onClick={() => downloadProductReport(sector.sector_key, level.tier, "pdf",
                { period: selPeriod || periodEnd, ...(activeScope ? { scope: activeScope } : {}) })}
              className="btn btn-ghost text-sm"
            >
              <Download className="w-4 h-4" /> {t("platform.catalog.downloadPdf")}
            </button>
            <button
              onClick={() => downloadProductReport(sector.sector_key, level.tier, "docx",
                { period: selPeriod || periodEnd, ...(activeScope ? { scope: activeScope } : {}) })}
              className="btn btn-ghost text-sm"
            >
              <FileText className="w-4 h-4" /> {t("platform.catalog.downloadWord")}
            </button>
            {/* Vigilar el MISMO sujeto que se está mirando (activeScope); sin sujeto, el
                eje entero. Es el punto de entrada real a la watchlist: nadie configura
                alertas en abstracto. */}
            <VigilarButton sectorKey={sector.sector_key} subject={activeScope ?? null} />
          </div>
        </>
      )}
    </InsightDrawerShell>
  );
}
