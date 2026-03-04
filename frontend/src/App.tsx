import { Routes, Route, Navigate } from "react-router-dom";
import { ProtectedRoute } from "@/shared/auth/ProtectedRoute";
import { AppLayout } from "@/shared/layout/AppLayout";
import { LoginPage } from "@/shared/auth/LoginPage";
import { ErrorBoundary } from "@/shared/components/ErrorBoundary";

import { DashboardPage } from "@/modules/banking-score/pages/DashboardPage";
import { ScoringPage } from "@/modules/banking-score/pages/ScoringPage";
import { RankingsPage } from "@/modules/banking-score/pages/RankingsPage";
import { ReportsPage } from "@/modules/banking-score/pages/ReportsPage";
import { DataPage } from "@/modules/banking-score/pages/DataPage";
import { ModelPage } from "@/modules/banking-score/pages/ModelPage";
import { ScenariosPage } from "@/modules/banking-score/pages/ScenariosPage";
import { ComparePage } from "@/modules/banking-score/pages/ComparePage";

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
          <Route path="/banking-score" element={<DashboardPage />} />
          <Route path="/banking-score/scoring" element={<ScoringPage />} />
          <Route path="/banking-score/rankings" element={<RankingsPage />} />
          <Route path="/banking-score/reports" element={<ReportsPage />} />
          <Route path="/banking-score/data" element={<DataPage />} />
          <Route path="/banking-score/model" element={<ModelPage />} />
          <Route path="/banking-score/scenarios" element={<ScenariosPage />} />
          <Route path="/banking-score/compare" element={<ComparePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/banking-score" replace />} />
      </Routes>
    </ErrorBoundary>
  );
}
