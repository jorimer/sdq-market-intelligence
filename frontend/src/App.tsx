import { Suspense, lazy, type ComponentType } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { ProtectedRoute } from "@/shared/auth/ProtectedRoute";
import { AppLayout } from "@/shared/layout/AppLayout";
import { LoginPage } from "@/shared/auth/LoginPage";
import { ErrorBoundary } from "@/shared/components/ErrorBoundary";
import { LoadingGrid } from "@/shared/ui/primitives";

// Code-splitting por página (React.lazy): cada pantalla es su propio chunk y el
// bundle inicial deja de cargar las ~48 páginas de golpe (aviso >500kB del build).
// Los módulos exportan por nombre → adaptador a default export para lazy().
// LoginPage queda EAGER a propósito: es la ruta pública de entrada (y el smoke
// test la monta síncrono).
function lazyPage<K extends string>(
  loader: () => Promise<Record<K, ComponentType>>,
  name: K,
) {
  return lazy(() => loader().then((m) => ({ default: m[name] })));
}

// Banking Score (Eje 1)
const DashboardPage = lazyPage(() => import("@/modules/banking-score/pages/DashboardPage"), "DashboardPage");
const ScoringPage = lazyPage(() => import("@/modules/banking-score/pages/ScoringPage"), "ScoringPage");
const RankingsPage = lazyPage(() => import("@/modules/banking-score/pages/RankingsPage"), "RankingsPage");
const ReportsPage = lazyPage(() => import("@/modules/banking-score/pages/ReportsPage"), "ReportsPage");
const DataPage = lazyPage(() => import("@/modules/banking-score/pages/DataPage"), "DataPage");
const OperacionesPage = lazyPage(() => import("@/modules/banking-score/pages/OperacionesPage"), "OperacionesPage");
const ModelPage = lazyPage(() => import("@/modules/banking-score/pages/ModelPage"), "ModelPage");
const ValidationPage = lazyPage(() => import("@/modules/banking-score/pages/ValidationPage"), "ValidationPage");
const ScenariosPage = lazyPage(() => import("@/modules/banking-score/pages/ScenariosPage"), "ScenariosPage");
const ComparePage = lazyPage(() => import("@/modules/banking-score/pages/ComparePage"), "ComparePage");
const FideicomisosPage = lazyPage(() => import("@/modules/banking-score/pages/FideicomisosPage"), "FideicomisosPage");
const BankingScoreLayout = lazyPage(() => import("@/modules/banking-score/components/BankingScoreLayout"), "BankingScoreLayout");

// Macro Monitor (Eje 2) + consolas de Datos
const MacroMonitorPage = lazyPage(() => import("@/modules/macro-monitor/pages/MacroMonitorPage"), "MacroMonitorPage");
const DatosMacroPage = lazyPage(() => import("@/modules/macro-monitor/pages/DatosMacroPage"), "DatosMacroPage");
const DatosSocialPage = lazyPage(() => import("@/modules/social-dev/pages/DatosSocialPage"), "DatosSocialPage");
const DatosComercioPage = lazyPage(() => import("@/modules/trade-intel/pages/DatosComercioPage"), "DatosComercioPage");
const DatosGobernanzaPage = lazyPage(() => import("@/modules/macro-political-risk/pages/DatosGobernanzaPage"), "DatosGobernanzaPage");
const MacroPoliticalRiskPage = lazyPage(() => import("@/modules/macro-political-risk/pages/MacroPoliticalRiskPage"), "MacroPoliticalRiskPage");
const SectorIntelPage = lazyPage(() => import("@/modules/sector-intel/pages/SectorIntelPage"), "SectorIntelPage");
const SocialDevPage = lazyPage(() => import("@/modules/social-dev/pages/SocialDevPage"), "SocialDevPage");
const TradeIntelPage = lazyPage(() => import("@/modules/trade-intel/pages/TradeIntelPage"), "TradeIntelPage");
const EsgClimatePage = lazyPage(() => import("@/modules/esg-climate/pages/EsgClimatePage"), "EsgClimatePage");
const PensionIntelPage = lazyPage(() => import("@/modules/pension-intel/pages/PensionIntelPage"), "PensionIntelPage");
const DatosPensionesPage = lazyPage(() => import("@/modules/pension-intel/pages/DatosPensionesPage"), "DatosPensionesPage");
const InsuranceIntelPage = lazyPage(() => import("@/modules/insurance-intel/pages/InsuranceIntelPage"), "InsuranceIntelPage");

// Plataforma
const OverviewPage = lazyPage(() => import("@/modules/platform/pages/OverviewPage"), "OverviewPage");
const MetodologiaPage = lazyPage(() => import("@/modules/platform/pages/MetodologiaPage"), "MetodologiaPage");
const ComparadorPage = lazyPage(() => import("@/modules/platform/pages/ComparadorPage"), "ComparadorPage");
const MarketBriefPage = lazyPage(() => import("@/modules/platform/pages/MarketBriefPage"), "MarketBriefPage");
const ResearchPage = lazyPage(() => import("@/modules/platform/pages/ResearchPage"), "ResearchPage");
const DealScoringPage = lazyPage(() => import("@/modules/platform/pages/DealScoringPage"), "DealScoringPage");
const ConfiguracionPage = lazyPage(() => import("@/modules/platform/pages/ConfiguracionPage"), "ConfiguracionPage");
const UsersAdminPage = lazyPage(() => import("@/modules/platform/pages/UsersAdminPage"), "UsersAdminPage");
const TarifarioPage = lazyPage(() => import("@/modules/platform/pages/TarifarioPage"), "TarifarioPage");
const MiPlanPage = lazyPage(() => import("@/modules/platform/pages/MiPlanPage"), "MiPlanPage");
const PagosPage = lazyPage(() => import("@/modules/platform/pages/PagosPage"), "PagosPage");
const CheckoutReturnPage = lazyPage(() => import("@/modules/platform/pages/CheckoutReturnPage"), "CheckoutReturnPage");
const ProductMonitorPage = lazyPage(() => import("@/modules/platform/pages/ProductMonitorPage"), "ProductMonitorPage");
const ProductCatalogPage = lazyPage(() => import("@/modules/platform/pages/ProductCatalogPage"), "ProductCatalogPage");
const SourceIntelPage = lazyPage(() => import("@/modules/source-intel/pages/SourceIntelPage"), "SourceIntelPage");

export default function App() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<div className="p-6"><LoadingGrid /></div>}>
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

            {/* Ejes 3-7 */}
            <Route path="/sector-intel" element={<SectorIntelPage />} />
            <Route path="/macro-political-risk" element={<MacroPoliticalRiskPage />} />
            <Route path="/social-dev" element={<SocialDevPage />} />
            <Route path="/trade-intel" element={<TradeIntelPage />} />
            <Route path="/esg-climate" element={<EsgClimatePage />} />
            <Route path="/pension-intel" element={<PensionIntelPage />} />
            <Route path="/insurance-intel" element={<InsuranceIntelPage />} />

            {/* Herramientas */}
            <Route path="/tools/research" element={<ResearchPage />} />
            <Route path="/tools/deal-scoring" element={<DealScoringPage />} />
            <Route path="/tools/market-brief" element={<MarketBriefPage />} />

            {/* Plataforma */}
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/compare" element={<ComparadorPage />} />
            <Route path="/methodology" element={<MetodologiaPage />} />
            <Route path="/catalog" element={<ProductCatalogPage />} />
            <Route path="/mi-plan" element={<MiPlanPage />} />
            <Route path="/checkout/return" element={<CheckoutReturnPage />} />
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
            <Route
              path="/admin/pagos"
              element={
                <ProtectedRoute requiredRole="admin">
                  <PagosPage />
                </ProtectedRoute>
              }
            />
          </Route>
          <Route path="*" element={<Navigate to="/banking-score" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}
