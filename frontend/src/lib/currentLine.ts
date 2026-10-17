/**
 * The line the user is working on: the one in the address (/lines/<id>/…), or else the last
 * one they opened in this browser. The sidebar and the line selector use it; pages still read
 * the line from the address.
 */
import { useEffect } from "react";
import { matchPath, useLocation } from "react-router";

const KEY = "linemind.lastLine";

/** The page within a line ("", "/downtime", "/quality", …), so switching lines keeps it. */
const LINE_PAGES = ["/downtime", "/unclassified", "/reasons", "/quality-setup", "/quality"];

function readLastLine(): number | null {
  try {
    const value = Number(window.localStorage.getItem(KEY));
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function useCurrentLine(): { lineId: number | null; subPage: string } {
  const { pathname } = useLocation();
  const match = matchPath({ path: "/lines/:lineId", end: false }, pathname);
  const fromPath = match ? Number(match.params.lineId) : null;
  const lineId = fromPath && Number.isInteger(fromPath) ? fromPath : null;
  useEffect(() => {
    if (lineId === null) return;
    try {
      window.localStorage.setItem(KEY, String(lineId));
    } catch {
      // Private mode: nothing is remembered.
    }
  }, [lineId]);
  const rest = match ? pathname.slice(match.pathnameBase.length) : "";
  const subPage = LINE_PAGES.find((page) => rest === page) ?? "";
  return { lineId: lineId ?? readLastLine(), subPage };
}

/** True while the media query matches (e.g. a tablet-width window). */
export function mediaMatches(query: string): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
}
