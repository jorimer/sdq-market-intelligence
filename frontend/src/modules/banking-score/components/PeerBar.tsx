import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface PeerEntry {
  bank_name: string;
  score: number;
}

interface Props {
  data: PeerEntry[];
  highlightBank?: string;
}

export function PeerBar({ data, highlightBank }: Props) {
  const chartData = data.map((d) => ({
    ...d,
    fill: d.bank_name === highlightBank ? "var(--c1)" : "var(--border-strong)",
  }));

  return (
    <ResponsiveContainer width="100%" height={Math.max(200, data.length * 40)}>
      <BarChart data={chartData} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
        <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11, fill: "var(--muted)" }} stroke="var(--border-strong)" />
        <YAxis
          type="category"
          dataKey="bank_name"
          width={100}
          tick={{ fontSize: 11, fill: "var(--muted)" }}
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
        <Bar dataKey="score" radius={[0, 4, 4, 0]}>
          {chartData.map((entry, index) => (
            <rect key={index} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
