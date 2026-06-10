import { Fragment, type ReactNode } from "react";

/** Minimal, dependency-free Markdown renderer for the AI insights (consistent,
 * simple output: #/##/### headings, **bold**, ---, -/* and N. lists, paragraphs).
 * Renders React elements (no HTML injection), styled with design tokens. */

function inline(text: string): ReactNode[] {
  // bold (**…**); everything else is plain text
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i} className="font-semibold text-ink">{part.slice(2, -2)}</strong>;
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
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

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { flushPara(); flushList(); continue; }
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
