import {
  Ban,
  CircleHelp,
  Hourglass,
  type LucideIcon,
  OctagonX,
  Pause,
  Play,
} from "lucide-react";

import type { MachineState, MachineStatus } from "../api/types.ts";
import type { MessageKey } from "../i18n/en.ts";

export interface StateStyle {
  label: MessageKey;
  Icon: LucideIcon;
  /** Card background and border. */
  card: string;
  /** Text colour of the state label. */
  text: string;
  /** Solid colour for timeline segments. */
  solid: string;
}

// Colour is never the only signal: every state also has its own icon and written label.
export const STATE_STYLES: Record<MachineState, StateStyle> = {
  running: {
    label: "state.running",
    Icon: Play,
    card: "bg-green-50 border-green-600",
    text: "text-green-800",
    solid: "bg-green-500",
  },
  stopped: {
    label: "state.stopped",
    Icon: OctagonX,
    card: "bg-red-50 border-red-600",
    text: "text-red-800",
    solid: "bg-red-600",
  },
  blocked: {
    label: "state.blocked",
    Icon: Ban,
    card: "bg-amber-50 border-amber-500",
    text: "text-amber-900",
    solid: "bg-amber-500",
  },
  starved: {
    label: "state.starved",
    Icon: Hourglass,
    card: "bg-amber-50 border-amber-500",
    text: "text-amber-900",
    solid: "bg-amber-300",
  },
  planned_stop: {
    label: "state.planned_stop",
    Icon: Pause,
    card: "bg-blue-50 border-blue-600",
    text: "text-blue-800",
    solid: "bg-blue-500",
  },
  unknown: {
    label: "state.unknown",
    Icon: CircleHelp,
    card: "bg-gray-100 border-gray-400",
    text: "text-gray-700",
    solid: "bg-gray-400",
  },
};

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
