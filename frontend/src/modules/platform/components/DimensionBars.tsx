import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface DimensionDatum {
  label: string;
  score: number;
}

/**
 * Barras horizontales de las dimensiones de un índice (score 0–100), theme-aware
 * (colores vía tokens CSS). Refleja en la vista online el mismo gráfico de marca que
 * el PDF/Word del reporte. Espejo del patrón de `PeerBar`.
 */
export function DimensionBars({ title, data }: { title: string; data: DimensionDatum[] }) {
  if (!data || data.length < 2) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] uppercase tracking-wide text-faint">{title}</div>
      <ResponsiveContainer width="100%" height={Math.max(140, data.length * 38)}>
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 36, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, 100]}
            tick={{ fontSize: 11, fill: "var(--muted)" }}
            stroke="var(--border-strong)"
          />
          <YAxis
            type="category"
            dataKey="label"
            width={132}
            tick={{ fontSize: 11, fill: "var(--ink)" }}
            stroke="var(--border-strong)"
          />
          <Tooltip
            formatter={(value: number) => [value.toFixed(1), "Score"]}
            contentStyle={{
              borderRadius: 8,
              fontSize: 12,
              background: "var(--surface)",
              border: "1px solid var(--border)",
              color: "var(--ink)",
            }}
            cursor={{ fill: "var(--surface-2)" }}
          />
          <Bar
            dataKey="score"
            fill="var(--c1)"
            radius={[0, 4, 4, 0]}
            maxBarSize={18}
            isAnimationActive={false}
          >
            <LabelList
              dataKey="score"
              position="right"
              formatter={(v: number) => v.toFixed(0)}
              style={{ fontSize: 11, fill: "var(--muted)" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
