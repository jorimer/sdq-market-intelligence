import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";

type Scope = "RD" | "Centroamérica" | "Caribe";

interface AppState {
  dark: boolean;
  toggleDark: () => void;
  period: string;
  setPeriod: (p: string) => void;
  scope: Scope;
  setScope: (s: Scope) => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
}

const AppCtx = createContext<AppState | null>(null);

const PERIODS = ["2025-Q2", "2025-Q1", "2024-Q4", "2025", "2024"];
const SCOPES: Scope[] = ["RD", "Centroamérica", "Caribe"];

function initDark(): boolean {
  const saved = localStorage.getItem("sdq_dark");
  if (saved != null) return saved === "1";
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState<boolean>(initDark);
  const [period, setPeriodState] = useState<string>(
    () => localStorage.getItem("sdq_period") || "2025-Q2",
  );
  const [scope, setScopeState] = useState<Scope>(
    () => (localStorage.getItem("sdq_scope") as Scope) || "RD",
  );
  const [sidebarCollapsed, setCollapsed] = useState<boolean>(
    () => localStorage.getItem("sdq_sidebar") === "1",
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("sdq_dark", dark ? "1" : "0");
  }, [dark]);

  const setPeriod = (p: string) => {
    setPeriodState(p);
    localStorage.setItem("sdq_period", p);
  };
  const setScope = (s: Scope) => {
    setScopeState(s);
    localStorage.setItem("sdq_scope", s);
  };
  const toggleSidebar = () => {
    setCollapsed((c) => {
      localStorage.setItem("sdq_sidebar", !c ? "1" : "0");
      return !c;
    });
  };

  return (
    <AppCtx.Provider
      value={{
        dark,
        toggleDark: () => setDark((d) => !d),
        period,
        setPeriod,
        scope,
        setScope,
        sidebarCollapsed,
        toggleSidebar,
      }}
    >
      {children}
    </AppCtx.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(AppCtx);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}

export { PERIODS, SCOPES };
export type { Scope };
