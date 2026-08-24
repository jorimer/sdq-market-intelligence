import { useEffect, useMemo, useState } from "react";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import {
  adoptPlanGoal,
  checkDecision,
  type Feasibility,
  type PlanGoal,
  type SignalRow,
  type WaveRef,
} from "../api";
import { mensajeDeError } from "../../../shared/api/errores";

interface Props {
  slug: string;
  planId: string;
  goal: PlanGoal;
  dataWaves: WaveRef[];
  allWaves: WaveRef[];
  metrics: SignalRow[];
  focalBrand: string | null;
  onClose: () => void;
  onAdopted: () => void;
}

/**
 * El portón humano de una meta del plan: el lector la PROPUSO, aquí una persona la
 * ADOPTA como decisión del ledger — ajustando lo que haga falta antes de comprometerla.
 *
 * Tres cosas lo distinguen del alta manual: los campos llegan pre-llenados con lo que
 * el documento declara (la meta literal queda como fundamento con su página), la medida
 * puede ser una FUENTE EXTERNA cuando el tracker no la mide, y el corte admite texto
 * libre — un plan legítimamente compromete cortes que el libro aún no trae, y esa
 * decisión se registra inevaluable con su motivo en vez de quedar fuera del sistema.
 */
export function PlanReviewDrawer({
  slug, planId, goal, dataWaves, allWaves, metrics, focalBrand, onClose, onAdopted,
}: Props) {
  const isExternalDefault = !goal.metric_code;
  const [mode, setMode] = useState<"tracker" | "externa">(
    isExternalDefault ? "externa" : "tracker",
  );
  const [title, setTitle] = useState(goal.claim.slice(0, 300));
  const [metric, setMetric] = useState(goal.metric_code ?? metrics[0]?.metric_code ?? "");
  const [segment, setSegment] = useState(goal.segment || "total");
  const [external, setExternal] = useState(goal.measure_source ?? "");
  const [baselineWave, setBaselineWave] = useState(
    dataWaves[dataWaves.length - 1]?.code ?? "",
  );
  const [targetWave, setTargetWave] = useState("");
  const [threshold, setThreshold] = useState<string>(
    goal.expected_move != null ? String(goal.expected_move) : "",
  );
  const [owner, setOwner] = useState(goal.owner_declared ?? "");

  const [check, setCheck] = useState<Feasibility | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const metricOptions = useMemo(() => {
    const seen = new Set<string>();
    return metrics.filter((m) => {
      if (seen.has(m.metric_code)) return false;
      seen.add(m.metric_code);
      return true;
    });
  }, [metrics]);

  // Factibilidad en vivo — solo para medidas del tracker: una fuente externa no tiene
  // aritmética muestral que comprobar (queda registrada con su nota, siempre).
  useEffect(() => {
    if (mode === "externa" || !metric || !baselineWave) {
      setCheck(null);
      return;
    }
    const value = parseFloat(threshold);
    if (Number.isNaN(value) || value <= 0) {
      setCheck(null);
      return;
    }
    setChecking(true);
    const t = setTimeout(() => {
      checkDecision(slug, {
        metric_code: metric,
        baseline_wave_code: baselineWave,
        segment,
        brand_slug: focalBrand,
        success_threshold: value,
      })
        .then(setCheck)
        .catch(() => setCheck(null))
        .finally(() => setChecking(false));
    }, 350);
    return () => {
      clearTimeout(t);
      setChecking(false);
    };
  }, [slug, mode, metric, segment, baselineWave, threshold, focalBrand]);

  const valid =
    title.trim().length >= 3 &&
    baselineWave &&
    (mode === "tracker" ? !!metric : external.trim().length >= 3);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const value = parseFloat(threshold);
      await adoptPlanGoal(slug, planId, goal.id, {
        title: title.trim(),
        metric_code: mode === "tracker" ? metric : null,
        external_measure: mode === "externa" ? external.trim() : null,
        segment: segment.trim() || "total",
        brand_slug: mode === "tracker" ? focalBrand : null,
        baseline_wave_code: baselineWave,
        target_wave_code: targetWave || undefined,
        success_threshold: Number.isNaN(value) ? undefined : value,
        owner: owner.trim() || undefined,
      });
      onAdopted();
    } catch (e: unknown) {
      setError(mensajeDeError(e, "No se pudo adoptar la meta."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <InsightDrawerShell
      eyebrow="Plan del cliente"
      title="Adoptar una meta como decisión"
      onClose={onClose}
    >
      <blockquote className="rounded-lg bg-panel p-3 text-sm text-body">
        «{goal.claim}»
        {goal.page_number ? (
          <span className="text-xs text-muted"> — página {goal.page_number}</span>
        ) : null}
      </blockquote>

      <div className="space-y-4">
        <label className="block">
          <span className="text-xs font-semibold text-body">Decisión</span>
          <input
            className="field mt-1"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
        </label>

        <div className="flex gap-2">
          <button
            className={`btn ${mode === "tracker" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setMode("tracker")}
            type="button"
          >
            Se mide con el tracker
          </button>
          <button
            className={`btn ${mode === "externa" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setMode("externa")}
            type="button"
          >
            Fuente externa
          </button>
        </div>

        {mode === "tracker" ? (
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs font-semibold text-body">Métrica</span>
              <select
                className="field mt-1"
                value={metric}
                onChange={(e) => setMetric(e.target.value)}
              >
                {goal.metric_code &&
                  !metricOptions.some((m) => m.metric_code === goal.metric_code) && (
                    <option value={goal.metric_code}>{goal.metric_code}</option>
                  )}
                {metricOptions.map((m) => (
                  <option key={m.metric_code} value={m.metric_code}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-body">Corte</span>
              <input
                className="field mt-1"
                value={segment}
                onChange={(e) => setSegment(e.target.value)}
                placeholder="total"
              />
              <span className="text-xs text-muted">
                Un corte sin datos en el libro queda inevaluable hasta cargarlo.
              </span>
            </label>
          </div>
        ) : (
          <label className="block">
            <span className="text-xs font-semibold text-body">Fuente externa</span>
            <input
              className="field mt-1"
              value={external}
              onChange={(e) => setExternal(e.target.value)}
              placeholder="Analytics de plataformas sociales"
            />
            <span className="text-xs text-muted">
              El tracker no la evalúa: la decisión queda visible con su fuente, y el
              veredicto requiere ese dato del cliente.
            </span>
          </label>
        )}

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs font-semibold text-body">Ola base</span>
            <select
              className="field mt-1"
              value={baselineWave}
              onChange={(e) => setBaselineWave(e.target.value)}
            >
              {dataWaves.map((w) => (
                <option key={w.code} value={w.code}>
                  {w.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-body">Ola de evaluación</span>
            <select
              className="field mt-1"
              value={targetWave}
              onChange={(e) => setTargetWave(e.target.value)}
            >
              <option value="">Sin definir</option>
              {allWaves.map((w) => (
                <option key={w.code} value={w.code}>
                  {w.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs font-semibold text-body">Movimiento esperado</span>
            <input
              className="field mt-1 mono"
              type="number"
              step="0.5"
              min="0"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              placeholder="8"
            />
            <span className="text-xs text-muted">
              En puntos del indicador (o de la fuente externa).
            </span>
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-body">Responsable</span>
            <input
              className="field mt-1"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder={goal.owner_declared ?? "Dirección de Marketing"}
            />
          </label>
        </div>
      </div>

      {checking && <p className="text-xs text-muted">Comprobando si es evaluable…</p>}

      {check && !checking && mode === "tracker" && (
        <div
          className={`rounded-lg p-3 text-sm ${
            check.feasible ? "bg-ok-soft text-ok" : "bg-alert-soft text-alert"
          }`}
        >
          <div className="font-semibold">
            {check.feasible ? "Decisión evaluable" : "Decisión inevaluable"}
          </div>
          <p className="mt-1">{check.reason}</p>
          {check.baseline_value != null && (
            <p className="mt-1 mono text-xs">
              Línea base {fmtPct(check.baseline_value)}
              {check.baseline_base_n ? ` · n=${check.baseline_base_n}` : ""}
              {check.detectable_threshold != null
                ? ` · mínimo detectable ±${fmtNum(check.detectable_threshold)} pp`
                : ""}
            </p>
          )}
        </div>
      )}

      {error && <p className="text-sm rounded-lg bg-alert-soft text-alert p-3">{error}</p>}

      <div className="flex items-center gap-2">
        <button className="btn btn-primary" disabled={!valid || busy} onClick={submit}>
          {busy ? "Adoptando…" : "Adoptar al ledger"}
        </button>
        <button className="btn btn-ghost" onClick={onClose} disabled={busy}>
          Cancelar
        </button>
      </div>

      <p className="text-xs text-muted">
        Una meta inevaluable igual se adopta, con su motivo: el informe la muestra en
        «El plan bajo el instrumento» junto a lo que falta para poder medirla.
      </p>
    </InsightDrawerShell>
  );
}
