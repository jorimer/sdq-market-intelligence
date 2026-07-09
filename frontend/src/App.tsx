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
import { OperacionesPage } from "@/modules/banking-score/pages/OperacionesPage";
import { ModelPage } from "@/modules/banking-score/pages/ModelPage";
import { ValidationPage } from "@/modules/banking-score/pages/ValidationPage";
import { ScenariosPage } from "@/modules/banking-score/pages/ScenariosPage";
import { ComparePage } from "@/modules/banking-score/pages/ComparePage";
import { FideicomisosPage } from "@/modules/banking-score/pages/FideicomisosPage";
import { BankingScoreLayout } from "@/modules/banking-score/components/BankingScoreLayout";

// Macro Monitor (Eje 2) — new canonical pattern
import { MacroMonitorPage } from "@/modules/macro-monitor/pages/MacroMonitorPage";
// Datos · Macroeconómico (BCRD) — consola operativa (API + Excel + Publicaciones)
import { DatosMacroPage } from "@/modules/macro-monitor/pages/DatosMacroPage";
// Datos · Social (ONE), Comercio (DGA), Gobernanza (WGI) — consolas por fuente
import { DatosSocialPage } from "@/modules/social-dev/pages/DatosSocialPage";
import { DatosComercioPage } from "@/modules/trade-intel/pages/DatosComercioPage";
import { DatosGobernanzaPage } from "@/modules/macro-political-risk/pages/DatosGobernanzaPage";
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
// Pensiones (SIPEN)
import { PensionIntelPage } from "@/modules/pension-intel/pages/PensionIntelPage";
import { DatosPensionesPage } from "@/modules/pension-intel/pages/DatosPensionesPage";
// Seguros (SIS · SISALRIL)
import { InsuranceIntelPage } from "@/modules/insurance-intel/pages/InsuranceIntelPage";
// Plataforma
import { OverviewPage } from "@/modules/platform/pages/OverviewPage";
import { MetodologiaPage } from "@/modules/platform/pages/MetodologiaPage";
import { ComparadorPage } from "@/modules/platform/pages/ComparadorPage";
import { MarketBriefPage } from "@/modules/platform/pages/MarketBriefPage";
import { DealScoringPage } from "@/modules/platform/pages/DealScoringPage";
import { ConfiguracionPage } from "@/modules/platform/pages/ConfiguracionPage";
import { UsersAdminPage } from "@/modules/platform/pages/UsersAdminPage";
import { TarifarioPage } from "@/modules/platform/pages/TarifarioPage";
import { MiPlanPage } from "@/modules/platform/pages/MiPlanPage";
import { ProductMonitorPage } from "@/modules/platform/pages/ProductMonitorPage";
import { ProductCatalogPage } from "@/modules/platform/pages/ProductCatalogPage";
import { SourceIntelPage } from "@/modules/source-intel/pages/SourceIntelPage";

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
            <Route path="validation" element={<ValidationPage />} />
            <Route path="scenarios" element={<ScenariosPage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route path="fideicomisos" element={<FideicomisosPage />} />
          </Route>
          {/* Old data route → moved to the Datos section */}
          <Route path="/banking-score/data" element={<Navigate to="/datos/banca" replace />} />

          {/* Datos — extracción por sector (multi-fuente) */}
          <Route path="/datos" element={<Navigate to="/datos/banca" replace />} />
          <Route path="/datos/banca" element={<DataPage />} />
          <Route path="/datos/operaciones" element={<OperacionesPage />} />
          <Route path="/datos/macro" element={<DatosMacroPage />} />
          <Route path="/datos/social" element={<DatosSocialPage />} />
          <Route path="/datos/comercio" element={<DatosComercioPage />} />
          <Route path="/datos/gobernanza" element={<DatosGobernanzaPage />} />
          <Route path="/datos/pensiones" element={<DatosPensionesPage />} />

          {/* Eje 2 — Macroeconómico */}
          <Route path="/macro-monitor" element={<MacroMonitorPage />} />

          {/* Publicaciones BCRD — ahora una pestaña dentro de Datos · Macro */}
          <Route path="/publicaciones-bcrd" element={<Navigate to="/datos/macro?tab=publicaciones" replace />} />

          {/* Ejes 3-7 — UI en construcción (backend disponible) */}
          <Route path="/sector-intel" element={<SectorIntelPage />} />
          <Route path="/macro-political-risk" element={<MacroPoliticalRiskPage />} />
          <Route path="/social-dev" element={<SocialDevPage />} />
          <Route path="/trade-intel" element={<TradeIntelPage />} />
          <Route path="/esg-climate" element={<EsgClimatePage />} />
          <Route path="/pension-intel" element={<PensionIntelPage />} />
          <Route path="/insurance-intel" element={<InsuranceIntelPage />} />

          {/* Herramientas */}
          <Route
            path="/tools/deal-scoring"
            element={<DealScoringPage />}
          />
          <Route
            path="/tools/market-brief"
            element={<MarketBriefPage />}
          />

          {/* Plataforma */}
          <Route path="/overview" element={<OverviewPage />} />
          <Route
            path="/compare"
            element={<ComparadorPage />}
          />
          <Route path="/methodology" element={<MetodologiaPage />} />
          <Route path="/catalog" element={<ProductCatalogPage />} />
          <Route path="/mi-plan" element={<MiPlanPage />} />
          <Route
            path="/products"
            element={
              <ProtectedRoute requiredRole="admin">
                <ProductMonitorPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/source-intel"
            element={
              <ProtectedRoute requiredRole="admin">
                <SourceIntelPage />
              </ProtectedRoute>
            }
          />
          <Route path="/settings" element={<ConfiguracionPage />} />

          {/* Administración (gateado por rol) */}
          <Route
            path="/admin/users"
            element={
              <ProtectedRoute requiredRole="admin">
                <UsersAdminPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/tarifario"
            element={
              <ProtectedRoute requiredRole="admin">
                <TarifarioPage />
              </ProtectedRoute>
            }
          />
        </Route>
        <Route path="*" element={<Navigate to="/banking-score" replace />} />
      </Routes>
    </ErrorBoundary>
  );
}
