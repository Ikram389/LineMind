import type { RuleParameter } from "../api/alertTypes.ts";

/** Check one parameter like the backend does; returns an error message or null. */
export function paramError(param: RuleParameter, raw: string): string | null {
  if (raw.trim() === "") return param.required ? "Required." : null;
  if (param.choices) return param.choices.includes(raw) ? null : "Choose one of the options.";
  const value = Number(raw);
  if (!Number.isFinite(value)) return "Must be a number.";
  if (param.kind === "integer" && !Number.isInteger(value)) return "Must be a whole number.";
  if (param.min !== null && value < param.min) return `Must be at least ${param.min}.`;
  if (param.max !== null && value > param.max) return `Must be at most ${param.max}.`;
  return null;
}
