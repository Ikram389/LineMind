import { en, type MessageKey } from "./en.ts";

export type Params = Record<string, string | number>;

/** Look up a UI string and fill in its {placeholders}. */
export function t(key: MessageKey, params: Params = {}): string {
  return en[key].replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}
