/**
 * Light or dark theme, remembered per user in this browser (local storage).
 * TV mode always uses dark. The theme is the "dark" class on <html> (see styles/theme.css).
 */
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "../auth/context.ts";

export type Theme = "light" | "dark";

const key = (userId: number | null | undefined) => `linemind.theme.${userId ?? "anonymous"}`;

export function readTheme(userId: number | null | undefined): Theme {
  try {
    return window.localStorage.getItem(key(userId)) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

/** The user's theme and a setter that applies and remembers it. */
export function useTheme(): [Theme, (theme: Theme) => void] {
  const userId = useAuth().user?.id;
  const [theme, setThemeState] = useState<Theme>(() => readTheme(userId));
  useEffect(() => {
    const stored = readTheme(userId);
    setThemeState(stored);
    applyTheme(stored);
  }, [userId]);
  const setTheme = useCallback(
    (next: Theme) => {
      try {
        window.localStorage.setItem(key(userId), next);
      } catch {
        // Private mode: the theme still applies for this visit.
      }
      setThemeState(next);
      applyTheme(next);
    },
    [userId],
  );
  return [theme, setTheme];
}
