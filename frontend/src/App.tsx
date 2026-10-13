import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { AuthProvider } from "./auth/AuthProvider.tsx";
import { RequireAuth } from "./auth/RequireAuth.tsx";
import { LineOverviewPage } from "./pages/LineOverviewPage.tsx";
import { LinePickerPage } from "./pages/LinePickerPage.tsx";
import { LoginPage } from "./pages/LoginPage.tsx";
import { MachineDetailPage } from "./pages/MachineDetailPage.tsx";

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
            <Route
              path="/"
              element={
                <RequireAuth>
                  <LinePickerPage />
                </RequireAuth>
              }
            />
            <Route
              path="/lines/:lineId"
              element={
                <RequireAuth>
                  <LineOverviewPage />
                </RequireAuth>
              }
            />
            <Route
              path="/lines/:lineId/machines/:machineId"
              element={
                <RequireAuth>
                  <MachineDetailPage />
                </RequireAuth>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
