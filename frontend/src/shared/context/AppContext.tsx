import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import client from "@/shared/api/client";

type Scope = "RD" | "Centroamérica" | "Caribe";

interface AppState {
  dark: boolean;
  toggleDark: () => void;
  period: string;
  setPeriod: (p: string) => void;
  /** Períodos seleccionables (más reciente primero); se cargan del backend. */
  periods: string[];
  scope: Scope;
  setScope: (s: Scope) => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  mobileOpen: boolean;
  setMobileOpen: (v: boolean) => void;
}

const AppCtx = createContext<AppState | null>(null);

/** Fallback estático (más reciente primero) si el backend no responde.
 *  La lista real se deriva en runtime de los períodos con datos (ver AppProvider). */
const PERIODS = [
  "2026-Q1", "2025-Q4", "2025-Q3", "2025-Q2", "2025-Q1",
  "2024-Q4", "2024-Q3", "2024-Q2", "2024-Q1",
];
const SCOPES: Scope[] = ["RD", "Centroamérica", "Caribe"];

const _QUARTER_END: Record<string, string> = { Q1: "03-31", Q2: "06-30", Q3: "09-30", Q4: "12-31" };

/** Map a global period label ("2025-Q2" / "2025") to a period-end ISO date. */
export function periodToDate(period: string): string {
  const m = period.match(/^(\d{4})-(Q[1-4])$/);
  if (m) return `${m[1]}-${_QUARTER_END[m[2]]}`;
  if (/^\d{4}$/.test(period)) return `${period}-12-31`;
  return period;
}

/** Map a period-end ISO date ("2026-03-31") to a global period label ("2026-Q1").
 *  Inverso de periodToDate; devuelve null si no es una fecha ISO reconocible. */
export function dateToPeriod(iso: string): string | null {
  const m = iso.match(/^(\d{4})-(\d{2})-\d{2}$/);
  if (!m) return null;
  const q = Math.ceil(parseInt(m[2], 10) / 3); // 1..4
  if (q < 1 || q > 4) return null;
  return `${m[1]}-Q${q}`;
}

function initDark(): boolean {
  const saved = localStorage.getItem("sdq_dark");
  if (saved != null) return saved === "1";
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState<boolean>(initDark);
  // Key versionada (v2): migra a la lista dinámica y arranca en el período más
  // reciente disponible (antes quedaba fijo en un default estático desfasado).
  const [period, setPeriodState] = useState<string>(
    () => localStorage.getItem("sdq_period_v2") || PERIODS[0],
  );
  const [periods, setPeriods] = useState<string[]>(PERIODS);
  const [scope, setScopeState] = useState<Scope>(
    () => (localStorage.getItem("sdq_scope") as Scope) || "RD",
  );
  const [sidebarCollapsed, setCollapsed] = useState<boolean>(
    () => localStorage.getItem("sdq_sidebar") === "1",
  );
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("sdq_dark", dark ? "1" : "0");
  }, [dark]);

  // Cargar los períodos reales (con datos) del backend; el motor del Eje 1 es la
  // fuente de verdad de períodos. Si falla, se queda con el fallback estático.
  useEffect(() => {
    let active = true;
    client
      .get<{ periods: string[] }>("/banking-score/periods")
      .then(({ data }) => {
        if (!active) return;
        const labels: string[] = [];
        for (const iso of data.periods ?? []) {
          const label = dateToPeriod(iso);
          if (label && !labels.includes(label)) labels.push(label);
        }
        if (!labels.length) return; // sin datos → conservar fallback
        setPeriods(labels);
        // Si el período guardado ya no existe (o no había), saltar al más reciente.
        setPeriodState((cur) => {
          if (labels.includes(cur)) return cur;
          localStorage.setItem("sdq_period_v2", labels[0]);
          return labels[0];
        });
      })
      .catch(() => {
        /* sin red/permiso → fallback estático, no romper el shell */
      });
    return () => {
      active = false;
    };
  }, []);

  const setPeriod = (p: string) => {
    setPeriodState(p);
    localStorage.setItem("sdq_period_v2", p);
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
        periods,
        scope,
        setScope,
        sidebarCollapsed,
        toggleSidebar,
        mobileOpen,
        setMobileOpen,
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
