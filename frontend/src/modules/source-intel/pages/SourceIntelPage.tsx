import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Compass, Plus, Trash2, Bot, User as UserIcon, Sparkles, Wrench, Database, RefreshCw } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import {
  listSuggestions, createSuggestion, setSuggestionStatus, deleteSuggestion, evaluateSuggestion,
  scaffoldSuggestion, runResearchAgent, agentStatus, runCatalogDiscovery, discoveryStatus,
  runMaintenance,
  type Suggestion, type SuggestionStatus, type SuggestionKind, type Evaluation,
  type IntegrationPlan,
} from "../api";

const KINDS: SuggestionKind[] = ["source", "info_type", "sector"];
const STATUSES: SuggestionStatus[] = [
  "proposed", "evaluating", "evaluated", "approved",
  "integrating", "integrated", "rejected", "deferred",
];
const AXES = ["banking", "macro", "trade", "tourism", "free_zones", "energy",
  "telecom", "construction", "agribusiness", "esg", "pension"];
const GATES = ["g1", "g2", "g3", "g4", "g5"];

// La lista se auto-prioriza por accionabilidad: lo que necesita al dueño arriba, lo
// cerrado/archivado al fondo (rechazadas al final del todo). Los grupos "cerrados"
// arrancan colapsados.
type GroupKey = "decide" | "approved" | "integrating" | "closed";
const GROUPS: { key: GroupKey; statuses: SuggestionStatus[]; closed?: boolean }[] = [
  { key: "decide", statuses: ["evaluated", "evaluating", "proposed"] },
  { key: "approved", statuses: ["approved"] },
  { key: "integrating", statuses: ["integrating"] },
  { key: "closed", statuses: ["integrated", "deferred", "rejected"], closed: true },
];
// Orden interno del grupo "cerrado": logro → pausa → rechazo (rechazadas al fondo).
const CLOSED_ORDER: SuggestionStatus[] = ["integrated", "deferred", "rejected"];

const scoreOf = (s: Suggestion): number =>
  typeof (s.evaluation as { score?: number } | null)?.score === "number"
    ? (s.evaluation as { score: number }).score : -1;

function statusTone(s: SuggestionStatus): "ok" | "warn" | "alert" | "muted" {
  if (s === "integrated" || s === "approved" || s === "integrating") return "ok";
  if (s === "rejected") return "alert";
  if (s === "evaluated" || s === "evaluating") return "warn";
  return "muted";
}

function recTone(r: Evaluation["recommendation"]): "ok" | "warn" | "alert" | "muted" {
  if (r === "approve") return "ok";
  if (r === "reject") return "alert";
  if (r === "defer") return "muted";
  return "warn";
}

function EvaluationBlock({ ev, t }: { ev: Evaluation; t: TFunction }) {
  return (
    <div className="mt-2 rounded-md border border-line bg-surface2/50 px-3 py-2">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="font-medium text-ink">{t("sourceIntel.evalScore")}</span>
        <span className="mono tabular-nums text-ink">{Math.round((ev.score ?? 0) * 100)}%</span>
        <Chip tone={recTone(ev.recommendation)}>{t(`sourceIntel.rec.${ev.recommendation}`)}</Chip>
        {ev.gate_closed && <Chip tone="muted">{ev.gate_closed.toUpperCase()}</Chip>}
        <Chip tone={ev.method === "ai" ? "ok" : "muted"}>{t(`sourceIntel.method.${ev.method}`)}</Chip>
        {ev.already_covered && (
          <span title={ev.coverage_note || ""}><Chip tone="warn">{t("sourceIntel.covered")}</Chip></span>
        )}
      </div>
      {ev.fit_rationale && <div className="text-[11px] text-muted mt-1">{ev.fit_rationale}</div>}
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1 text-[10px] text-faint">
        {Object.entries(ev.criteria || {}).map(([k, v]) => (
          <span key={k} className="tabular-nums">{t(`sourceIntel.crit.${k}`)}: {Math.round((v?.score ?? 0) * 100)}%</span>
        ))}
      </div>
    </div>
  );
}

function PlanBlock({ plan, t }: { plan: IntegrationPlan; t: TFunction }) {
  return (
    <div className="mt-2 rounded-md border border-line bg-surface px-3 py-2">
      <div className="flex items-center gap-2 text-xs">
        <Wrench className="w-3.5 h-3.5 text-muted" />
        <span className="font-medium text-ink">{t("sourceIntel.planTitle")}</span>
        <Chip tone={plan.method === "ai" ? "ok" : "muted"}>{t(`sourceIntel.method.${plan.method === "ai" ? "ai" : "heuristic"}`)}</Chip>
        {plan.effort && <span className="text-[10px] text-faint">· {t("sourceIntel.planEffort")}: {plan.effort}</span>}
      </div>
      <div className="text-[11px] text-muted mt-1 space-y-0.5">
        {plan.connector && <div><span className="text-faint">{t("sourceIntel.planConnector")}:</span> {plan.connector}</div>}
        {plan.crosswalk && <div><span className="text-faint">{t("sourceIntel.planCrosswalk")}:</span> {plan.crosswalk}</div>}
      </div>
      {plan.steps?.length > 0 && (
        <ol className="mt-1 text-[11px] text-muted list-decimal ml-4 space-y-0.5">
          {plan.steps.map((s, i) => <li key={i}>{s}</li>)}
        </ol>
      )}
      {plan.risks?.length > 0 && (
        <div className="mt-1 text-[10px] text-faint">{t("sourceIntel.planRisks")}: {plan.risks.join(" · ")}</div>
      )}
    </div>
  );
}

export function SourceIntelPage() {
  const { t } = useTranslation();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");

  const [items, setItems] = useState<Suggestion[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const [filterStatus, setFilterStatus] = useState<SuggestionStatus | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // Form
  const [kind, setKind] = useState<SuggestionKind>("source");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [axis, setAxis] = useState("");
  const [gate, setGate] = useState("");

  const load = () =>
    listSuggestions()
      .then((b) => { setItems(b.suggestions); setSummary(b.summary); setState("ready"); })
      .catch(() => setState("error"));

  useEffect(() => { if (isAdmin) load(); }, [isAdmin]);

  const onCreate = async () => {
    if (!title.trim()) return;
    setBusy("create"); setMsg(null);
    try {
      await createSuggestion({
        kind, title, description,
        target_axis: axis || null, target_gate: gate || null,
      });
      setTitle(""); setDescription(""); setAxis(""); setGate("");
      await load();
    } catch {
      setMsg(t("sourceIntel.createError"));
    } finally { setBusy(null); }
  };

  const onStatus = async (id: string, status: SuggestionStatus) => {
    setBusy(id); setMsg(null);
    try { await setSuggestionStatus(id, status); await load(); }
    catch { setMsg(t("sourceIntel.statusError")); }
    finally { setBusy(null); }
  };

  const onDelete = async (id: string) => {
    setBusy(id); setMsg(null);
    try { await deleteSuggestion(id); await load(); }
    catch { setMsg(t("sourceIntel.deleteError")); }
    finally { setBusy(null); }
  };

  const onEvaluate = async (id: string) => {
    setBusy(id); setMsg(null);
    try { await evaluateSuggestion(id); await load(); }
    catch { setMsg(t("sourceIntel.evalError")); }
    finally { setBusy(null); }
  };

  const onScaffold = async (id: string) => {
    setBusy(id); setMsg(null);
    try { await scaffoldSuggestion(id); await load(); }
    catch { setMsg(t("sourceIntel.scaffoldError")); }
    finally { setBusy(null); }
  };

  const onMaintenance = async () => {
    setBusy("maintenance"); setMsg(null);
    try {
      const r = await runMaintenance();
      await load();
      setMsg(t("sourceIntel.maintenanceDone", { deferred: r.deferred, flagged: r.flagged }));
    } catch {
      setMsg(t("sourceIntel.maintenanceError"));
    } finally { setBusy(null); }
  };

  const onGenerate = async () => {
    setBusy("agent"); setMsg(t("sourceIntel.agentWorking"));
    try {
      const r = await runResearchAgent();
      if (!r.started) { setMsg(t("sourceIntel.agentBusy")); return; }
      // Sondeo: el agente corre async (varias llamadas IA); refrescar al terminar.
      let last: { capped?: boolean } | null = null;
      for (let i = 0; i < 30; i++) {
        await new Promise((res) => setTimeout(res, 3000));
        const st = await agentStatus();
        last = st.lastResult;
        if (!st.running) break;
      }
      await load();
      // Honesto: si topó el cap por corrida, avisar que quedan brechas (correr de nuevo).
      setMsg(last?.capped ? t("sourceIntel.agentCapped") : t("sourceIntel.agentDone"));
    } catch {
      setMsg(t("sourceIntel.agentError"));
    } finally { setBusy(null); }
  };

  const onDiscover = async () => {
    setBusy("discover"); setMsg(t("sourceIntel.discoverWorking"));
    try {
      const r = await runCatalogDiscovery();
      if (!r.started) { setMsg(t("sourceIntel.agentBusy")); return; }
      let last: { capped?: boolean } | null = null;
      for (let i = 0; i < 30; i++) {
        await new Promise((res) => setTimeout(res, 3000));
        const st = await discoveryStatus();
        last = st.lastResult;
        if (!st.running) break;
      }
      await load();
      setMsg(last?.capped ? t("sourceIntel.agentCapped") : t("sourceIntel.discoverDone"));
    } catch {
      setMsg(t("sourceIntel.discoverError"));
    } finally { setBusy(null); }
  };

  if (!isAdmin) {
    return (
      <div>
        <PageHead eyebrow={t("sourceIntel.eyebrow")} title={t("sourceIntel.title")} sub={t("sourceIntel.sub")} />
        <StateBlock kind="forbidden" message={t("sourceIntel.forbidden")} />
      </div>
    );
  }

  // Items por grupo, ordenados por score desc (y el grupo cerrado por logro→pausa→rechazo).
  // Si hay un chip-filtro activo, solo ese estado pasa.
  const visible = filterStatus ? items.filter((s) => s.status === filterStatus) : items;
  const grouped = GROUPS.map((g) => {
    let rows = visible.filter((s) => g.statuses.includes(s.status));
    if (g.key === "closed") {
      rows = [...rows].sort((a, b) =>
        CLOSED_ORDER.indexOf(a.status) - CLOSED_ORDER.indexOf(b.status) || scoreOf(b) - scoreOf(a));
    } else {
      rows = [...rows].sort((a, b) => scoreOf(b) - scoreOf(a));
    }
    return { ...g, rows };
  }).filter((g) => g.rows.length > 0);

  const renderCard = (s: Suggestion) => {
    const ev = s.evaluation as unknown as Evaluation | null;
    const coveredDecided = !!ev?.already_covered && (s.status === "approved" || s.status === "integrating");
    return (
      <div key={s.id} className="rounded-lg border border-line bg-surface px-3 py-2">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <Chip tone="muted">{t(`sourceIntel.kindOpt.${s.kind}`)}</Chip>
              <span className="text-sm text-ink truncate" title={s.title}>{s.title}</span>
              {s.origin === "agent"
                ? <span title={t("sourceIntel.originAgent")}><Bot className="w-3.5 h-3.5 text-muted" /></span>
                : s.origin === "catalog"
                ? <span title={t("sourceIntel.originCatalog")}><Database className="w-3.5 h-3.5 text-muted" /></span>
                : <span title={t("sourceIntel.originManual")}><UserIcon className="w-3.5 h-3.5 text-faint" /></span>}
            </div>
            {s.description && <div className="text-[11px] text-muted mt-0.5">{s.description}</div>}
            <div className="text-[11px] text-faint mt-0.5">
              {s.target_axis ? `${s.target_axis}${s.target_gate ? ` · ${s.target_gate.toUpperCase()}` : ""}` : t("sourceIntel.noTarget")}
            </div>
            {coveredDecided && (
              <div className="mt-1.5 flex items-center gap-2 flex-wrap text-[11px]">
                <span title={ev?.coverage_note || ""}><Chip tone="warn">{t("sourceIntel.covered")}</Chip></span>
                <span className="text-muted">{t("sourceIntel.coveredDecidedHint")}</span>
                <button onClick={() => onStatus(s.id, "integrated")} disabled={busy === s.id}
                  className="btn btn-ghost !py-0.5 !px-2 text-xs">{t("sourceIntel.markIntegrated")}</button>
                <button onClick={() => onStatus(s.id, "deferred")} disabled={busy === s.id}
                  className="btn btn-ghost !py-0.5 !px-2 text-xs">{t("sourceIntel.markDeferred")}</button>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Chip tone={statusTone(s.status)}>{t(`sourceIntel.status.${s.status}`)}</Chip>
            <button onClick={() => onEvaluate(s.id)} disabled={busy === s.id}
              className="btn btn-ghost !py-1 !px-2 text-xs" title={t("sourceIntel.evaluateHint")}>
              <Sparkles className={`w-3.5 h-3.5 ${busy === s.id ? "animate-pulse" : ""}`} /> {t("sourceIntel.evaluate")}
            </button>
            <button onClick={() => onScaffold(s.id)} disabled={busy === s.id}
              className="btn btn-ghost !py-1 !px-2 text-xs" title={t("sourceIntel.scaffoldHint")}>
              <Wrench className={`w-3.5 h-3.5 ${busy === s.id ? "animate-pulse" : ""}`} /> {t("sourceIntel.scaffold")}
            </button>
            <select className="field !py-1 !text-xs" value={s.status} disabled={busy === s.id}
              onChange={(e) => onStatus(s.id, e.target.value as SuggestionStatus)}
              aria-label={t("sourceIntel.moveStatus")}>
              {STATUSES.map((st) => <option key={st} value={st}>{t(`sourceIntel.status.${st}`)}</option>)}
            </select>
            <button onClick={() => onDelete(s.id)} disabled={busy === s.id}
              className="btn btn-ghost !py-1 !px-2" aria-label={t("sourceIntel.delete")}>
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        {s.evaluation && <EvaluationBlock ev={s.evaluation as unknown as Evaluation} t={t} />}
        {s.integration_plan && <PlanBlock plan={s.integration_plan as unknown as IntegrationPlan} t={t} />}
      </div>
    );
  };

  return (
    <div>
      <PageHead eyebrow={t("sourceIntel.eyebrow")} title={t("sourceIntel.title")} sub={t("sourceIntel.sub")} />

      {/* Alta de sugerencia */}
      <Card className="mb-4">
        <CardHead icon={Plus} title={t("sourceIntel.newTitle")} subtitle={t("sourceIntel.newSub")} />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="text-xs text-muted">
            {t("sourceIntel.kind")}
            <select className="field mt-1" value={kind} onChange={(e) => setKind(e.target.value as SuggestionKind)}>
              {KINDS.map((k) => <option key={k} value={k}>{t(`sourceIntel.kindOpt.${k}`)}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted md:col-span-3">
            {t("sourceIntel.titleField")}
            <input className="field mt-1" value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder={t("sourceIntel.titlePlaceholder")} />
          </label>
          <label className="text-xs text-muted md:col-span-2">
            {t("sourceIntel.descField")}
            <input className="field mt-1" value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder={t("sourceIntel.descPlaceholder")} />
          </label>
          <label className="text-xs text-muted">
            {t("sourceIntel.axis")}
            <select className="field mt-1" value={axis} onChange={(e) => setAxis(e.target.value)}>
              <option value="">{t("sourceIntel.axisNone")}</option>
              {AXES.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted">
            {t("sourceIntel.gate")}
            <select className="field mt-1" value={gate} onChange={(e) => setGate(e.target.value)}>
              <option value="">{t("sourceIntel.gateNone")}</option>
              {GATES.map((g) => <option key={g} value={g}>{g.toUpperCase()}</option>)}
            </select>
          </label>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button onClick={onCreate} disabled={busy === "create" || !title.trim()} className="btn btn-primary !py-1.5">
            <Plus className="w-3.5 h-3.5" /> {t("sourceIntel.add")}
          </button>
          {msg && <span className="text-xs text-alert" role="alert">{msg}</span>}
        </div>
      </Card>

      {/* Tablero */}
      <Card>
        <CardHead icon={Compass} title={t("sourceIntel.boardTitle")}
          subtitle={t("sourceIntel.boardSub", { n: items.length })}
          right={
            <div className="flex items-center gap-2 shrink-0">
              <button onClick={onMaintenance} disabled={busy === "maintenance"}
                className="btn btn-ghost !py-1.5 shrink-0" title={t("sourceIntel.maintenanceHint")}>
                <RefreshCw className={`w-3.5 h-3.5 ${busy === "maintenance" ? "animate-spin" : ""}`} />
                {t("sourceIntel.maintenance")}
              </button>
              <button onClick={onDiscover} disabled={busy === "discover"} className="btn btn-ghost !py-1.5 shrink-0">
                <Database className={`w-3.5 h-3.5 ${busy === "discover" ? "animate-pulse" : ""}`} />
                {t("sourceIntel.discover")}
              </button>
              <button onClick={onGenerate} disabled={busy === "agent"} className="btn btn-ghost !py-1.5 shrink-0">
                <Bot className={`w-3.5 h-3.5 ${busy === "agent" ? "animate-pulse" : ""}`} />
                {t("sourceIntel.generate")}
              </button>
            </div>
          } />
        {/* Chips = filtros reales: clic para ver solo ese estado; clic de nuevo para quitar. */}
        <div className="flex flex-wrap items-center gap-2 mb-3 text-xs">
          {STATUSES.filter((s) => summary[s]).map((s) => {
            const active = filterStatus === s;
            return (
              <button key={s} onClick={() => setFilterStatus(active ? null : s)}
                aria-pressed={active}
                className={`rounded-full transition ${active ? "ring-2 ring-accent" : "opacity-80 hover:opacity-100"}`}>
                <Chip tone={statusTone(s)}>{t(`sourceIntel.status.${s}`)}: {summary[s]}</Chip>
              </button>
            );
          })}
          {filterStatus && (
            <button onClick={() => setFilterStatus(null)} className="text-faint hover:text-muted underline">
              {t("sourceIntel.clearFilter")}
            </button>
          )}
        </div>

        {state === "loading" ? (
          <Skeleton className="h-64" />
        ) : state === "error" ? (
          <StateBlock kind="error" message={t("sourceIntel.loadError")} />
        ) : items.length === 0 ? (
          <StateBlock kind="empty" message={t("sourceIntel.empty")} />
        ) : (
          <div className="flex flex-col gap-4">
            {grouped.map((g) => {
              const collapsed = g.closed && !showClosed && !filterStatus;
              return (
                <div key={g.key} className="flex flex-col gap-2">
                  <button
                    onClick={() => g.closed && setShowClosed((v) => !v)}
                    className={`flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-faint ${g.closed ? "hover:text-muted" : "cursor-default"}`}
                    aria-expanded={g.closed ? showClosed : undefined}>
                    {t(`sourceIntel.group.${g.key}`)}
                    <span className="tabular-nums">({g.rows.length})</span>
                    {g.closed && <span>{collapsed ? "▸" : "▾"}</span>}
                  </button>
                  {!collapsed && g.rows.map((s) => renderCard(s))}
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
