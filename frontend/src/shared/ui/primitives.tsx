import { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Inbox,
  Loader2,
  Lock,
  Construction,
} from "lucide-react";
import { Band, Tone, toneBadgeClass, toneVar } from "@/shared/lib/bands";
import { deltaTone, fmtDelta } from "@/shared/lib/format";

/* ── Eyebrow / kicker ─────────────────────────────────────────── */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="mono text-[10px] font-semibold uppercase tracking-[0.16em] text-accent">
      {children}
    </div>
  );
}

/* ── Card ─────────────────────────────────────────────────────── */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`card p-5 ${className}`}>{children}</div>;
}

/* ── CardHead — one-line title rule (§8) ──────────────────────── */
export function CardHead({
  icon: Icon,
  title,
  subtitle,
  right,
}: {
  icon?: LucideIcon;
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 mb-4">
      {Icon && (
        <span className="shrink-0 grid place-items-center w-[30px] h-[30px] rounded-[9px] bg-accent-soft text-accent">
          <Icon size={16} />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <h3 className="font-display text-[15px] font-bold text-ink truncate">
          {title}
        </h3>
        {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}

/* ── PageHead ─────────────────────────────────────────────────── */
export function PageHead({
  eyebrow,
  title,
  sub,
  right,
}: {
  eyebrow?: ReactNode;
  title: string;
  sub?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-4 mb-6">
      <div className="min-w-0 flex-1">
        {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
        <h1 className="font-display text-[26px] font-extrabold leading-tight text-ink truncate mt-1">
          {title}
        </h1>
        {sub && <p className="text-sm text-body mt-1.5 max-w-2xl">{sub}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}

/* ── Chip ─────────────────────────────────────────────────────── */
export function Chip({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: Tone;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${toneBadgeClass(
        tone,
      )}`}
    >
      {children}
    </span>
  );
}

/* ── BandBadge ────────────────────────────────────────────────── */
export function BandBadge({ band }: { band: Band }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${toneBadgeClass(
        band.tone,
      )}`}
    >
      {band.label}
    </span>
  );
}

/* ── Delta ────────────────────────────────────────────────────── */
export function Delta({ value, digits = 1 }: { value: number | null | undefined; digits?: number }) {
  const tone = deltaTone(value);
  const color =
    tone === "ok" ? "text-ok" : tone === "alert" ? "text-alert" : "text-muted";
  return <span className={`mono text-xs font-semibold ${color}`}>{fmtDelta(value, digits)}</span>;
}

/* ── StatTile ─────────────────────────────────────────────────── */
export function StatTile({
  label,
  value,
  delta,
  unit,
}: {
  label: string;
  value: ReactNode;
  delta?: number | null;
  unit?: string;
}) {
  return (
    <div className="card p-4">
      <div className="text-xs text-muted truncate">{label}</div>
      <div className="flex items-baseline gap-2 mt-1.5">
        <span className="font-display text-2xl font-extrabold text-ink mono">{value}</span>
        {unit && <span className="text-xs text-muted">{unit}</span>}
      </div>
      {delta != null && (
        <div className="mt-1">
          <Delta value={delta} />
        </div>
      )}
    </div>
  );
}

/* ── Gauge (SVG arc, token colors) ────────────────────────────── */
export function Gauge({
  score,
  band,
  size = 132,
}: {
  score: number | null | undefined;
  band: Band;
  size?: number;
}) {
  const stroke = 10;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score ?? 0)) / 100;
  const color = toneVar(band.tone);
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--grid)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c - pct * c}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-[28px] font-extrabold text-ink mono leading-none">
          {score == null ? "—" : score.toFixed(1)}
        </span>
        <span className="text-[11px] text-muted mt-1">de 100</span>
      </div>
    </div>
  );
}

/* ── Skeleton ─────────────────────────────────────────────────── */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-[10px] bg-surface2 ${className}`} />;
}

/* ── Tabs (controlled) ────────────────────────────────────────── */
export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`px-3.5 py-2 text-sm font-medium -mb-px border-b-2 transition ${
            active === t.id
              ? "border-accent text-accent-ink"
              : "border-transparent text-muted hover:text-ink"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/* ── StateBlock — the four canonical states (+ "soon") ────────── */
type StateKind = "loading" | "empty" | "error" | "forbidden" | "soon";

const STATE_META: Record<StateKind, { icon: LucideIcon; title: string }> = {
  loading: { icon: Loader2, title: "Cargando…" },
  empty: { icon: Inbox, title: "Sin datos" },
  error: { icon: AlertTriangle, title: "Error al cargar" },
  forbidden: { icon: Lock, title: "Sin permiso" },
  soon: { icon: Construction, title: "En construcción" },
};

export function StateBlock({
  kind,
  title,
  message,
  action,
}: {
  kind: StateKind;
  title?: string;
  message?: string;
  action?: ReactNode;
}) {
  const meta = STATE_META[kind];
  const Icon = meta.icon;
  return (
    <div className="card p-10 flex flex-col items-center justify-center text-center">
      <span className="grid place-items-center w-12 h-12 rounded-xl bg-surface2 text-muted mb-3">
        <Icon size={22} className={kind === "loading" ? "animate-spin" : ""} />
      </span>
      <div className="font-display text-[15px] font-bold text-ink whitespace-nowrap">
        {title ?? meta.title}
      </div>
      {message && <p className="text-sm text-muted mt-1.5 max-w-md">{message}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* ── Loading skeleton grid for axis pages ─────────────────────── */
export function LoadingGrid() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}
