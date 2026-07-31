import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Download,
  FileText,
  Filter,
  ListChecks,
  FileSearch,
  Plus,
  Radar,
  Scale,
  Upload,
  Wallet,
} from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  StatTile,
  StateBlock,
  LoadingGrid,
  Chip,
} from "@/shared/ui/primitives";
import { fmtDelta, fmtNum, fmtPct } from "@/shared/lib/format";
import {
  listEngagements,
  getCategory,
  getFunnel,
  getTicket,
  getSignalFilter,
  getDecisions,
  getBacktest,
  getAttribution,
  getScenarios,
  getVigilance,
  getEngagementDetail,
  uploadPdf,
  listExtractions,
  issueForecast,
  scoreForecasts,
  downloadTemplate,
  openReport,
  uploadWorkbook,
  type AgendaItem,
  type AttributionAnalysis,
  type BacktestPayload,
  type CategoryAnalysis,
  type DecisionStatus,
  type DecisionsPayload,
  type Engagement,
  type EngagementDetail,
  type FunnelAnalysis,
  type IngestReport,
  type ExtractionSummary,
  type PdfIngestReport,
  type ScenariosAnalysis,
  type SignalFilter,
  type TicketAnalysis,
  type VigilanceAnalysis,
} from "../api";
import { NewEngagementDrawer } from "../components/NewEngagementDrawer";
import { DecisionDrawer } from "../components/DecisionDrawer";
import { ExtractionReviewDrawer } from "../components/ExtractionReviewDrawer";

type Status = "loading" | "error" | "ready";

const DECISION_TONE: Record<DecisionStatus, "ok" | "alert" | "warn" | "muted"> = {
  achieved: "ok",
  worsened: "alert",
  not_detectable: "warn",
  unevaluable: "muted",
  open: "muted",
};

const DECISION_LABEL: Record<DecisionStatus, string> = {
  achieved: "Logrado",
  worsened: "Empeoró",
  not_detectable: "No detectable",
  unevaluable: "Inevaluable",
  open: "Abierta",
};

/** Share of category, wave by wave. The denominator the tracker does not build. */
function ShareTable({ data }: { data: CategoryAnalysis }) {
  const waves = data.waves ?? [];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-muted">
            <th className="text-left font-semibold pb-2">Marca</th>
            {waves.map((w) => (
              <th key={w.code} className="text-right font-semibold pb-2 px-3">
                {w.label}
              </th>
            ))}
            <th className="text-right font-semibold pb-2">Δ</th>
          </tr>
        </thead>
        <tbody>
          {(data.share ?? []).map((row) => {
            const values = row.series.map((s) => s.share);
            const first = values.find((v) => v != null) ?? null;
            const last = [...values].reverse().find((v) => v != null) ?? null;
            const delta = first != null && last != null ? last - first : null;
            return (
              <tr
                key={row.brand}
                className={`border-t border-hair ${row.is_focal ? "font-semibold text-ink" : "text-body"}`}
              >
                <td className="py-2 truncate max-w-[180px]">{row.name}</td>
                {row.series.map((s) => (
                  <td key={s.wave} className="py-2 px-3 text-right mono">
                    {s.share == null ? "—" : fmtPct(s.share)}
                  </td>
                ))}
                <td className="py-2 text-right mono">
                  {delta == null ? "—" : `${delta > 0 ? "+" : ""}${fmtNum(delta)} pp`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Declared preference against effective traffic share. When they diverge, that is the finding. */
function DivergenceBlock({ data }: { data: CategoryAnalysis }) {
  const reading = data.divergence_reading;
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-muted">
              <th className="text-left font-semibold pb-2">Ola</th>
              <th className="text-right font-semibold pb-2">Preferencia declarada</th>
              <th className="text-right font-semibold pb-2">Share de tráfico</th>
            </tr>
          </thead>
          <tbody>
            {(data.divergence ?? []).map((d) => (
              <tr key={d.wave} className="border-t border-hair text-body">
                <td className="py-2">{d.label}</td>
                <td className="py-2 text-right mono">
                  {d.attitude == null ? "—" : fmtPct(d.attitude)}
                </td>
                <td className="py-2 text-right mono">
                  {d.behaviour == null ? "—" : fmtPct(d.behaviour)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {reading && (
        <p className="text-sm text-body rounded-lg bg-surface2 p-3">
          {reading.diverging ? (
            <>
              Entre {reading.wave_from} y {reading.wave_to} los dos indicadores se movieron en{" "}
              <strong className="text-ink">direcciones opuestas</strong>: preferencia{" "}
              {fmtDelta(reading.delta_attitude)} pp, tráfico {fmtDelta(reading.delta_behaviour)} pp.{" "}
              {reading.direction === "converting_above_attitude"
                ? "La marca convierte por encima de su capital actitudinal."
                : "La preferencia va por delante de la conversión."}
            </>
          ) : (
            <>Actitud y comportamiento se mueven en el mismo sentido: están alineados.</>
          )}
        </p>
      )}
    </div>
  );
}

/** What each indicator would need to move to sustain a budget decision. */
function SignalTable({ data }: { data: SignalFilter }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-muted">
            <th className="text-left font-semibold pb-2">Indicador</th>
            <th className="text-left font-semibold pb-2">Corte</th>
            <th className="text-right font-semibold pb-2">Base</th>
            <th className="text-right font-semibold pb-2">Umbral</th>
            <th className="text-left font-semibold pb-2 pl-4">Estado</th>
          </tr>
        </thead>
        <tbody>
          {(data.rows ?? []).map((r) => (
            <tr key={`${r.metric_code}-${r.segment}`} className="border-t border-hair text-body">
              <td className="py-2 truncate max-w-[240px]">{r.label}</td>
              <td className="py-2 text-muted">{r.segment}</td>
              <td className="py-2 text-right mono">{r.base_n ?? "—"}</td>
              <td className="py-2 text-right mono">
                {r.threshold == null ? "—" : `±${fmtNum(r.threshold)} pp`}
              </td>
              <td className="py-2 pl-4">
                <Chip tone={r.publishable ? "ok" : "alert"}>
                  {r.publishable ? "Utilizable" : "Base insuficiente"}
                </Chip>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The accountability loop: the client's decisions, each with a verdict. */
function DecisionsBlock({ data }: { data: DecisionsPayload }) {
  if (!data.decisions.length) {
    return (
      <p className="text-sm text-muted">
        Aún no hay decisiones registradas. Cada decisión requiere métrica, línea base,
        ventana de evaluación, umbral de éxito y responsable.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {data.decisions.map((d) => (
        <div key={d.id} className="rounded-lg border border-hair p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-ink">{d.title}</div>
              <div className="text-xs text-muted mt-0.5">
                {d.label}
                {d.owner ? ` · ${d.owner}` : ""}
              </div>
            </div>
            <Chip tone={DECISION_TONE[d.status]}>{DECISION_LABEL[d.status]}</Chip>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 mt-2 text-xs text-body mono">
            <span>
              {d.baseline_value == null ? "—" : fmtPct(d.baseline_value)} →{" "}
              {d.target_value == null ? "—" : fmtPct(d.target_value)}
            </span>
            {d.observed_delta != null && <span>Δ {fmtNum(d.observed_delta)} pp</span>}
            {d.detectable_threshold != null && (
              <span>umbral ±{fmtNum(d.detectable_threshold)} pp</span>
            )}
          </div>
          {d.note && <p className="text-xs text-muted mt-2">{d.note}</p>}
        </div>
      ))}
    </div>
  );
}

const PRIORITY_TONE: Record<AgendaItem["priority"], "alert" | "warn" | "muted"> = {
  alta: "alert",
  media: "warn",
  baja: "muted",
};

/** The agenda leads the page: it is the part the client acts on. */
function AgendaBlock({ data }: { data: VigilanceAnalysis }) {
  const agenda = data.agenda;
  if (!agenda || agenda.empty_reason) {
    return (
      <p className="text-sm text-muted">
        {agenda?.empty_reason ?? data.reason ?? "Sin agenda disponible."}
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {agenda.items.map((item, i) => (
        <div key={i} className="flex items-start gap-4">
          <span className="font-display text-xl font-extrabold text-ink mono w-6 shrink-0">
            {i + 1}
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold text-ink">{item.title}</span>
              <Chip tone={PRIORITY_TONE[item.priority]}>{item.priority}</Chip>
            </div>
            <p className="text-xs text-muted mt-1">{item.rationale}</p>
            {item.evidence.length > 0 && (
              <p className="text-xs text-body mono mt-1">{item.evidence.join(" · ")}</p>
            )}
          </div>
        </div>
      ))}
      <p className="text-xs text-muted">{agenda.note}</p>
    </div>
  );
}

const VERDICT_TONE: Record<string, "alert" | "warn" | "muted"> = {
  marca: "alert",
  solo_marca: "alert",
  categoria: "warn",
  mixto: "muted",
  sin_movimiento: "muted",
};

/** S3 — was it the brand, or the market moving under it? */
function AttributionBlock({ data }: { data: AttributionAnalysis }) {
  if (!data.available) return <p className="text-sm text-muted">{data.reason}</p>;
  const env = data.environment;
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-muted">
              <th className="text-left font-semibold pb-2">Indicador</th>
              <th className="text-right font-semibold pb-2">Movimiento</th>
              <th className="text-right font-semibold pb-2">Categoría</th>
              <th className="text-right font-semibold pb-2">Marca</th>
              <th className="text-left font-semibold pb-2 pl-4">Origen</th>
            </tr>
          </thead>
          <tbody>
            {(data.rows ?? []).map((r) => (
              <tr key={r.metric_code} className="border-t border-hair text-body">
                <td className="py-2 truncate max-w-[220px]">{r.label}</td>
                <td className="py-2 text-right mono">{fmtDelta(r.delta)} pp</td>
                <td className="py-2 text-right mono">
                  {r.category_effect == null ? "n/d" : `${fmtDelta(r.category_effect, 2)} pp`}
                </td>
                <td className="py-2 text-right mono">
                  {r.brand_effect == null ? "n/d" : `${fmtDelta(r.brand_effect, 2)} pp`}
                </td>
                <td className="py-2 pl-4">
                  <Chip tone={VERDICT_TONE[r.verdict] ?? "muted"}>
                    {r.verdict === "solo_marca" ? "marca" : r.verdict.replace("_", " ")}
                  </Chip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {env && (
        <p className="text-sm text-body rounded-lg bg-surface2 p-3">
          {env.available ? (
            <>
              Entorno macro del período: <strong className="text-ink">{env.stance}</strong>.{" "}
              {env.note}
            </>
          ) : (
            env.note
          )}
        </p>
      )}
    </div>
  );
}

/** S4 — how to read the forecast, and what could invalidate it. */
function ScenariosBlock({ data }: { data: ScenariosAnalysis }) {
  if (!data.available) return <p className="text-sm text-muted">{data.reason}</p>;
  const fragile = (data.rule_dispersion ?? []).filter((d) => !d.robust);
  const bandLabel: Record<string, string> = {
    sesgo_a_la_baja: "Sesgo a la baja",
    sesgo_al_alza: "Sesgo al alza",
    simetrica: "Simétrica",
  };
  return (
    <div className="space-y-3">
      {(data.scenarios ?? []).map((s) => (
        <div key={s.key} className="rounded-lg border border-hair p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-semibold text-ink">{s.label}</span>
            <Chip tone={s.band_reading === "sesgo_a_la_baja" ? "alert" : "muted"}>
              {bandLabel[s.band_reading] ?? s.band_reading}
            </Chip>
          </div>
          <ul className="mt-1.5 space-y-0.5">
            {s.assumptions.map((a, i) => (
              <li key={i} className="text-xs text-muted">
                · {a}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <p className="text-sm text-body rounded-lg bg-surface2 p-3">
        {fragile.length ? (
          <>
            Pronósticos que dependen de la regla elegida más que de la serie:{" "}
            <strong className="text-ink">
              {fragile.map((d) => d.label).join(", ")}
            </strong>
            . Léanse con reserva.
          </>
        ) : (
          <>
            Las tres reglas coinciden dentro de la banda muestral en todos los indicadores:
            el resultado no depende de cuál se elija.
          </>
        )}
      </p>
      {(data.risks ?? []).length > 0 && (
        <ul className="space-y-1">
          {(data.risks ?? []).map((r, i) => (
            <li key={i} className="text-xs text-muted">
              <span className="font-semibold text-body">{r.risk}.</span> {r.detail}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const STRENGTH_TONE: Record<string, "ok" | "warn" | "muted"> = {
  confirmada: "ok",
  marginal: "warn",
  contextual: "muted",
};

const SOURCE_LABEL: Record<string, string> = {
  forecast: "Pronóstico",
  tracker: "Tracker",
  decision: "Decisiones",
  macro: "Macro",
};

/** S5 — what moved since the last delivery. */
function VigilanceBlock({ data }: { data: VigilanceAnalysis }) {
  if (!data.available) return <p className="text-sm text-muted">{data.reason}</p>;
  const rows = (["forecast", "tracker", "decision", "macro"] as const).flatMap(
    (src) => data.signals?.[src] ?? [],
  );
  if (!rows.length) {
    return <p className="text-sm text-muted">Ninguna señal superó su umbral en el período.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-muted">
            <th className="text-left font-semibold pb-2">Fuente</th>
            <th className="text-left font-semibold pb-2">Señal</th>
            <th className="text-left font-semibold pb-2">Lectura</th>
            <th className="text-left font-semibold pb-2 pl-4">Fuerza</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s, i) => (
            <tr key={i} className="border-t border-hair text-body">
              <td className="py-2 text-muted">{SOURCE_LABEL[s.source] ?? s.source}</td>
              <td className="py-2 truncate max-w-[220px]">{s.label}</td>
              <td className="py-2 mono text-xs">{s.reading}</td>
              <td className="py-2 pl-4">
                <Chip tone={STRENGTH_TONE[s.strength] ?? "muted"}>{s.strength}</Chip>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Ranking of the naive forecast rules on this engagement's own history. */
function BacktestBlock({ data }: { data: BacktestPayload }) {
  if (!data.available) {
    return <p className="text-sm text-muted">{data.reason}</p>;
  }
  return (
    <div className="space-y-3">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-muted">
            <th className="text-left font-semibold pb-2">Regla</th>
            <th className="text-right font-semibold pb-2">Error medio</th>
          </tr>
        </thead>
        <tbody>
          {(data.ranking ?? []).map((r, i) => (
            <tr
              key={r.rule}
              className={`border-t border-hair ${i === 0 ? "font-semibold text-ink" : "text-body"}`}
            >
              <td className="py-2">{r.rule}</td>
              <td className="py-2 text-right mono">{fmtNum(r.mae, 2)} pp</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.note && <p className="text-xs text-muted">{data.note}</p>}
    </div>
  );
}

export function BrandIntelPage() {
  const [status, setStatus] = useState<Status>("loading");
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [slug, setSlug] = useState<string>("");
  const [category, setCategory] = useState<CategoryAnalysis | null>(null);
  const [funnel, setFunnel] = useState<FunnelAnalysis | null>(null);
  const [ticket, setTicket] = useState<TicketAnalysis | null>(null);
  const [signal, setSignal] = useState<SignalFilter | null>(null);
  const [decisions, setDecisions] = useState<DecisionsPayload | null>(null);
  const [backtest, setBacktest] = useState<BacktestPayload | null>(null);
  const [attribution, setAttribution] = useState<AttributionAnalysis | null>(null);
  const [scenarios, setScenarios] = useState<ScenariosAnalysis | null>(null);
  const [vigilance, setVigilance] = useState<VigilanceAnalysis | null>(null);
  const [ingest, setIngest] = useState<IngestReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<EngagementDetail | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [showDecision, setShowDecision] = useState(false);
  const [forecastMsg, setForecastMsg] = useState<string | null>(null);
  const [extractions, setExtractions] = useState<ExtractionSummary[]>([]);
  const [pdfReport, setPdfReport] = useState<PdfIngestReport | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pdfRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listEngagements()
      .then((rows) => {
        setEngagements(rows);
        setSlug(rows[0]?.slug ?? "");
        setStatus(rows.length ? "ready" : "ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  const load = useCallback(async (target: string) => {
    if (!target) return;
    setStatus("loading");
    try {
      const [det, cat, fun, tic, sig, dec, bt, att, scn, vig] = await Promise.all([
        getEngagementDetail(target),
        getCategory(target),
        getFunnel(target),
        getTicket(target),
        getSignalFilter(target),
        getDecisions(target),
        getBacktest(target),
        getAttribution(target),
        getScenarios(target),
        getVigilance(target),
      ]);
      setDetail(det);
      setCategory(cat);
      listExtractions(target).then(setExtractions).catch(() => setExtractions([]));
      setFunnel(fun);
      setTicket(tic);
      setSignal(sig);
      setDecisions(dec);
      setBacktest(bt);
      setAttribution(att);
      setScenarios(scn);
      setVigilance(vig);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    if (slug) void load(slug);
  }, [slug, load]);

  const onEngagementCreated = async (newSlug: string) => {
    setShowNew(false);
    const rows = await listEngagements();
    setEngagements(rows);
    setSlug(newSlug);
  };

  const onIssueForecast = async () => {
    const target = detail?.waves?.[detail.waves.length - 1]?.code;
    if (!target) return;
    setBusy(true);
    setForecastMsg(null);
    try {
      const out = await issueForecast(slug, target);
      setForecastMsg(
        out.issued.length
          ? `Pronóstico congelado para ${out.target_wave}: ${out.issued.length} indicador(es), regla «${out.issued[0].rule}».`
          : "No se pudo emitir: historia o base insuficiente.",
      );
      await load(slug);
    } catch {
      setForecastMsg("No se pudo emitir el pronóstico.");
    } finally {
      setBusy(false);
    }
  };

  const onScoreForecasts = async () => {
    setBusy(true);
    setForecastMsg(null);
    try {
      const out = await scoreForecasts(slug);
      setForecastMsg(
        out.n
          ? `${out.n} pronóstico(s) puntuado(s) contra el dato real.`
          : "No hay pronósticos pendientes con dato para puntuar.",
      );
      await load(slug);
    } catch {
      setForecastMsg("No se pudieron puntuar los pronósticos.");
    } finally {
      setBusy(false);
    }
  };

  const onUploadPdf = async (file: File) => {
    setBusy(true);
    setPdfReport(null);
    try {
      const report = await uploadPdf(slug, file);
      setPdfReport(report);
      setExtractions(await listExtractions(slug));
      if (report.extraction_id) setReviewing(report.extraction_id);
    } catch {
      setPdfReport(null);
      setForecastMsg("No se pudo procesar el PDF.");
    } finally {
      setBusy(false);
      if (pdfRef.current) pdfRef.current.value = "";
    }
  };

  const onUpload = async (file: File) => {
    setBusy(true);
    setIngest(null);
    try {
      setIngest(await uploadWorkbook(slug, file));
      await load(slug);
    } catch {
      setStatus("error");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  if (status === "loading" && !category) return <LoadingGrid />;

  if (status === "error") {
    return (
      <StateBlock
        kind="error"
        title="No se pudo cargar el encargo"
        message="Verifica tu acceso al encargo o vuelve a intentarlo."
      />
    );
  }

  if (!engagements.length) {
    return (
      <>
        <StateBlock
          kind="empty"
          title="Sin encargos"
          message="Un encargo agrupa las olas, marcas y observaciones de un tracker. Crea el primero para empezar a cargar datos."
          action={
            <button className="btn btn-primary" onClick={() => setShowNew(true)}>
              <Plus size={15} /> Nuevo encargo
            </button>
          }
        />
        {showNew && (
          <NewEngagementDrawer
            onClose={() => setShowNew(false)}
            onCreated={onEngagementCreated}
          />
        )}
      </>
    );
  }

  const current = engagements.find((e) => e.slug === slug);
  const growth = category?.category_growth_pct;
  const reading = category?.divergence_reading;
  const weakest = funnel?.weakest_step;

  return (
    <div className="space-y-6">
      <PageHead
        eyebrow="Contexto de Mercado"
        title={current ? current.focal_brand : "Brand Intel"}
        sub={
          current
            ? [
                current.category,
                current.market,
                `${current.waves} ola${current.waves === 1 ? "" : "s"}`,
                current.provider ? `Tracker: ${current.provider}` : null,
              ]
                .filter(Boolean)
                .join(" · ")
            : undefined
        }
        right={
          <div className="flex flex-wrap items-center gap-2">
            {engagements.length > 1 && (
              <select
                className="field text-sm w-auto"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                aria-label="Encargo"
              >
                {engagements.map((e) => (
                  <option key={e.slug} value={e.slug}>
                    {e.focal_brand} — {e.client}
                  </option>
                ))}
              </select>
            )}
            <button className="btn btn-ghost text-sm" onClick={() => setShowNew(true)}>
              <Plus size={15} /> Encargo
            </button>
            <button className="btn btn-ghost text-sm" onClick={() => void downloadTemplate(slug)}>
              <Download size={15} /> Plantilla
            </button>
            <button
              className="btn btn-ghost text-sm"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
            >
              <Upload size={15} /> {busy ? "Cargando…" : "Excel"}
            </button>
            <button
              className="btn btn-ghost text-sm"
              disabled={busy}
              onClick={() => pdfRef.current?.click()}
              title="Lee las láminas del informe y las deja en revisión"
            >
              <FileSearch size={15} /> Presentación
            </button>
            <input
              ref={pdfRef}
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onUploadPdf(f);
              }}
            />
            <button className="btn btn-primary text-sm" onClick={() => void openReport(slug)}>
              <FileText size={15} /> Informe
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.xlsm"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onUpload(f);
              }}
            />
          </div>
        }
      />

      {ingest && (
        <Card>
          <CardHead
            icon={Upload}
            title="Resultado de la carga"
            subtitle={
              ingest.total_rechazadas
                ? `${ingest.total_rechazadas} fila(s) rechazada(s)`
                : "Sin filas rechazadas"
            }
          />
          <div className="text-sm text-body space-y-1">
            <div className="mono">
              Olas +{ingest.olas.creadas}/~{ingest.olas.actualizadas} · Marcas +
              {ingest.marcas.creadas}/~{ingest.marcas.actualizadas} · Observaciones +
              {ingest.observaciones.creadas}/~{ingest.observaciones.actualizadas}
            </div>
            {ingest.rechazadas.slice(0, 8).map((r, i) => (
              <div key={i} className="text-xs text-muted">
                {r.sheet} fila {r.row}: {r.reason}
              </div>
            ))}
            {ingest.advertencias.map((w, i) => (
              <div key={`w-${i}`} className="text-xs text-muted">
                {w}
              </div>
            ))}
          </div>
        </Card>
      )}

      {(pdfReport || extractions.length > 0) && (
        <Card>
          <CardHead
            icon={FileSearch}
            title="Presentaciones leídas"
            subtitle="Las cifras extraídas esperan revisión antes de convertirse en datos"
          />
          {pdfReport && (
            <p className="text-sm text-body rounded-lg bg-surface2 p-3 mb-3">
              {pdfReport.nota_cobertura}
              {pdfReport.total_rechazadas > 0 && (
                <span className="text-muted">
                  {" "}
                  {pdfReport.total_rechazadas} fila(s) no pudieron mapearse al encargo.
                </span>
              )}
            </p>
          )}
          <div className="space-y-2">
            {extractions.map((x) => (
              <div
                key={x.id}
                className="flex items-center justify-between gap-3 rounded-lg border border-hair p-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-ink truncate">{x.document}</div>
                  <div className="text-xs text-muted mt-0.5">
                    {x.pages ?? "—"} láminas
                    {x.summary ? ` · ${x.summary.passed}/${x.summary.total} confirmadas` : ""}
                    {x.confirmed_by ? ` · confirmada por ${x.confirmed_by}` : ""}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Chip tone={x.status === "confirmed" ? "ok" : "warn"}>
                    {x.status === "confirmed" ? "Confirmada" : "Pendiente"}
                  </Chip>
                  {x.status !== "confirmed" && (
                    <button
                      className="btn btn-ghost text-xs"
                      onClick={() => setReviewing(x.id)}
                    >
                      Revisar
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile
          label="Tamaño de la categoría"
          value={growth == null ? "—" : `${growth > 0 ? "+" : ""}${fmtNum(growth)}`}
          unit="%"
        />
        <StatTile
          label="Share de la marca focal"
          value={(() => {
            const focal = category?.share?.find((s) => s.is_focal);
            const last = focal?.series?.[focal.series.length - 1]?.share;
            return last == null ? "—" : fmtPct(last);
          })()}
        />
        <StatTile
          label="Ticket real desde el pico"
          value={
            ticket?.change_from_peak_pct == null
              ? "—"
              : `${fmtNum(ticket.change_from_peak_pct)}`
          }
          unit="%"
        />
        <StatTile
          label="Decisiones cerradas"
          value={decisions ? `${decisions.summary.closed}/${decisions.summary.total}` : "—"}
        />
      </div>

      {vigilance && (
        <Card>
          <CardHead
            icon={ListChecks}
            title="Lo que el trimestre justifica discutir"
            subtitle="Agenda derivada de las señales que superaron su umbral"
          />
          <AgendaBlock data={vigilance} />
        </Card>
      )}

      {category?.available ? (
        <>
          <Card>
            <CardHead
              icon={Activity}
              title="Posición competitiva efectiva"
              subtitle={category.denominator_note}
            />
            <ShareTable data={category} />
          </Card>

          <Card>
            <CardHead
              icon={Activity}
              title="Actitud contra comportamiento"
              subtitle="Preferencia declarada frente a share de tráfico efectivo"
              right={
                reading?.diverging ? <Chip tone="warn">Se cruzan</Chip> : undefined
              }
            />
            <DivergenceBlock data={category} />
          </Card>
        </>
      ) : (
        <Card>
          <CardHead icon={Activity} title="Posición competitiva efectiva" />
          <p className="text-sm text-muted">{category?.reason}</p>
        </Card>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <CardHead
            icon={Wallet}
            title="El ticket en pesos constantes"
            subtitle={ticket?.deflated ? ticket.deflator_note : undefined}
          />
          {ticket?.available ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-muted">
                  <th className="text-left font-semibold pb-2">Ola</th>
                  <th className="text-right font-semibold pb-2">Nominal</th>
                  <th className="text-right font-semibold pb-2">Real</th>
                </tr>
              </thead>
              <tbody>
                {(ticket.series ?? []).map((r) => (
                  <tr key={r.wave} className="border-t border-hair text-body">
                    <td className="py-2">{r.label}</td>
                    <td className="py-2 text-right mono">{fmtNum(r.nominal, 0)}</td>
                    <td className="py-2 text-right mono">
                      {r.real == null ? "—" : fmtNum(r.real, 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-muted">{ticket?.reason}</p>
          )}
        </Card>

        <Card>
          <CardHead
            icon={Activity}
            title="Embudo de conversión"
            subtitle={funnel?.wave ? `Ola ${funnel.wave.label}` : undefined}
          />
          {weakest ? (
            <div className="space-y-2">
              <p className="text-sm text-body">
                Escalón de mayor rezago:{" "}
                <strong className="text-ink">{weakest.step_label}</strong>
              </p>
              <p className="text-sm text-body">
                La marca focal convierte{" "}
                <span className="mono">{fmtPct(weakest.focal_conversion, 0)}</span> frente al{" "}
                <span className="mono">{fmtPct(weakest.leader_conversion, 0)}</span> de{" "}
                {weakest.leader_name ?? weakest.leader} — brecha de{" "}
                <span className="mono">{fmtNum(weakest.gap)} pp</span>.
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted">
              {funnel?.reason ?? "Sin escalón de rezago identificable."}
            </p>
          )}
        </Card>
      </div>

      {attribution && (
        <Card>
          <CardHead
            icon={Scale}
            title="¿La marca o el mercado?"
            subtitle={
              attribution.available
                ? `${attribution.wave_from_label} → ${attribution.wave_to_label}`
                : undefined
            }
          />
          <AttributionBlock data={attribution} />
        </Card>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        {scenarios && (
          <Card>
            <CardHead
              icon={Activity}
              title="Qué podría invalidar el pronóstico"
              subtitle="Los escenarios califican la lectura; no mueven las cifras"
            />
            <ScenariosBlock data={scenarios} />
          </Card>
        )}
        {vigilance && (
          <Card>
            <CardHead
              icon={Radar}
              title="Panel de vigilancia"
              subtitle="Qué se movió desde la última entrega"
            />
            <VigilanceBlock data={vigilance} />
          </Card>
        )}
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <CardHead icon={Filter} title="Filtro de señal" subtitle={signal?.note} />
          {signal?.available ? (
            <SignalTable data={signal} />
          ) : (
            <p className="text-sm text-muted">{signal?.reason}</p>
          )}
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHead
              icon={ListChecks}
              title="Ledger de decisiones"
              subtitle="Decisiones del cliente, con veredicto"
              right={
                <button
                  className="btn btn-ghost text-xs"
                  onClick={() => setShowDecision(true)}
                  disabled={!signal?.rows?.length}
                >
                  <Plus size={14} /> Registrar
                </button>
              }
            />
            {decisions && <DecisionsBlock data={decisions} />}
          </Card>
          <Card>
            <CardHead
              icon={Activity}
              title="Regla de pronóstico"
              subtitle="Seleccionada por backtest sobre la historia del encargo"
              right={
                <div className="flex items-center gap-1.5">
                  <button
                    className="btn btn-ghost text-xs"
                    onClick={() => void onIssueForecast()}
                    disabled={busy || !detail?.waves?.length}
                    title="Congela un pronóstico para la última ola del encargo"
                  >
                    Congelar
                  </button>
                  <button
                    className="btn btn-ghost text-xs"
                    onClick={() => void onScoreForecasts()}
                    disabled={busy}
                    title="Puntúa los pronósticos pendientes contra el dato real"
                  >
                    Puntuar
                  </button>
                </div>
              }
            />
            {forecastMsg && (
              <p className="text-xs text-body rounded-lg bg-surface2 p-2.5 mb-3">
                {forecastMsg}
              </p>
            )}
            {backtest && <BacktestBlock data={backtest} />}
          </Card>
        </div>
      </div>

      {showNew && (
        <NewEngagementDrawer
          onClose={() => setShowNew(false)}
          onCreated={onEngagementCreated}
        />
      )}

      {reviewing && (
        <ExtractionReviewDrawer
          slug={slug}
          extractionId={reviewing}
          onClose={() => setReviewing(null)}
          onConfirmed={() => {
            setReviewing(null);
            setPdfReport(null);
            void load(slug);
            listExtractions(slug).then(setExtractions).catch(() => undefined);
          }}
        />
      )}

      {showDecision && detail && (
        <DecisionDrawer
          slug={slug}
          dataWaves={category?.waves ?? []}
          allWaves={detail.waves.map((w) => ({ code: w.code, label: w.label }))}
          metrics={signal?.rows ?? []}
          focalBrand={detail.brands.find((b) => b.is_focal)?.slug ?? null}
          onClose={() => setShowDecision(false)}
          onCreated={() => {
            setShowDecision(false);
            void load(slug);
          }}
        />
      )}
    </div>
  );
}
