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
        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
        <XAxis dataKey="period" tick={{ fontSize: 11 }} />
        <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
        <Tooltip
          formatter={(value: number) => [value.toFixed(1), "Score"]}
          contentStyle={{ borderRadius: 8, fontSize: 12 }}
        />
        <Line
          type="monotone"
          dataKey="score"
          stroke="#2B6CB0"
          strokeWidth={2}
          dot={{ fill: "#2B6CB0", r: 4 }}
          activeDot={{ r: 6 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
