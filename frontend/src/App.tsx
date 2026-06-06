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

// Macro Monitor (Eje 2) — new canonical pattern
import { MacroMonitorPage } from "@/modules/macro-monitor/pages/MacroMonitorPage";
// Macro-Political Risk (Eje 4)
import { MacroPoliticalRiskPage } from "@/modules/macro-political-risk/pages/MacroPoliticalRiskPage";

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
          {/* Eje 1 — Financiero */}
          <Route path="/banking-score" element={<DashboardPage />} />
          <Route path="/banking-score/scoring" element={<ScoringPage />} />
          <Route path="/banking-score/rankings" element={<RankingsPage />} />
          <Route path="/banking-score/reports" element={<ReportsPage />} />
          <Route path="/banking-score/data" element={<DataPage />} />
          <Route path="/banking-score/model" element={<ModelPage />} />
          <Route path="/banking-score/scenarios" element={<ScenariosPage />} />
          <Route path="/banking-score/compare" element={<ComparePage />} />

          {/* Eje 2 — Macroeconómico */}
          <Route path="/macro-monitor" element={<MacroMonitorPage />} />

          {/* Ejes 3-7 — UI en construcción (backend disponible) */}
          <Route
            path="/sector-intel"
            element={
              <PlaceholderPage
                eyebrow="ONE · BCRD"
                title="Sectorial"
                sub="Atractivo (IAI) y potencial de crecimiento (SGPS) por sector."
                api="/api/v1/sector-intel"
              />
            }
          />
          <Route path="/macro-political-risk" element={<MacroPoliticalRiskPage />} />
          <Route
            path="/social-dev"
            element={
              <PlaceholderPage
                eyebrow="ONE"
                title="Social & desarrollo"
                sub="Índice multidimensional de desarrollo; distribución, no solo promedio."
                api="/api/v1/social-dev"
              />
            }
          />
          <Route
            path="/trade-intel"
            element={
              <PlaceholderPage
                eyebrow="BCRD · DGA"
                title="Comercio exterior"
                sub="Resiliencia comercial: diversificación y dependencia, no volumen."
                api="/api/v1/trade-intel"
              />
            }
          />
          <Route
            path="/esg-climate"
            element={
              <PlaceholderPage
                eyebrow="ONE · TCFD/ISSB"
                title="ESG & clima"
                sub="Exposición climática y materialidad por sector."
                api="/api/v1/esg-climate"
              />
            }
          />

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
          <Route
            path="/overview"
            element={<PlaceholderPage title="Resumen ejecutivo" sub="Vista consolidada de los 7 ejes." />}
          />
          <Route
            path="/compare"
            element={<PlaceholderPage title="Comparador" sub="Comparación lado a lado de entidades, sectores y países." />}
          />
          <Route
            path="/methodology"
            element={<PlaceholderPage title="Metodología" sub="Doctrina, pesos y trazabilidad de cada índice." />}
          />
          <Route
            path="/settings"
            element={<PlaceholderPage title="Configuración" sub="Preferencias de cuenta y plataforma." />}
          />
        </Route>
        <Route path="*" element={<Navigate to="/banking-score" replace />} />
      </Routes>
    </ErrorBoundary>
  );
}
