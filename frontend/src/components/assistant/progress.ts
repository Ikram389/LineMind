import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";

/** "Checking the downtime…" for a tool name; the server's English label as a fallback. */
export function progressLabel(tool: string, fallback: string): string {
  const key = `assistant.progress.${tool}` as MessageKey;
  const text = t(key);
  return text === key ? fallback : text;
}
