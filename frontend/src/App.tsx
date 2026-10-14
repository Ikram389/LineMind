import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { AuthProvider } from "./auth/AuthProvider.tsx";
import { RequireAuth } from "./auth/RequireAuth.tsx";
import { AppLayout } from "./components/AppBar.tsx";
import { AlertRulesPage } from "./pages/AlertRulesPage.tsx";
import { AlertsPage } from "./pages/AlertsPage.tsx";
import { DowntimePage } from "./pages/DowntimePage.tsx";
import { LineOverviewPage } from "./pages/LineOverviewPage.tsx";
import { LinePickerPage } from "./pages/LinePickerPage.tsx";
import { LoginPage } from "./pages/LoginPage.tsx";
import { MachineDetailPage } from "./pages/MachineDetailPage.tsx";
import { QualityPage } from "./pages/QualityPage.tsx";
import { QualitySetupPage } from "./pages/QualitySetupPage.tsx";
import { ReasonsPage } from "./pages/ReasonsPage.tsx";
import { SettingsPage } from "./pages/SettingsPage.tsx";
import { UnclassifiedPage } from "./pages/UnclassifiedPage.tsx";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5_000, refetchOnWindowFocus: true },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* Every signed-in page shares the top bar (alerts bell, settings, log out). */}
            <Route
              element={
                <RequireAuth>
                  <AppLayout />
                </RequireAuth>
              }
            >
              <Route path="/" element={<LinePickerPage />} />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route path="/alert-rules" element={<AlertRulesPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/lines/:lineId" element={<LineOverviewPage />} />
              <Route path="/lines/:lineId/downtime" element={<DowntimePage />} />
              <Route path="/lines/:lineId/unclassified" element={<UnclassifiedPage />} />
              <Route path="/lines/:lineId/reasons" element={<ReasonsPage />} />
              <Route path="/lines/:lineId/quality" element={<QualityPage />} />
              <Route path="/lines/:lineId/quality-setup" element={<QualitySetupPage />} />
              <Route path="/lines/:lineId/machines/:machineId" element={<MachineDetailPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
