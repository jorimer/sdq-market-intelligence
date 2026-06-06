import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { NAV } from "@/shared/layout/nav";

interface Entry {
  to: string;
  label: string;
  group: string;
  icon: typeof NAV[number]["items"][number]["icon"];
}

const ENTRIES: Entry[] = NAV.flatMap((g) =>
  g.items.map((i) => ({ to: i.to, label: i.label, group: g.title, icon: i.icon })),
);

/** Global ⌘K / Ctrl-K command palette for navigation. */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ENTRIES;
    return ENTRIES.filter(
      (e) => e.label.toLowerCase().includes(q) || e.group.toLowerCase().includes(q),
    );
  }, [query]);

  if (!open) return null;

  const go = (to: string) => {
    navigate(to);
    setOpen(false);
  };

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && results[active]) {
      go(results[active].to);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4 bg-ink/40 backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-lg rounded-2xl bg-surface border border-line shadow-pop overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 px-4 border-b border-line">
          <Search className="w-4 h-4 text-faint shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActive(0); }}
            onKeyDown={onListKey}
            placeholder="Buscar pantallas…"
            className="w-full bg-transparent outline-none text-sm text-ink py-3.5"
          />
          <kbd className="mono text-[10px] text-faint border border-line rounded px-1.5 py-0.5 shrink-0">ESC</kbd>
        </div>
        <ul className="max-h-80 overflow-y-auto py-2">
          {results.length === 0 ? (
            <li className="px-4 py-6 text-sm text-muted text-center">Sin resultados</li>
          ) : (
            results.map((e, i) => {
              const Icon = e.icon;
              return (
                <li key={e.to}>
                  <button
                    onMouseEnter={() => setActive(i)}
                    onClick={() => go(e.to)}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-left text-sm ${
                      i === active ? "bg-accent-soft text-accent-ink" : "text-body hover:bg-surface2"
                    }`}
                  >
                    <Icon size={16} className="shrink-0" />
                    <span className="flex-1 truncate">{e.label}</span>
                    <span className="mono text-[10px] text-faint">{e.group}</span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
      </div>
    </div>
  );
}
