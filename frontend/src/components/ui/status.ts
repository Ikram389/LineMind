import {
  Ban,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  Hourglass,
  Info,
  type LucideIcon,
  OctagonAlert,
  OctagonX,
  Pause,
  Play,
  TrendingDown,
  TrendingUp,
  CircleMinus,
} from "lucide-react";

import type { MessageKey } from "../../i18n/en.ts";

/** Everything that has a meaning colour: machine states, severities, effect results. */
export type StatusKind =
  | "running"
  | "stopped"
  | "blocked"
  | "starved"
  | "planned_stop"
  | "unknown"
  | "info"
  | "warning"
  | "critical"
  | "improved"
  | "no_change"
  | "worse"
  | "ok";

interface StatusStyle {
  Icon: LucideIcon;
  label: MessageKey;
  /** Soft background + strong text, from the tokens. */
  tone: string;
  /** The solid colour, for bands and timeline segments. */
  solid: string;
}

// Colour is never the only signal: each status also has its own icon and written label.
export const STATUS: Record<StatusKind, StatusStyle> = {
  running: { Icon: Play, label: "state.running", tone: "bg-running-soft text-running", solid: "bg-running" },
  stopped: { Icon: OctagonX, label: "state.stopped", tone: "bg-stopped-soft text-stopped", solid: "bg-stopped" },
  blocked: { Icon: Ban, label: "state.blocked", tone: "bg-blocked-soft text-blocked", solid: "bg-blocked" },
  starved: { Icon: Hourglass, label: "state.starved", tone: "bg-blocked-soft text-blocked", solid: "bg-blocked" },
  planned_stop: { Icon: Pause, label: "state.planned_stop", tone: "bg-planned-soft text-planned", solid: "bg-planned" },
  unknown: {
    Icon: CircleHelp,
    label: "state.unknown",
    tone: "bg-unknown-soft text-unknown outline-1 outline-dashed outline-unknown",
    solid: "bg-unknown",
  },
  info: { Icon: Info, label: "severity.info", tone: "bg-info-soft text-info", solid: "bg-info" },
  warning: { Icon: CircleAlert, label: "severity.warning", tone: "bg-warning-soft text-warning", solid: "bg-warning" },
  critical: { Icon: OctagonAlert, label: "severity.critical", tone: "bg-critical-soft text-critical", solid: "bg-critical" },
  improved: { Icon: TrendingDown, label: "maint.effect.status.improved", tone: "bg-running-soft text-improved", solid: "bg-improved" },
  no_change: { Icon: CircleMinus, label: "maint.effect.status.no_change", tone: "bg-surface-muted text-ink-muted", solid: "bg-unknown" },
  worse: { Icon: TrendingUp, label: "maint.effect.status.worse", tone: "bg-stopped-soft text-worse", solid: "bg-worse" },
  ok: { Icon: CircleCheck, label: "ui.ok", tone: "bg-running-soft text-running", solid: "bg-running" },
};
