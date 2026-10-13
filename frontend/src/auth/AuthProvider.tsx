import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { clearTokens, hasRefreshToken, onLogout } from "../api/client.ts";
import { getMe, login as apiLogin } from "../api/endpoints.ts";
import type { Me } from "../api/types.ts";
import { AuthContext, type AuthState } from "./context.ts";

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<Me | null>(null);
  const [status, setStatus] = useState<AuthState["status"]>(
    hasRefreshToken() ? "loading" : "anonymous",
  );

  // A stored refresh token means we may still be logged in: /me/ refreshes the access token.
  useEffect(() => {
    if (status !== "loading") return;
    getMe()
      .then((me) => {
        setUser(me);
        setStatus("authenticated");
      })
      .catch(() => {
        clearTokens();
        setStatus("anonymous");
      });
  }, [status]);

  useEffect(
    () =>
      onLogout(() => {
        setUser(null);
        setStatus("anonymous");
        queryClient.clear();
      }),
    [queryClient],
  );

  const login = useCallback(async (email: string, password: string) => {
    await apiLogin(email, password);
    const me = await getMe();
    setUser(me);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
    setStatus("anonymous");
    queryClient.clear();
  }, [queryClient]);

  const value = useMemo(() => ({ user, status, login, logout }), [user, status, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
