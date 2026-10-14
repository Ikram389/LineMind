import { en, type MessageKey } from "./en.ts";

export type Params = Record<string, string | number>;

/** Look up a UI string and fill in its {placeholders}. A missing key (only possible with a
 * key built at run time) shows the key itself instead of breaking the page. */
export function t(key: MessageKey, params: Params = {}): string {
  return (en[key] ?? key).replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}
