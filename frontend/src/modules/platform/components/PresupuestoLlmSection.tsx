import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Wallet, Loader2 } from "lucide-react";
import { Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { settingsApi } from "../settingsApi";

/**
 * Techo DIARIO de gasto del modelo. Admin-only (la página lo gatea).
 *
 * Existe porque el 2026-08-20 una tarea generó informes que nadie pidió por USD 127 en un
 * día: el techo solo se podía mover por variable de entorno, o sea con un redeploy — justo
 * el tiempo que no se tiene cuando el gasto ya está corriendo.
 *
 * La pantalla dice qué pasa AL LLEGAR al techo porque el riesgo va en el sentido contrario
 * al que uno teme: un techo por debajo del uso real no ahorra plata, deja clientes sin su
 * informe (la entrega premium responde 503 en vez de servir texto degradado).
 */
export function PresupuestoLlmSection() {
  const { t } = useTranslation();
  const [valor, setValor] = useState("");
  const [guardado, setGuardado] = useState<number | null>(null);
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState(false);

  async function recargar() {
    setCargando(true);
    setError("");
    try {
      const s = await settingsApi.get();
      setGuardado(s.llmDailyBudgetUsd);
      setValor(String(s.llmDailyBudgetUsd));
    } catch {
      setError(t("platform.llmBudget.loadError"));
    } finally {
      setCargando(false);
    }
  }

  useEffect(() => {
    recargar();
  }, []);

  async function guardar() {
    const n = Number(valor);
    // El backend también lo rechaza; acá se evita el viaje y se nombra el motivo.
    if (!Number.isFinite(n) || n < 0) {
      setError(t("platform.llmBudget.invalid"));
      return;
    }
    setGuardando(true);
    setError("");
    setOk(false);
    try {
      const s = await settingsApi.update({ llmDailyBudgetUsd: n });
      setGuardado(s.llmDailyBudgetUsd);
      setValor(String(s.llmDailyBudgetUsd));
      setOk(true);
    } catch {
      setError(t("platform.llmBudget.saveError"));
    } finally {
      setGuardando(false);
    }
  }

  if (cargando) return <StateBlock kind="loading" />;

  const apagado = guardado === 0;
  const sucio = String(guardado ?? "") !== valor.trim();

  return (
    <Card>
      <CardHead
        icon={Wallet}
        title={t("platform.llmBudget.title")}
        subtitle={t("platform.llmBudget.sub")}
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-40">
          <label className="block text-xs font-medium text-muted mb-1">
            {t("platform.llmBudget.label")}
          </label>
          <input
            type="number"
            min={0}
            step="1"
            inputMode="decimal"
            className="field mono"
            value={valor}
            onChange={(e) => {
              setValor(e.target.value);
              setOk(false);
            }}
          />
        </div>
        <button
          className="btn btn-primary"
          onClick={guardar}
          disabled={guardando || !sucio}
        >
          {guardando ? <Loader2 className="w-4 h-4 animate-spin" /> : t("platform.llmBudget.save")}
        </button>
        {ok && <span className="text-xs text-ok">{t("platform.llmBudget.saved")}</span>}
        {error && <span className="text-xs text-alert">{error}</span>}
      </div>

      {/* El estado vigente se DECLARA: "0" y "no configurado" se ven igual en un input. */}
      <p className="mt-3 text-xs text-muted">
        {apagado ? t("platform.llmBudget.stateOff") : t("platform.llmBudget.stateOn", { usd: guardado })}
      </p>

      <div className="mt-4 rounded-lg bg-surface2 p-3 space-y-1.5">
        <div className="text-xs font-medium text-ink">{t("platform.llmBudget.whatHappens")}</div>
        <ul className="text-xs text-muted space-y-1 list-disc pl-4">
          <li>{t("platform.llmBudget.effectPremium")}</li>
          <li>{t("platform.llmBudget.effectNarrative")}</li>
          <li>{t("platform.llmBudget.effectReset")}</li>
        </ul>
        <div className="text-xs text-muted pt-1">{t("platform.llmBudget.calibrate")}</div>
      </div>
    </Card>
  );
}
