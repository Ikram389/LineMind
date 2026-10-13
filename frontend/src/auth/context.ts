import { createContext, useContext } from "react";

import type { Me } from "../api/types.ts";

export interface AuthState {
  user: Me | null;
  status: "loading" | "anonymous" | "authenticated";
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>.");
  return value;
}
