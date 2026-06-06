import { fmtNum } from "@/shared/lib/format";

export interface HeatmapData {
  rows: string[];
  cols: string[];
  // values[rowIdx][colIdx], 0-100 (null = missing)
  values: (number | null)[][];
}

// Sequential single-hue heatmap (accent), opacity ∝ value. Theme-aware via vars;
// the number is overlaid so opacity doesn't dim the text.
export function Heatmap({ data, rowLabelWidth = 150 }: { data: HeatmapData; rowLabelWidth?: number }) {
  const { rows, cols, values } = data;
  return (
    <div className="overflow-x-auto">
      <table className="border-separate" style={{ borderSpacing: 4 }}>
        <thead>
          <tr>
            <th style={{ width: rowLabelWidth }} />
            {cols.map((c) => (
              <th key={c} className="text-[11px] font-medium text-muted px-1 pb-1 align-bottom">
                <div className="truncate" style={{ maxWidth: 90 }}>{c}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={r}>
              <td className="text-sm text-ink pr-2 truncate" style={{ maxWidth: rowLabelWidth }}>{r}</td>
              {cols.map((_, ci) => {
                const v = values[ri]?.[ci];
                const op = v == null ? 0 : 0.12 + 0.85 * (Math.max(0, Math.min(100, v)) / 100);
                return (
                  <td key={ci} className="p-0">
                    <div className="relative grid place-items-center rounded-[6px] w-[64px] h-[40px] bg-surface2">
                      {v != null && (
                        <div
                          className="absolute inset-0 rounded-[6px]"
                          style={{ background: "var(--accent)", opacity: op }}
                        />
                      )}
                      <span className="relative mono text-xs font-semibold text-ink">
                        {v == null ? "—" : fmtNum(v, 0)}
                      </span>
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
