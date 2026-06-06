import { useLocation } from "react-router-dom";
import { PanelLeft, Moon, Sun, LogOut } from "lucide-react";
import { useApp, PERIODS, SCOPES, Scope } from "@/shared/context/AppContext";
import { useAuth } from "@/shared/auth/AuthContext";
import { ROUTE_LABELS } from "./nav";

function Breadcrumbs() {
  const { pathname } = useLocation();
  // Match the longest registered route prefix.
  const base = "/" + pathname.split("/").filter(Boolean).slice(0, 1).join("/");
  const label = ROUTE_LABELS[pathname] || ROUTE_LABELS[base] || "Inicio";
  return (
    <div className="flex items-center gap-1.5 text-sm min-w-0">
      <span className="font-display font-bold text-ink">SDQ·MIP</span>
      <span className="text-faint">›</span>
      <span className="text-body truncate">{label}</span>
    </div>
  );
}

export function Topbar() {
  const { dark, toggleDark, period, setPeriod, scope, setScope, toggleSidebar } = useApp();
  const { user, logout } = useAuth();

  return (
    <header className="h-[58px] shrink-0 flex items-center gap-3 px-4 border-b border-line bg-surface">
      <button
        onClick={toggleSidebar}
        className="shrink-0 grid place-items-center w-9 h-9 rounded-[10px] text-muted hover:bg-surface2 hover:text-ink transition"
        title="Colapsar menú"
      >
        <PanelLeft size={18} />
      </button>

      <div className="min-w-0 flex-1">
        <Breadcrumbs />
      </div>

      {/* Period */}
      <select
        value={period}
        onChange={(e) => setPeriod(e.target.value)}
        className="field mono !w-auto !py-1.5 text-xs shrink-0"
        title="Período"
      >
        {PERIODS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>

      {/* Scope */}
      <select
        value={scope}
        onChange={(e) => setScope(e.target.value as Scope)}
        className="field !w-auto !py-1.5 text-xs shrink-0 hidden sm:block"
        title="Ámbito"
      >
        {SCOPES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      {/* Theme toggle */}
      <button
        onClick={toggleDark}
        className="shrink-0 grid place-items-center w-9 h-9 rounded-[10px] text-muted hover:bg-surface2 hover:text-ink transition"
        title={dark ? "Modo claro" : "Modo oscuro"}
      >
        {dark ? <Sun size={18} /> : <Moon size={18} />}
      </button>

      {/* Profile */}
      <div className="flex items-center gap-2 shrink-0 pl-2 border-l border-line">
        <div className="hidden md:block text-right leading-tight">
          <div className="text-xs font-semibold text-ink truncate max-w-[140px]">
            {user?.full_name || "Usuario"}
          </div>
          <div className="text-[10px] text-muted mono uppercase">{user?.role}</div>
        </div>
        <button
          onClick={logout}
          className="grid place-items-center w-9 h-9 rounded-[10px] text-muted hover:bg-alert-soft hover:text-alert transition"
          title="Cerrar sesión"
        >
          <LogOut size={17} />
        </button>
      </div>
    </header>
  );
}
