import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DollarSign, RefreshCw } from "lucide-react";
import { Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { getLlmSpend, SpendRow, SpendSummary } from "@/shared/ops/api";

/**
 * Gasto del modelo por período, dentro de la consola de Operaciones.
 *
 * Vive acá y no en una página propia porque la decisión que informa —apagar una tarea que
 * gasta— se toma en esta misma pantalla. Ver el costo de una operación lejos de su
 * interruptor obliga a cruzar dos vistas de memoria.
 *
 * El rango es de FECHAS y no una ventana de N días: la pregunta que motiva mirar esto es
 * «¿cuadra con lo que me facturaron?», y la facturación va por ciclo calendario.
 */

const hoy = () => new Date().toISOString().slice(0, 10);
const haceDias = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

/** Formatea un costo, y tolera que NO venga.
 *
 * Reventó producción con «Cannot read properties of undefined (reading 'toFixed')» y se
 * llevó puesta la consola de Operaciones entera —incluidos los interruptores para apagar
 * la tarea que estaba gastando—. Un panel de observabilidad que tumba la pantalla que
 * observa es peor que no tenerlo: llega justo cuando hace falta mirar.
 *
 * Un guion declara la ausencia; un cero la rellenaría con una cifra falsa. */
function usd(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return v >= 0.01 || v === 0 ? `$${v.toFixed(2)}` : `$${v.toFixed(4)}`;
}

/** Igual para los conteos: ausente es «—», no cero. */
function num(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? String(v) : "—";
}

/** Una tabla del reparto. `vacio` se muestra cuando no hay filas: un bloque en blanco
 *  se lee como error, y «sin gasto registrado» es una respuesta legítima. */
function Reparto({
  titulo,
  filas,
  vacio,
}: {
  titulo: string;
  filas: SpendRow[];
  vacio: string;
}) {
  const { t } = useTranslation();
  const seguras = Array.isArray(filas) ? filas : [];
  if (!seguras.length) {
    return (
      <div className="mt-4">
        <div className="text-xs text-muted uppercase tracking-wide">{titulo}</div>
        <div className="mt-2 text-sm text-muted">{vacio}</div>
      </div>
    );
  }
  return (
    <div className="mt-4">
      <div className="text-xs text-muted uppercase tracking-wide">{titulo}</div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-line">
              <th className="py-1.5 px-2 font-medium">{t("ops.spend.key")}</th>
              <th className="py-1.5 px-2 font-medium text-right">{t("ops.spend.cost")}</th>
              <th className="py-1.5 px-2 font-medium text-right">{t("ops.spend.generated")}</th>
              <th className="py-1.5 px-2 font-medium text-right">{t("ops.spend.cached")}</th>
            </tr>
          </thead>
          <tbody>
            {seguras.map((f, i) => (
              <tr key={f.clave ?? i} className="border-b border-line/60 last:border-0">
                {/* Se muestra el PRODUCTO; la clave técnica queda en el título emergente
                    porque es lo que hace falta para depurar, y una etiqueta que la
                    reemplace del todo convierte dos minutos de investigación en veinte. */}
                <td className="py-2 px-2 text-ink" title={f.clave ?? ""}>
                  {f.etiqueta ?? f.clave ?? "—"}
                </td>
                <td className="py-2 px-2 mono text-body tabular-nums text-right">
                  {usd(f.costo_usd)}
                </td>
                <td className="py-2 px-2 mono text-body tabular-nums text-right">
                  {num(f.generaciones_reales)}
                </td>
                {/* Los HIT se muestran aparte: sin ellos no se distingue «nadie lo pidió»
                    de «lo pidieron y la caché lo absorbió», que es lo que justifica la caché. */}
                <td className="py-2 px-2 mono text-muted tabular-nums text-right">
                  {num(f.hits_de_cache)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SpendPanel() {
  const { t } = useTranslation();
  const [desde, setDesde] = useState(haceDias(30));
  const [hasta, setHasta] = useState(hoy());
  const [data, setData] = useState<SpendSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getLlmSpend(desde, hasta));
    } catch {
      setError(t("ops.spend.error"));
    } finally {
      setLoading(false);
    }
  }, [desde, hasta, t]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const rangoInvertido = desde > hasta;

  return (
    <Card>
      <CardHead icon={DollarSign} title={t("ops.spend.title")} subtitle={t("ops.spend.sub")} />

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted">
          {t("ops.spend.from")}
          <input
            type="date"
            value={desde}
            max={hasta}
            onChange={(e) => setDesde(e.target.value)}
            className="mt-1 block rounded border border-line bg-transparent px-2 py-1 text-sm text-ink"
          />
        </label>
        <label className="text-xs text-muted">
          {t("ops.spend.to")}
          <input
            type="date"
            value={hasta}
            min={desde}
            onChange={(e) => setHasta(e.target.value)}
            className="mt-1 block rounded border border-line bg-transparent px-2 py-1 text-sm text-ink"
          />
        </label>
        <button
          type="button"
          onClick={() => void cargar()}
          disabled={loading || rangoInvertido}
          className="inline-flex items-center gap-1.5 rounded border border-line px-3 py-1.5 text-sm text-body disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          {t("ops.spend.refresh")}
        </button>
      </div>

      {rangoInvertido && (
        <div className="mt-2 text-sm text-alert">{t("ops.spend.invertedRange")}</div>
      )}

      {error && <StateBlock kind="error" title={error} />}

      {data && !error && (
        <>
          <div className="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-1">
            <div>
              <div className="text-xs text-muted uppercase tracking-wide">
                {t("ops.spend.total")}
              </div>
              <div className="mono text-2xl text-ink tabular-nums">
                {usd(data.costo_total_usd)}
              </div>
            </div>
            <div className="text-sm text-muted">
              {t("ops.spend.calls", { count: data.llamadas_totales ?? 0 })}
            </div>
          </div>

          {/* El disparador va PRIMERO: es la columna que responde si lo pidió alguien o si
              una tarea agendada lo generó sola, que es la pregunta por la que existe. */}
          <Reparto
            titulo={t("ops.spend.byTrigger")}
            filas={data.por_disparador}
            vacio={t("ops.spend.empty")}
          />
          <Reparto
            titulo={t("ops.spend.byPurpose")}
            filas={data.por_motivo}
            vacio={t("ops.spend.empty")}
          />
          <Reparto
            titulo={t("ops.spend.byModule")}
            filas={data.por_modulo}
            vacio={t("ops.spend.empty")}
          />

          <p className="mt-4 text-xs text-muted">{t("ops.spend.note")}</p>
        </>
      )}
    </Card>
  );
}
