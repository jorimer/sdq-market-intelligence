import { useApp } from "@/shared/context/AppContext";
import { SidebarContent } from "./SidebarContent";

export function Sidebar() {
  const { sidebarCollapsed } = useApp();
  const w = sidebarCollapsed ? "w-16" : "w-[252px]";

  return (
    <aside
      className={`${w} hidden md:flex flex-col shrink-0 border-r border-line bg-surface transition-all duration-200`}
    >
      <SidebarContent collapsed={sidebarCollapsed} />
    </aside>
  );
}
