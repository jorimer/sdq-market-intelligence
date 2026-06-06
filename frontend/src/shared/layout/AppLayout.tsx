import { Outlet } from "react-router-dom";
import { AppProvider, useApp } from "@/shared/context/AppContext";
import { Sidebar } from "./Sidebar";
import { SidebarContent } from "./SidebarContent";
import { Topbar } from "./Topbar";
import { CommandPalette } from "@/shared/ui/CommandPalette";

function MobileDrawer() {
  const { mobileOpen, setMobileOpen } = useApp();
  if (!mobileOpen) return null;
  return (
    <div className="md:hidden fixed inset-0 z-40">
      <div className="absolute inset-0 bg-ink/40" onClick={() => setMobileOpen(false)} />
      <aside className="absolute left-0 top-0 bottom-0 w-[252px] flex flex-col bg-surface border-r border-line shadow-pop">
        <SidebarContent onNavigate={() => setMobileOpen(false)} />
      </aside>
    </div>
  );
}

function Shell() {
  return (
    <div className="h-screen flex overflow-hidden bg-canvas text-ink">
      <Sidebar />
      <MobileDrawer />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Topbar />
        <main className="flex-1 overflow-y-auto px-6 py-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}

export function AppLayout() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
