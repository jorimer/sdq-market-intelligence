import { Routes, Route, Navigate } from "react-router-dom";
import { ProtectedRoute } from "@/shared/auth/ProtectedRoute";
import { AppLayout } from "@/shared/layout/AppLayout";
import { LoginPage } from "@/shared/auth/LoginPage";
import { ErrorBoundary } from "@/shared/components/ErrorBoundary";
import { PlaceholderPage } from "@/shared/ui/PlaceholderPage";

// Banking Score (Eje 1) — existing screens
import { DashboardPage } from "@/modules/banking-score/pages/DashboardPage";
import { ScoringPage } from "@/modules/banking-score/pages/ScoringPage";
import { RankingsPage } from "@/modules/banking-score/pages/RankingsPage";
import { ReportsPage } from "@/modules/banking-score/pages/ReportsPage";
import { DataPage } from "@/modules/banking-score/pages/DataPage";
import { ModelPage } from "@/modules/banking-score/pages/ModelPage";
import { ScenariosPage } from "@/modules/banking-score/pages/ScenariosPage";
import { ComparePage } from "@/modules/banking-score/pages/ComparePage";
import { FideicomisosPage } from "@/modules/banking-score/pages/FideicomisosPage";
import { BankingScoreLayout } from "@/modules/banking-score/components/BankingScoreLayout";

// Macro Monitor (Eje 2) — new canonical pattern
import { MacroMonitorPage } from "@/modules/macro-monitor/pages/MacroMonitorPage";
// Publicaciones BCRD (informes oficiales + digest IA)
import { PublicationsPage } from "@/modules/publications/pages/PublicationsPage";
// Macro-Political Risk (Eje 4)
import { MacroPoliticalRiskPage } from "@/modules/macro-political-risk/pages/MacroPoliticalRiskPage";
// Sector Intel (Eje 3)
import { SectorIntelPage } from "@/modules/sector-intel/pages/SectorIntelPage";
// Social Dev (Eje 5)
import { SocialDevPage } from "@/modules/social-dev/pages/SocialDevPage";
// Trade Intel (Eje 6)
import { TradeIntelPage } from "@/modules/trade-intel/pages/TradeIntelPage";
// ESG & Climate (Eje 7)
import { EsgClimatePage } from "@/modules/esg-climate/pages/EsgClimatePage";
// Plataforma
import { OverviewPage } from "@/modules/platform/pages/OverviewPage";
import { MetodologiaPage } from "@/modules/platform/pages/MetodologiaPage";
import { ConfiguracionPage } from "@/modules/platform/pages/ConfiguracionPage";

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          {/* Eje 1 — Financiero (sub-navegación por pestañas) */}
          <Route path="/banking-score" element={<BankingScoreLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="scoring" element={<ScoringPage />} />
            <Route path="rankings" element={<RankingsPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="model" element={<ModelPage />} />
            <Route path="scenarios" element={<ScenariosPage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route path="fideicomisos" element={<FideicomisosPage />} />
          </Route>
          {/* Old data route → moved to the Datos section */}
          <Route path="/banking-score/data" element={<Navigate to="/datos/banca" replace />} />

          {/* Datos — extracción por sector (multi-fuente) */}
          <Route path="/datos" element={<Navigate to="/datos/banca" replace />} />
          <Route path="/datos/banca" element={<DataPage />} />
          <Route
            path="/datos/macro"
            element={<PlaceholderPage title="Datos · Macroeconómico (BCRD)" sub="Conector en construcción. Configure la fuente en Configuración → APIs de Benchmarks por Sector." />}
          />
          <Route
            path="/datos/social"
            element={<PlaceholderPage title="Datos · Social (ONE)" sub="Conector en construcción. Configure la fuente en Configuración → APIs de Benchmarks por Sector." />}
          />
          <Route
            path="/datos/comercio"
            element={<PlaceholderPage title="Datos · Comercio (UN Comtrade)" sub="Conector en construcción. Configure la fuente en Configuración → APIs de Benchmarks por Sector." />}
          />
          <Route
            path="/datos/gobernanza"
            element={<PlaceholderPage title="Datos · Gobernanza (WGI)" sub="Conector en construcción. Configure la fuente en Configuración → APIs de Benchmarks por Sector." />}
          />

          {/* Eje 2 — Macroeconómico */}
          <Route path="/macro-monitor" element={<MacroMonitorPage />} />

          {/* Publicaciones BCRD — informes oficiales + digest IA */}
          <Route path="/publicaciones-bcrd" element={<PublicationsPage />} />

          {/* Ejes 3-7 — UI en construcción (backend disponible) */}
          <Route path="/sector-intel" element={<SectorIntelPage />} />
          <Route path="/macro-political-risk" element={<MacroPoliticalRiskPage />} />
          <Route path="/social-dev" element={<SocialDevPage />} />
          <Route path="/trade-intel" element={<TradeIntelPage />} />
          <Route path="/esg-climate" element={<EsgClimatePage />} />

          {/* Herramientas */}
          <Route
            path="/tools/deal-scoring"
            element={<PlaceholderPage title="Deal Scoring" sub="Evaluación integral de oportunidades." />}
          />
          <Route
            path="/tools/market-brief"
            element={<PlaceholderPage title="Market Brief" sub="Resúmenes de mercado generados con Claude." />}
          />

          {/* Plataforma */}
          <Route path="/overview" element={<OverviewPage />} />
          <Route
            path="/compare"
            element={<PlaceholderPage title="Comparador" sub="Comparación lado a lado de entidades, sectores y países." />}
          />
          <Route path="/methodology" element={<MetodologiaPage />} />
          <Route path="/settings" element={<ConfiguracionPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/banking-score" replace />} />
      </Routes>
    </ErrorBoundary>
  );
}
