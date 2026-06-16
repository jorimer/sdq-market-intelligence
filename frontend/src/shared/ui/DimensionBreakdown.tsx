import { fmtNum } from "@/shared/lib/format";

export interface DimensionRow {
  key: string;
  label: string;
  score: number;
  weight: number;
  contribution: number;
  /** Optional provenance tag (e.g. "5/5 en vivo" / "rúbrica") shown by the label. */
  tag?: { text: string; ok?: boolean };
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
            <span className="min-w-0 flex items-baseline gap-2">
              <span className="text-sm text-ink truncate">{d.label}</span>
              {d.tag && (
                <span
                  className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded-full ${
                    d.tag.ok ? "bg-ok-soft text-ok" : "bg-surface2 text-muted"
                  }`}
                >
                  {d.tag.text}
                </span>
              )}
            </span>
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
