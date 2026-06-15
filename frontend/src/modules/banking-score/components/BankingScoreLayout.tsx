import { NavLink, Outlet } from "react-router-dom";

/** Sub-navigation for the Financiero (banking-score) axis.
 *
 * The eje has eight routed screens; the global sidebar only links the axis
 * root, so without this tab bar the inner pages (Datos, Rankings, …) were
 * unreachable by clicking. Rendered as a layout around the banking routes.
 */
const TABS: { to: string; label: string; end?: boolean }[] = [
  { to: "/banking-score", label: "Dashboard", end: true },
  { to: "/banking-score/rankings", label: "Rankings" },
  { to: "/banking-score/scoring", label: "Scoring" },
  { to: "/banking-score/scenarios", label: "Escenarios" },
  { to: "/banking-score/compare", label: "Comparar" },
  { to: "/banking-score/fideicomisos", label: "Fideicomisos" },
  { to: "/banking-score/model", label: "Modelo" },
  { to: "/banking-score/validation", label: "Validación" },
  { to: "/banking-score/reports", label: "Reportes" },
];

export function BankingScoreLayout() {
  return (
    <div>
      <nav className="flex gap-1 overflow-x-auto border-b border-line mb-5 -mt-1">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              `shrink-0 px-3.5 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                isActive
                  ? "border-accent text-accent"
                  : "border-transparent text-muted hover:text-ink"
              }`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
