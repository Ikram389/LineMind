import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { t } from "../i18n/t.ts";
import { useAuth } from "./context.ts";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return <p className="p-8 text-xl text-gray-600">{t("panel.loading")}</p>;
  }
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
