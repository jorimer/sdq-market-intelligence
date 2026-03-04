import {
  Radar,
  RadarChart as ReRadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from "recharts";
import { useTranslation } from "react-i18next";
import type { SubComponents } from "@/types";

interface Props {
  data: SubComponents;
  comparisonData?: SubComponents;
  comparisonLabel?: string;
  size?: number;
}

const AXES: (keyof SubComponents)[] = [
  "solidez",
  "calidad",
  "eficiencia",
  "liquidez",
  "diversificacion",
];

export function RadarChart({ data, comparisonData, comparisonLabel }: Props) {
  const { t } = useTranslation();

  const chartData = AXES.map((key) => ({
    axis: t(`sub.${key}`),
    value: data[key] ?? 0,
    ...(comparisonData ? { comparison: comparisonData[key] ?? 0 } : {}),
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ReRadarChart data={chartData}>
        <PolarGrid stroke="#E2E8F0" />
        <PolarAngleAxis
          dataKey="axis"
          tick={{ fontSize: 11, fill: "#4A5568" }}
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 100]}
          tick={{ fontSize: 10 }}
        />
        <Radar
          name="Score"
          dataKey="value"
          stroke="#2B6CB0"
          fill="#2B6CB0"
          fillOpacity={0.25}
          strokeWidth={2}
        />
        {comparisonData && (
          <Radar
            name={comparisonLabel ?? "Comparison"}
            dataKey="comparison"
            stroke="#E53E3E"
            fill="#E53E3E"
            fillOpacity={0.1}
            strokeWidth={2}
            strokeDasharray="4 4"
          />
        )}
      </ReRadarChart>
    </ResponsiveContainer>
  );
}
