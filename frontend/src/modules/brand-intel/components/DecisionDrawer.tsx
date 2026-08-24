import { useEffect, useState } from "react";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import {
  checkDecision,
  createDecision,
  type Feasibility,
  type SignalRow,
  type WaveRef,
} from "../api";
import { mensajeDeError } from "../../../shared/api/errores";

interface Props {
  slug: string;
  /** Waves WITH data — a baseline needs an observed value. */
  dataWaves: WaveRef[];
  /** Every wave, including future ones: the evaluation window is normally ahead. */
  allWaves: WaveRef[];
  /** Metrics that can carry a verdict — the signal filter defines that universe. */
  metrics: SignalRow[];
  focalBrand: string | null;
  onClose: () => void;
  onCreated: () => void;
}

/** Metric and cut form one composite key: the same metric appears once per segment, and
 *  keying only by metric_code would silently collapse "Santiago" into "total". */
const keyOf = (m: SignalRow) => `${m.metric_code}::${m.segment}`;

/** Register a client decision — and show, before it is committed, whether any wave
 *  will ever be able to settle it. That check is the point of the ledger. */
export function DecisionDrawer({
  slug, dataWaves, allWaves, metrics, focalBrand, onClose, onCreated,
}: Props) {
  const [title, setTitle] = useState("");
  const [rationale, setRationale] = useState("");
  const [selected, setSelected] = useState(metrics[0] ? keyOf(metrics[0]) : "");
  const [metric, segment] = selected.split("::");
  const [baselineWave, setBaselineWave] = useState(
    dataWaves[dataWaves.length - 1]?.code ?? "",
  );
  const [targetWave, setTargetWave] = useState("");
  const [threshold, setThreshold] = useState<string>("");
  const [owner, setOwner] = useState("");

  const [check, setCheck] = useState<Feasibility | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Live feasibility: re-run whenever the metric, baseline or intended movement changes.
  // Debounced so typing a threshold does not fire a request per keystroke.
  useEffect(() => {
    const value = parseFloat(threshold);
    if (!metric || !baselineWave || Number.isNaN(value) || value <= 0) {
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
  }, [slug, metric, segment, baselineWave, threshold, focalBrand]);

  const valid = title.trim().length >= 3 && metric && baselineWave;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const value = parseFloat(threshold);
      await createDecision(slug, {
        title: title.trim(),
        rationale: rationale.trim() || undefined,
        metric_code: metric,
        segment,
        brand_slug: focalBrand,
        baseline_wave_code: baselineWave,
        target_wave_code: targetWave || undefined,
        success_threshold: Number.isNaN(value) ? undefined : value,
        owner: owner.trim() || undefined,
      });
      onCreated();
    } catch (e: unknown) {
      setError(mensajeDeError(e, "No se pudo registrar la decisión."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <InsightDrawerShell
      eyebrow="Ledger de decisiones"
      title="Registrar una decisión"
      onClose={onClose}
    >
      <p className="text-sm text-muted">
        Una decisión sin métrica, línea base, ventana y umbral no puede recibir veredicto.
        El sistema comprueba, antes de comprometerla, si alguna ola podrá confirmarla.
      </p>

      <div className="space-y-4">
        <label className="block">
          <span className="text-xs font-semibold text-body">Decisión</span>
          <input
            className="field mt-1"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Reactivar el tráfico en Santo Domingo"
            autoFocus
          />
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-body">Fundamento</span>
          <textarea
            className="field mt-1"
            rows={2}
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="Qué se va a hacer y por qué."
          />
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-body">Métrica objetivo</span>
          <select
            className="field mt-1"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {metrics.map((m) => (
              <option key={keyOf(m)} value={keyOf(m)}>
                {m.label}
                {m.segment !== "total" ? ` · ${m.segment}` : ""}
              </option>
            ))}
          </select>
          <span className="text-xs text-muted">
            Solo las métricas que admiten veredicto aparecen aquí.
          </span>
        </label>

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
            <span className="text-xs text-muted">En puntos porcentuales.</span>
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-body">Responsable</span>
            <input
              className="field mt-1"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="Dirección de Marketing"
            />
          </label>
        </div>
      </div>

      {checking && <p className="text-xs text-muted">Comprobando si es evaluable…</p>}

      {check && !checking && (
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
          {busy ? "Registrando…" : "Registrar decisión"}
        </button>
        <button className="btn btn-ghost" onClick={onClose} disabled={busy}>
          Cancelar
        </button>
      </div>

      <p className="text-xs text-muted">
        Una decisión inevaluable igual se registra, con su motivo: queda para rediseñarla,
        no para volver a proponerla el trimestre siguiente.
      </p>
    </InsightDrawerShell>
  );
}
