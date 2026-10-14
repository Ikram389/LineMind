import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Role } from "../api/types.ts";
import { AuthContext } from "../auth/context.ts";

/** Render with a query client, a logged-in user with `role`, and a router at `route`. */
export function renderWithProviders(
  ui: ReactElement,
  { role = "production_supervisor", route = "/", path }: { role?: Role; route?: string; path?: string } = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const auth = {
    user: {
      id: 1,
      email: `${role}@demo.test`,
      full_name: "",
      organization: { id: 1, name: "Demo Beverages" },
      role,
      all_factories: true,
      factories: [{ id: 1, name: "Algiers Plant", timezone: "Africa/Algiers" }],
    },
    status: "authenticated" as const,
    login: async () => {},
    logout: () => {},
  };
  const result = render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter initialEntries={[route]}>
          {path ? (
            <Routes>
              <Route path={path} element={ui} />
              <Route path="*" element={<p>other page</p>} />
            </Routes>
          ) : (
            ui
          )}
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}
