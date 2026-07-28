import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

/** Sub-navigation for the Financiero (banking-score) axis.
 *
 * The eje has eight routed screens; the global sidebar only links the axis
 * root, so without this tab bar the inner pages (Datos, Rankings, …) were
 * unreachable by clicking. Rendered as a layout around the banking routes.
 */
const TABS: { to: string; key: string; end?: boolean }[] = [
  { to: "/banking-score", key: "dashboard", end: true },
  { to: "/banking-score/rankings", key: "rankings" },
  { to: "/banking-score/scoring", key: "scoring" },
  { to: "/banking-score/scenarios", key: "scenarios" },
  { to: "/banking-score/compare", key: "compare" },
  { to: "/banking-score/fideicomisos", key: "fideicomisos" },
  { to: "/banking-score/model", key: "model" },
  { to: "/banking-score/validation", key: "validation" },
  { to: "/banking-score/historico", key: "historico" },
  { to: "/banking-score/reports", key: "reports" },
];

export function BankingScoreLayout() {
  const { t } = useTranslation();
  return (
    <div>
      <nav className="flex gap-1 overflow-x-auto border-b border-line mb-5 -mt-1">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              `shrink-0 px-3.5 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                isActive
                  ? "border-accent text-accent"
                  : "border-transparent text-muted hover:text-ink"
              }`
            }
          >
            {t(`banking.tab.${tab.key}`)}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
