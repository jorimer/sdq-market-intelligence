import { fmtNum } from "@/shared/lib/format";

export interface DimensionRow {
  key: string;
  label: string;
  score: number;
  weight: number;
  contribution: number;
}

/**
 * Weighted sub-component / dimension meters — the explainable breakdown shared by
 * every index axis (IRMP, IAI, IDM, IRC).  Bar width = score; the weight and
 * contribution make the composite reconstructable by hand.
 */
export function DimensionBreakdown({ rows }: { rows: DimensionRow[] }) {
  return (
    <div className="space-y-3.5">
      {rows.map((d) => (
        <div key={d.key}>
          <div className="flex items-baseline justify-between gap-3 mb-1">
            <span className="text-sm text-ink min-w-0 truncate">{d.label}</span>
            <span className="shrink-0 mono text-xs text-muted">
              peso {Math.round(d.weight * 100)}% · aporta {fmtNum(d.contribution, 1)}
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <div className="flex-1 h-2 rounded-full bg-surface2 overflow-hidden">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${Math.max(0, Math.min(100, d.score))}%` }}
              />
            </div>
            <span className="shrink-0 mono text-sm font-semibold text-ink w-11 text-right">
              {fmtNum(d.score, 1)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
