import {
  Bell,
  BookOpen,
  Boxes,
  CircleDollarSign,
  Compass,
  CreditCard,
  Gauge,
  GitCompare,
  Hash,
  Landmark,
  LayoutDashboard,
  LayoutGrid,
  Leaf,
  LineChart,
  PiggyBank,
  Scale,
  ScanSearch,
  Settings,
  ShieldCheck,
  Ship,
  Sparkles,
  Store,
  Target,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  ready?: boolean; // has a real UI/connector (vs. placeholder "pronto")
  minRole?: string; // rol mínimo (jerárquico) para ver el item; ausente = todos
}

export interface NavGroup {
  key: string; // clave i18n del grupo (sidebar.groups.<key>)
  title: string; // fallback ES
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    key: "intelligence",
    title: "Ejes de inteligencia",
    items: [
      { to: "/banking-score", label: "Financiero", icon: Landmark, ready: true },
      { to: "/macro-monitor", label: "Macroeconómico", icon: LineChart, ready: true },
      { to: "/sector-intel", label: "Sectorial", icon: LayoutGrid, ready: true },
      { to: "/macro-political-risk", label: "Regulatorio & político", icon: Scale, ready: true },
      { to: "/social-dev", label: "Social & desarrollo", icon: Users, ready: true },
      { to: "/trade-intel", label: "Comercio exterior", icon: Ship, ready: true },
      { to: "/esg-climate", label: "ESG & clima", icon: Leaf, ready: true },
      { to: "/pension-intel", label: "Pensiones", icon: PiggyBank, ready: true },
      { to: "/insurance-intel", label: "Seguros", icon: ShieldCheck, ready: true },
    ],
  },
  {
    key: "data",
    title: "Datos",
    items: [
      { to: "/datos/banca", label: "Banca · SIB", icon: Landmark, ready: true },
      { to: "/datos/operaciones", label: "Operaciones", icon: Wrench, ready: true },
      { to: "/datos/macro", label: "Macro · BCRD", icon: LineChart, ready: true },
      { to: "/datos/social", label: "Social · ONE", icon: Users, ready: true },
      { to: "/datos/comercio", label: "Comercio · DGA", icon: Ship, ready: true },
      { to: "/datos/gobernanza", label: "Gobernanza · WGI", icon: Scale, ready: true },
      { to: "/datos/pensiones", label: "Pensiones · SIPEN", icon: PiggyBank, ready: true },
    ],
  },
  {
    key: "tools",
    title: "Herramientas",
    items: [
      { to: "/tools/research", label: "Research a Medida", icon: ScanSearch, ready: true },
      { to: "/brand-intel", label: "Contexto de Marca", icon: Gauge, ready: true },
      { to: "/tools/deal-scoring", label: "Deal Scoring", icon: Target },
      { to: "/tools/market-brief", label: "Market Brief", icon: Sparkles },
      { to: "/tools/proyecciones", label: "Proyecciones Macro", icon: LineChart, ready: true },
    ],
  },
  {
    key: "platform",
    title: "Plataforma",
    items: [
      { to: "/overview", label: "Resumen ejecutivo", icon: LayoutDashboard },
      { to: "/compare", label: "Comparador", icon: GitCompare },
      { to: "/methodology", label: "Metodología", icon: BookOpen },
      { to: "/catalog", label: "Catálogo de productos", icon: Store },
      { to: "/mi-plan", label: "Mi plan", icon: CreditCard },
      { to: "/mis-vigilancias", label: "Mis vigilancias", icon: Bell },
      { to: "/products", label: "Monitor de productos", icon: Boxes, minRole: "admin" },
      { to: "/source-intel", label: "Inteligencia de Fuentes", icon: Compass, minRole: "admin" },
      { to: "/settings", label: "Configuración", icon: Settings },
    ],
  },
  {
    key: "admin",
    title: "Administración",
    items: [
      { to: "/admin/users", label: "Usuarios", icon: ShieldCheck, ready: true, minRole: "admin" },
      { to: "/admin/tarifario", label: "Tarifario", icon: CircleDollarSign, ready: true, minRole: "admin" },
      { to: "/admin/pagos", label: "Pagos · PayPal", icon: CreditCard, ready: true, minRole: "admin" },
      { to: "/admin/comprobantes", label: "Comprobantes · NCF", icon: Hash, ready: true, minRole: "admin" },
    ],
  },
];

/** Flat lookup of route → breadcrumb label. */
export const ROUTE_LABELS: Record<string, string> = Object.fromEntries(
  NAV.flatMap((g) => g.items.map((i) => [i.to, i.label])),
);
