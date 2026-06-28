import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Compass, Plus, Trash2, Bot, User as UserIcon, Sparkles } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import {
  listSuggestions, createSuggestion, setSuggestionStatus, deleteSuggestion, evaluateSuggestion,
  runResearchAgent, agentStatus,
  type Suggestion, type SuggestionStatus, type SuggestionKind, type Evaluation,
} from "../api";

const KINDS: SuggestionKind[] = ["source", "info_type", "sector"];
const STATUSES: SuggestionStatus[] = [
  "proposed", "evaluating", "evaluated", "approved",
  "integrating", "integrated", "rejected", "deferred",
];
const AXES = ["banking", "macro", "trade", "tourism", "free_zones", "energy",
  "telecom", "construction", "agribusiness", "esg", "pension"];
const GATES = ["g1", "g2", "g3", "g4", "g5"];

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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function EvaluationBlock({ ev, t }: { ev: Evaluation; t: any }) {
  return (
    <div className="mt-2 rounded-md border border-line bg-surface2/50 px-3 py-2">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="font-medium text-ink">{t("sourceIntel.evalScore")}</span>
        <span className="mono tabular-nums text-ink">{Math.round((ev.score ?? 0) * 100)}%</span>
        <Chip tone={recTone(ev.recommendation)}>{t(`sourceIntel.rec.${ev.recommendation}`)}</Chip>
        {ev.gate_closed && <Chip tone="muted">{ev.gate_closed.toUpperCase()}</Chip>}
        <Chip tone={ev.method === "ai" ? "ok" : "muted"}>{t(`sourceIntel.method.${ev.method}`)}</Chip>
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

export function SourceIntelPage() {
  const { t } = useTranslation();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");

  const [items, setItems] = useState<Suggestion[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState<string | null>(null);
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

  if (!isAdmin) {
    return (
      <div>
        <PageHead eyebrow={t("sourceIntel.eyebrow")} title={t("sourceIntel.title")} sub={t("sourceIntel.sub")} />
        <StateBlock kind="forbidden" message={t("sourceIntel.forbidden")} />
      </div>
    );
  }

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
            <button onClick={onGenerate} disabled={busy === "agent"} className="btn btn-ghost !py-1.5 shrink-0">
              <Bot className={`w-3.5 h-3.5 ${busy === "agent" ? "animate-pulse" : ""}`} />
              {t("sourceIntel.generate")}
            </button>
          } />
        <div className="flex flex-wrap gap-2 mb-3 text-xs">
          {STATUSES.filter((s) => summary[s]).map((s) => (
            <Chip key={s} tone={statusTone(s)}>{t(`sourceIntel.status.${s}`)}: {summary[s]}</Chip>
          ))}
        </div>

        {state === "loading" ? (
          <Skeleton className="h-64" />
        ) : state === "error" ? (
          <StateBlock kind="error" message={t("sourceIntel.loadError")} />
        ) : items.length === 0 ? (
          <StateBlock kind="empty" message={t("sourceIntel.empty")} />
        ) : (
          <div className="flex flex-col gap-2">
            {items.map((s) => (
              <div key={s.id} className="rounded-lg border border-line bg-surface px-3 py-2">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Chip tone="muted">{t(`sourceIntel.kindOpt.${s.kind}`)}</Chip>
                      <span className="text-sm text-ink truncate" title={s.title}>{s.title}</span>
                      {s.origin === "agent"
                        ? <span title={t("sourceIntel.originAgent")}><Bot className="w-3.5 h-3.5 text-muted" /></span>
                        : <span title={t("sourceIntel.originManual")}><UserIcon className="w-3.5 h-3.5 text-faint" /></span>}
                    </div>
                    {s.description && <div className="text-[11px] text-muted mt-0.5">{s.description}</div>}
                    <div className="text-[11px] text-faint mt-0.5">
                      {s.target_axis ? `${s.target_axis}${s.target_gate ? ` · ${s.target_gate.toUpperCase()}` : ""}` : t("sourceIntel.noTarget")}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Chip tone={statusTone(s.status)}>{t(`sourceIntel.status.${s.status}`)}</Chip>
                    <button onClick={() => onEvaluate(s.id)} disabled={busy === s.id}
                      className="btn btn-ghost !py-1 !px-2 text-xs" title={t("sourceIntel.evaluateHint")}>
                      <Sparkles className={`w-3.5 h-3.5 ${busy === s.id ? "animate-pulse" : ""}`} /> {t("sourceIntel.evaluate")}
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
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
