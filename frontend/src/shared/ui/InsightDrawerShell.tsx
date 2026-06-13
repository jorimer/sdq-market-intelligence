import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

interface Props {
  /** Muted context line above the title (e.g. "Entidad · 2026-03-31"). */
  eyebrow?: ReactNode;
  title: string;
  onClose: () => void;
  /** Escape handler. Defaults to onClose; override to preserve nested-drawer
   * semantics (e.g. close the inner indicator drawer before the entity drawer). */
  onEscape?: () => void;
  children: ReactNode;
}

/** Right-side drawer shell shared by the banking-score insight drawers: overlay,
 * panel, sticky header with eyebrow/title/close, and the `p-5 space-y-6` body.
 * Domain content (badges, charts, peers, AI section) is passed as `children`. */
export function InsightDrawerShell({ eyebrow, title, onClose, onEscape, children }: Props) {
  const escRef = useRef<() => void>(onEscape ?? onClose);
  escRef.current = onEscape ?? onClose;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && escRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Cerrar" onClick={onClose} className="absolute inset-0 bg-ink/40 backdrop-blur-sm" />
      <div className="relative w-full max-w-lg h-full bg-surface border-l border-line shadow-pop overflow-y-auto">
        <div className="sticky top-0 z-10 bg-surface border-b border-line px-5 py-4 flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {eyebrow !== undefined && <div className="text-xs text-muted truncate">{eyebrow}</div>}
            <h2 className="text-base font-semibold text-ink font-display truncate">{title}</h2>
          </div>
          <button onClick={onClose} className="btn btn-ghost shrink-0 -mr-2" aria-label="Cerrar">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5 space-y-6">{children}</div>
      </div>
    </div>
  );
}
