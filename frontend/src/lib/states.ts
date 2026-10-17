import type { LucideIcon } from "lucide-react";

import type { MachineState, MachineStatus } from "../api/types.ts";
import { STATUS } from "../components/ui/status.ts";
import type { MessageKey } from "../i18n/en.ts";

export interface StateStyle {
  label: MessageKey;
  Icon: LucideIcon;
  /** Border colour (design token). */
  border: string;
  /** Soft background tint. */
  soft: string;
  /** Text colour of the state label. */
  text: string;
  /** Solid colour for timeline segments. */
  solid: string;
}

const TOKENS: Record<MachineState, { border: string; soft: string; text: string; solid: string }> = {
  running: { border: "border-running", soft: "bg-running-soft", text: "text-running", solid: "bg-running" },
  stopped: { border: "border-stopped", soft: "bg-stopped-soft", text: "text-stopped", solid: "bg-stopped" },
  blocked: { border: "border-blocked", soft: "bg-blocked-soft", text: "text-blocked", solid: "bg-blocked" },
  // Starved shares the amber family; its lighter segment, icon and text tell it apart.
  starved: { border: "border-blocked", soft: "bg-blocked-soft", text: "text-blocked", solid: "bg-blocked/55" },
  planned_stop: { border: "border-planned", soft: "bg-planned-soft", text: "text-planned", solid: "bg-planned" },
  unknown: { border: "border-unknown border-dashed", soft: "bg-unknown-soft", text: "text-unknown", solid: "bg-unknown" },
};

// Colour is never the only signal: every state also has its own icon and written label
// (the same ones as StatusBadge).
export const STATE_STYLES = Object.fromEntries(
  (Object.keys(TOKENS) as MachineState[]).map((state) => [
    state,
    { label: STATUS[state].label, Icon: STATUS[state].Icon, ...TOKENS[state] },
  ]),
) as Record<MachineState, StateStyle>;

export interface EffectiveState {
  state: MachineState;
  since: string | null;
  isStale: boolean;
}

/**
 * The state to show right now. Uses server time: a machine whose data is older than
 * the stale threshold is "unknown", never its last reported state.
 */
export function effectiveState(
  machine: Pick<MachineStatus, "state" | "state_since" | "last_seen">,
  staleAfterSeconds: number,
  nowMs: number,
): EffectiveState {
  const lastSeenMs = machine.last_seen ? Date.parse(machine.last_seen) : null;
  if (lastSeenMs === null || nowMs - lastSeenMs > staleAfterSeconds * 1000) {
    return { state: "unknown", since: machine.last_seen, isStale: true };
  }
  return { state: machine.state, since: machine.state_since, isStale: false };
}
