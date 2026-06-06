import { NavLink } from "react-router-dom";
import { useApp } from "@/shared/context/AppContext";
import { NAV } from "./nav";

function ArcMark() {
  return (
    <svg viewBox="0 0 32 32" width="28" height="28" className="shrink-0">
      <rect width="32" height="32" rx="9" fill="var(--accent)" />
      <g transform="translate(16 16)">
        <circle
          r="8"
          fill="none"
          stroke="white"
          strokeWidth="3.4"
          strokeLinecap="round"
          strokeDasharray="50.2"
          strokeDashoffset="13"
          transform="rotate(-90)"
        />
        <circle cy="-8" r="2.4" fill="white" />
      </g>
    </svg>
  );
}

export function Sidebar() {
  const { sidebarCollapsed } = useApp();
  const w = sidebarCollapsed ? "w-16" : "w-[252px]";

  return (
    <aside
      className={`${w} hidden md:flex flex-col shrink-0 border-r border-line bg-surface transition-all duration-200`}
    >
      {/* Brand */}
      <div className="h-[58px] flex items-center gap-2.5 px-4 border-b border-line">
        <ArcMark />
        {!sidebarCollapsed && (
          <span className="font-display text-[17px] font-extrabold text-ink tracking-tight">
            SDQ<span className="text-muted">·MIP</span>
          </span>
        )}
      </div>

      {/* Groups */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-5">
        {NAV.map((group) => (
          <div key={group.title}>
            {!sidebarCollapsed && (
              <div className="mono text-[10px] font-semibold uppercase tracking-[0.14em] text-faint px-2.5 mb-1.5">
                {group.title}
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    title={item.label}
                    className={({ isActive }) =>
                      `relative flex items-center gap-3 rounded-[10px] px-2.5 py-2 text-sm font-medium transition ${
                        isActive
                          ? "bg-accent-soft text-accent-ink"
                          : "text-body hover:bg-surface2 hover:text-ink"
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full bg-accent" />
                        )}
                        <Icon
                          size={17}
                          className={isActive ? "text-accent shrink-0" : "shrink-0"}
                        />
                        {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                      </>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}
