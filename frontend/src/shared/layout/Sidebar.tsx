import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  LayoutDashboard,
  Calculator,
  Trophy,
  FileText,
  Database,
  Brain,
  SlidersHorizontal,
  GitCompare,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useState } from "react";

const NAV_ITEMS = [
  { to: "/banking-score", icon: LayoutDashboard, key: "nav.dashboard", end: true },
  { to: "/banking-score/scoring", icon: Calculator, key: "nav.scoring" },
  { to: "/banking-score/rankings", icon: Trophy, key: "nav.rankings" },
  { to: "/banking-score/reports", icon: FileText, key: "nav.reports" },
  { to: "/banking-score/data", icon: Database, key: "nav.data" },
  { to: "/banking-score/model", icon: Brain, key: "nav.model" },
  { to: "/banking-score/scenarios", icon: SlidersHorizontal, key: "nav.scenarios" },
  { to: "/banking-score/compare", icon: GitCompare, key: "nav.compare" },
];

export function Sidebar() {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`bg-primary text-white flex flex-col transition-all duration-300 ${
        collapsed ? "w-16" : "w-60"
      }`}
    >
      <div className="p-4 flex items-center justify-between border-b border-primary-light/20">
        {!collapsed && (
          <span className="text-sm font-semibold uppercase tracking-wider">
            {t("nav.bankingScore")}
          </span>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1 hover:bg-primary-light rounded transition-colors"
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <ChevronLeft className="w-4 h-4" />
          )}
        </button>
      </div>

      <nav className="flex-1 py-2">
        {NAV_ITEMS.map(({ to, icon: Icon, key, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                isActive
                  ? "bg-primary-light/30 text-white border-r-2 border-white"
                  : "text-white/70 hover:text-white hover:bg-primary-light/10"
              }`
            }
          >
            <Icon className="w-5 h-5 flex-shrink-0" />
            {!collapsed && <span>{t(key)}</span>}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
