import { useMemo } from "react";
import { fmtPct } from "@/shared/lib/format";

export interface TreemapItem {
  label: string;
  value: number;
  share?: number;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
  item: TreemapItem;
}

const PALETTE = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

// Recursive binary squarify: split into two groups ~half the value, alternating
// by the longer side → squarish tiles. Good for the small N we render.
function squarify(items: TreemapItem[], r: Omit<Rect, "item">): Rect[] {
  if (items.length === 1) return [{ ...r, item: items[0] }];
  const total = items.reduce((s, i) => s + i.value, 0);
  let acc = 0;
  let i = 0;
  while (i < items.length - 1 && acc + items[i].value < total / 2) {
    acc += items[i].value;
    i++;
  }
  const a = items.slice(0, i + 1);
  const b = items.slice(i + 1);
  const aSum = a.reduce((s, it) => s + it.value, 0);
  const horizontal = r.w >= r.h;
  if (horizontal) {
    const wA = (r.w * aSum) / total;
    return [
      ...squarify(a, { x: r.x, y: r.y, w: wA, h: r.h }),
      ...squarify(b, { x: r.x + wA, y: r.y, w: r.w - wA, h: r.h }),
    ];
  }
  const hA = (r.h * aSum) / total;
  return [
    ...squarify(a, { x: r.x, y: r.y, w: r.w, h: hA }),
    ...squarify(b, { x: r.x, y: r.y + hA, w: r.w, h: r.h - hA }),
  ];
}

export function Treemap({ items, height = 220 }: { items: TreemapItem[]; height?: number }) {
  const W = 600;
  const rects = useMemo(() => {
    const clean = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
    if (!clean.length) return [];
    return squarify(clean, { x: 0, y: 0, w: W, h: height });
  }, [items, height]);

  if (!rects.length) return <p className="text-sm text-muted py-6 text-center">Sin datos.</p>;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} preserveAspectRatio="none">
      {rects.map((r, idx) => {
        const big = r.w > 70 && r.h > 30;
        return (
          <g key={r.item.label}>
            <rect
              x={r.x + 1}
              y={r.y + 1}
              width={Math.max(0, r.w - 2)}
              height={Math.max(0, r.h - 2)}
              rx={6}
              fill={PALETTE[idx % PALETTE.length]}
              opacity={0.88}
            />
            {big && (
              <>
                <text x={r.x + 10} y={r.y + 20} fill="#fff" fontSize="12" fontWeight="600">
                  {r.item.label.length > 22 ? r.item.label.slice(0, 21) + "…" : r.item.label}
                </text>
                <text x={r.x + 10} y={r.y + 36} fill="#fff" fontSize="11" opacity={0.85} className="mono">
                  {r.item.share != null ? fmtPct(r.item.share * 100, 1) : r.item.value.toFixed(0)}
                </text>
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}
