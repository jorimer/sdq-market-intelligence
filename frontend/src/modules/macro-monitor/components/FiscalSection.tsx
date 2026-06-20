import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Landmark, RefreshCw } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { FiscalPulse, getFiscalPulse } from "../api";

function fmtMM(v: number | null | undefined): string {
  return v == null ? "—" : `RD$ ${fmtNum(v, 0)} MM`;
}

/** Merge ingresos + gastos timelines into one series for the last `months` points. */
function mergeTimeline(p: FiscalPulse, months = 36) {
  const ing = new Map((p.eo?.ingresos ?? []).map((d) => [d.period, d.value]));
  const gas = new Map((p.eo?.gastos ?? []).map((d) => [d.period, d.value]));
  const periods = Array.from(new Set([...ing.keys(), ...gas.keys()])).sort();
  return periods
    .slice(-months)
    .map((period) => ({ period, ingresos: ing.get(period) ?? null, gastos: gas.get(period) ?? null }));
}

export function FiscalSection() {
  const [pulse, setPulse] = useState<FiscalPulse | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  const load = useCallback(async () => {
    try {
      setPulse(await getFiscalPulse());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (status === "loading") return <StateBlock kind="loading" message="Cargando pulso fiscal…" />;
  if (status === "error") return <StateBlock kind="error" message="No se pudo cargar el pulso fiscal." />;
  if (!pulse?.has_data) {
    return (
      <StateBlock
        kind="empty"
        message="Aún no hay datos fiscales. Corre la operación «Sincronizar pulso fiscal» en Operaciones."
      />
    );
  }

  const data = mergeTimeline(pulse);
  const lat = pulse.eo_latest ?? { ingresos: null, gastos: null, balance_global: null };
  const deficit = lat.balance_global ?? null;
  const groups = pulse.recaudacion?.groups ?? [];
  const maxRec = Math.max(1, ...groups.map((g) => g.value));

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile label={`Ingresos · ${pulse.latest_period ?? ""}`} value={fmtMM(lat.ingresos)} />
        <StatTile label="Gastos" value={fmtMM(lat.gastos)} />
        <StatTile label="Balance global (déficit)" value={fmtMM(deficit)} />
        <StatTile
          label="Cobertura"
          value={pulse.period_range ? `${pulse.period_range[0]} – ${pulse.period_range[1]}` : "—"}
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHead
            icon={Landmark}
            title="Ingresos vs gastos del Gobierno Central"
            subtitle={`Estado de Operaciones (Hacienda) · ${pulse.eo_unit ?? "RD$ MM"} · últimos 36 meses`}
          />
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
              <XAxis dataKey="period" tick={{ fontSize: 10, fill: "var(--muted)" }} stroke="var(--border-strong)" minTickGap={28} />
              <YAxis tick={{ fontSize: 10, fill: "var(--muted)" }} stroke="var(--border-strong)" width={56}
                tickFormatter={(v: number) => fmtNum(v / 1000, 0) + "k"} />
              <Tooltip
                formatter={(v: number, name: string) => [fmtMM(v), name === "ingresos" ? "Ingresos" : "Gastos"]}
                contentStyle={{ borderRadius: 8, fontSize: 12, background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}
              />
              <Line type="monotone" dataKey="ingresos" stroke="var(--c1)" strokeWidth={2} dot={false} connectNulls />
              <Line type="monotone" dataKey="gastos" stroke="var(--c4)" strokeWidth={2} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex items-center gap-4 mt-1 text-xs text-muted">
            <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 rounded" style={{ background: "var(--c1)" }} /> Ingresos</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 rounded" style={{ background: "var(--c4)" }} /> Gastos</span>
          </div>
        </Card>

        <Card>
          <CardHead
            icon={Landmark}
            title="Recaudación por impuesto"
            subtitle={`DGII · ${pulse.recaudacion?.period ?? ""} · ${pulse.recaudacion_unit ?? "RD$"}`}
          />
          {groups.length ? (
            <div className="space-y-2.5 mt-1">
              {groups.map((g) => (
                <div key={g.slug} className="flex items-center gap-3">
                  <span className="w-28 shrink-0 text-xs text-ink truncate" title={g.label}>{g.label}</span>
                  <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
                    <div className="h-full rounded-full bg-accent" style={{ width: `${(g.value / maxRec) * 100}%` }} />
                  </div>
                  <span className="w-24 shrink-0 text-right mono text-xs text-body tabular-nums">
                    {fmtNum(g.value / 1e6, 0)} MM
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <StateBlock kind="empty" message="Sin recaudación DGII." />
          )}
        </Card>
      </div>

      <p className="flex items-center gap-1.5 text-xs text-faint">
        <RefreshCw className="w-3 h-3" /> Fuente: Ministerio de Hacienda (Estado de Operaciones) + DGII (recaudación). Mensual.
      </p>
    </div>
  );
}
