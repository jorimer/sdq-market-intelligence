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
