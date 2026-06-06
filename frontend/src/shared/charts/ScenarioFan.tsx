import { useMemo } from "react";

export interface FanPoint {
  period: string;
  value: number | null;
}

interface Props {
  points: FanPoint[];
  // projected next value + uncertainty band [lo, hi]
  projection?: { value: number; band: [number, number] } | null;
  height?: number;
}

// Historical line + projected segment with a shaded uncertainty band.
// Probabilistic read (Tetlock): never a dry point estimate.
export function ScenarioFan({ points, projection, height = 200 }: Props) {
  const W = 600;
  const padX = 36;
  const padY = 16;

  const model = useMemo(() => {
    const clean = points.filter((p) => p.value != null) as { period: string; value: number }[];
    if (clean.length < 2) return null;

    const labels = clean.map((p) => p.period);
    const vals = clean.map((p) => p.value);
    const allVals = [...vals];
    if (projection) allVals.push(projection.value, projection.band[0], projection.band[1]);
    const min = Math.min(...allVals);
    const max = Math.max(...allVals);
    const span = max - min || 1;

    const n = clean.length + (projection ? 1 : 0);
    const xAt = (i: number) => padX + (i * (W - padX * 2)) / (n - 1);
    const yAt = (v: number) => padY + (1 - (v - min) / span) * (height - padY * 2);

    const linePts = vals.map((v, i) => `${xAt(i)},${yAt(v)}`).join(" ");

    let proj = null;
    if (projection) {
      const li = clean.length - 1;
      const pi = clean.length;
      proj = {
        x0: xAt(li), y0: yAt(vals[li]),
        x1: xAt(pi), y1: yAt(projection.value),
        bandHi: yAt(projection.band[1]),
        bandLo: yAt(projection.band[0]),
      };
    }
    return { labels, linePts, proj, lastPeriod: labels[labels.length - 1] };
  }, [points, projection, height]);

  if (!model) return <p className="text-sm text-muted py-6 text-center">Datos insuficientes para proyectar.</p>;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height}>
      {/* uncertainty band */}
      {model.proj && (
        <polygon
          points={`${model.proj.x0},${model.proj.y0} ${model.proj.x1},${model.proj.bandHi} ${model.proj.x1},${model.proj.bandLo}`}
          fill="var(--accent)"
          opacity={0.14}
        />
      )}
      {/* historical line */}
      <polyline points={model.linePts} fill="none" stroke="var(--c1)" strokeWidth={2} />
      {/* projected segment (dashed) */}
      {model.proj && (
        <>
          <line
            x1={model.proj.x0} y1={model.proj.y0} x2={model.proj.x1} y2={model.proj.y1}
            stroke="var(--accent)" strokeWidth={2} strokeDasharray="5 4"
          />
          <circle cx={model.proj.x1} cy={model.proj.y1} r={4} fill="var(--accent)" />
        </>
      )}
      {/* historical dots */}
      {model.linePts.split(" ").map((pt, i) => {
        const [x, y] = pt.split(",").map(Number);
        return <circle key={i} cx={x} cy={y} r={3} fill="var(--c1)" />;
      })}
    </svg>
  );
}
