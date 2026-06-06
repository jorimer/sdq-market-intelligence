import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface DataPoint {
  period: string;
  score: number;
  tier?: string;
}

interface Props {
  data: DataPoint[];
}

export function TrendChart({ data }: Props) {
  if (data.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
        <XAxis dataKey="period" tick={{ fontSize: 11, fill: "var(--muted)" }} stroke="var(--border-strong)" />
        <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "var(--muted)" }} stroke="var(--border-strong)" />
        <Tooltip
          formatter={(value: number) => [value.toFixed(1), "Score"]}
          contentStyle={{
            borderRadius: 8,
            fontSize: 12,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            color: "var(--ink)",
          }}
        />
        <Line
          type="monotone"
          dataKey="score"
          stroke="var(--c1)"
          strokeWidth={2}
          dot={{ fill: "var(--c1)", r: 4 }}
          activeDot={{ r: 6 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
