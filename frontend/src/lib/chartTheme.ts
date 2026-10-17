/**
 * Chart colours and text sizes from the design tokens, so every chart looks the same and
 * follows the light/dark theme. Recharts needs real colour values, not CSS classes.
 */
import { useEffect, useState } from "react";

export interface ChartTheme {
  accent: string;
  ink: string;
  muted: string;
  grid: string;
  surface: string;
  running: string;
  stopped: string;
  blocked: string;
  planned: string;
  unknown: string;
  /** Axis tick size in px (bigger in TV mode). */
  tick: number;
}

function read(): ChartTheme {
  const root = document.documentElement;
  const style = getComputedStyle(root);
  const v = (name: string, fallback: string) => style.getPropertyValue(`--lm-${name}`).trim() || fallback;
  return {
    accent: v("accent", "#1d4ed8"),
    ink: v("ink", "#111827"),
    muted: v("ink-muted", "#4b5563"),
    grid: v("line", "#e2e5ea"),
    surface: v("surface", "#ffffff"),
    running: v("running", "#15803d"),
    stopped: v("stopped", "#b91c1c"),
    blocked: v("blocked", "#b45309"),
    planned: v("planned", "#6d28d9"),
    unknown: v("unknown", "#4b5563"),
    tick: root.classList.contains("tv") ? 20 : 13,
  };
}

/** Re-reads the tokens when the <html> classes change (theme or TV mode). */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}
