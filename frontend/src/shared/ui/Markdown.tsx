import { Fragment, type ReactNode } from "react";

/** Minimal, dependency-free Markdown renderer for the AI insights (consistent,
 * simple output: #/##/### headings, **bold**, ---, -/* and N. lists, GFM tables,
 * paragraphs). Renders React elements (no HTML injection), styled with design tokens. */

function inline(text: string): ReactNode[] {
  // bold (**…**); everything else is plain text
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i} className="font-semibold text-ink">{part.slice(2, -2)}</strong>;
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/** Split a GFM table row "| a | b |" into trimmed cells ["a", "b"]. */
function splitRow(line: string): string[] {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  return t.split("|").map((c) => c.trim());
}

/** A GFM table separator row: |---|:--:|---| (cells of -, optional : for align). */
function isSeparatorRow(line: string): boolean {
  const t = line.trim();
  if (!t.includes("-") || !t.includes("|")) return false;
  return splitRow(t).every((c) => /^:?-{1,}:?$/.test(c));
}

export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let para: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushPara = () => {
    if (para.length) {
      blocks.push(
        <p key={blocks.length} className="text-sm text-body leading-relaxed">{inline(para.join(" "))}</p>,
      );
      para = [];
    }
  };
  const flushList = () => {
    if (list) {
      const Tag = list.ordered ? "ol" : "ul";
      blocks.push(
        <Tag key={blocks.length} className={`text-sm text-body leading-relaxed pl-5 space-y-1 ${list.ordered ? "list-decimal" : "list-disc"}`}>
          {list.items.map((it, i) => <li key={i}>{inline(it)}</li>)}
        </Tag>,
      );
      list = null;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) { flushPara(); flushList(); continue; }

    // GFM table: header row with pipes + a separator row immediately after.
    if (line.includes("|") && i + 1 < lines.length && isSeparatorRow(lines[i + 1])) {
      flushPara(); flushList();
      const headers = splitRow(line);
      const rows: string[][] = [];
      let j = i + 2;
      while (j < lines.length && lines[j].trim().includes("|") && lines[j].trim() !== "") {
        rows.push(splitRow(lines[j]));
        j++;
      }
      i = j - 1; // resume after the table
      blocks.push(
        <div key={blocks.length} className="overflow-x-auto">
          <table className="w-full text-sm my-1">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-line">
                {headers.map((h, k) => (
                  <th key={k} className={`py-2 px-2 font-medium ${k === 0 ? "" : "text-right"}`}>{inline(h)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((cells, r) => (
                <tr key={r} className="border-b border-line/60">
                  {cells.map((c, k) => (
                    <td key={k} className={`py-2 px-2 ${k === 0 ? "text-body" : "text-right mono text-ink tabular-nums"}`}>{inline(c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (/^---+$/.test(line)) { flushPara(); flushList(); blocks.push(<hr key={blocks.length} className="border-line my-1" />); continue; }

    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) {
      flushPara(); flushList();
      const lvl = h[1].length;
      const cls = lvl === 1 ? "text-sm font-semibold text-ink font-display"
        : lvl === 2 ? "text-sm font-semibold text-ink"
        : "text-xs font-semibold text-muted uppercase tracking-wide";
      blocks.push(<div key={blocks.length} className={`${cls} mt-1`}>{inline(h[2])}</div>);
      continue;
    }

    const ol = line.match(/^\d+[.)]\s+(.*)$/);
    const ul = line.match(/^[-*]\s+(.*)$/);
    if (ol || ul) {
      flushPara();
      const ordered = Boolean(ol);
      if (!list || list.ordered !== ordered) { flushList(); list = { ordered, items: [] }; }
      list.items.push((ol ? ol[1] : ul![1]));
      continue;
    }

    flushList();
    para.push(line);
  }
  flushPara();
  flushList();

  return <div className={`space-y-2 ${className}`}>{blocks}</div>;
}
