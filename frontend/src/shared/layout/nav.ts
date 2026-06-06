import {
  Landmark,
  LineChart,
  LayoutGrid,
  Scale,
  Users,
  Ship,
  Leaf,
  Target,
  Sparkles,
  LayoutDashboard,
  GitCompare,
  BookOpen,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  ready?: boolean; // axis has a real UI (vs. placeholder)
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    title: "Ejes de inteligencia",
    items: [
      { to: "/banking-score", label: "Financiero", icon: Landmark, ready: true },
      { to: "/macro-monitor", label: "Macroeconómico", icon: LineChart, ready: true },
      { to: "/sector-intel", label: "Sectorial", icon: LayoutGrid, ready: true },
      { to: "/macro-political-risk", label: "Regulatorio & político", icon: Scale, ready: true },
      { to: "/social-dev", label: "Social & desarrollo", icon: Users, ready: true },
      { to: "/trade-intel", label: "Comercio exterior", icon: Ship, ready: true },
      { to: "/esg-climate", label: "ESG & clima", icon: Leaf, ready: true },
    ],
  },
  {
    title: "Herramientas",
    items: [
      { to: "/tools/deal-scoring", label: "Deal Scoring", icon: Target },
      { to: "/tools/market-brief", label: "Market Brief", icon: Sparkles },
    ],
  },
  {
    title: "Plataforma",
    items: [
      { to: "/overview", label: "Resumen ejecutivo", icon: LayoutDashboard },
      { to: "/compare", label: "Comparador", icon: GitCompare },
      { to: "/methodology", label: "Metodología", icon: BookOpen },
      { to: "/settings", label: "Configuración", icon: Settings },
    ],
  },
];

/** Flat lookup of route → breadcrumb label. */
export const ROUTE_LABELS: Record<string, string> = Object.fromEntries(
  NAV.flatMap((g) => g.items.map((i) => [i.to, i.label])),
);
