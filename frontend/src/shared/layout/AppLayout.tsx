import { Outlet } from "react-router-dom";
import { AppProvider } from "@/shared/context/AppContext";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppLayout() {
  return (
    <AppProvider>
      <div className="h-screen flex overflow-hidden bg-canvas text-ink">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Topbar />
          <main className="flex-1 overflow-y-auto px-6 py-6">
            <Outlet />
          </main>
        </div>
      </div>
    </AppProvider>
  );
}
