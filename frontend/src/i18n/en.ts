/**
 * Every piece of UI text, in one place. To add French or Arabic later, add a
 * dictionary with the same keys and let `t` pick it.
 * Placeholders look like {name} and are filled in by `t(key, { name })`.
 */
export const en = {
  appName: "LineMind",

  "login.title": "Sign in to LineMind",
  "login.email": "Email",
  "login.password": "Password",
  "login.submit": "Sign in",
  "login.submitting": "Signing in…",
  "login.invalid": "The email or password is incorrect.",
  "login.failed": "Could not sign in. Check your connection and try again.",

  "health.status": "Backend: {backend} · Database: {database}",
  "health.unreachable": "unreachable",

  "nav.logout": "Log out",
  "nav.lines": "Lines",
  "nav.backToLine": "← Back to the line",

  "picker.title": "Choose a line",
  "picker.empty": "You do not have access to any production line yet.",

  "state.running": "Running",
  "state.stopped": "Stopped",
  "state.blocked": "Blocked",
  "state.starved": "Starved",
  "state.planned_stop": "Planned stop",
  "state.unknown": "Unknown",
  "state.unknownHint": "No recent data",

  "machine.since": "for {duration}",
  "machine.shiftCount": "This shift",
  "machine.noShift": "No shift running",
  "machine.alarm": "Alarm {code}",
  "machine.lastAlarm": "Last alarm {code} · {ago} ago",
  "machine.firstStop": "First observed stop",
  "machine.open": "Open details for {name}",

  "incident.stopped": "Line stopped for {duration} — first observed stop: {machines}",
  "incident.alarm": "(alarm {code})",
  "incident.unknownOrigin":
    "Line disturbed for {duration} — no stopped machine observed, origin unknown",
  "incident.affected": "Affected machines",
  "incident.clue": "The first observed stop is where the stop was first seen, not proof of its cause.",

  "live.connecting": "Connecting to live updates…",
  "live.live": "Live",
  "live.reconnecting": "Live updates paused, reconnecting…",

  "shift.none": "No shift running",
  "shift.remaining": "{duration} left",
  "shift.label": "{name} {start}–{end}",

  "oee.title": "Current shift OEE",
  "oee.oee": "OEE",
  "oee.availability": "Availability",
  "oee.performance": "Performance",
  "oee.quality": "Quality",
  "oee.coverage": "Data coverage",
  "oee.notAvailable": "—",
  "oee.noShift": "OEE is calculated for the current shift. No shift is running.",
  "oee.hourly": "Hourly OEE",
  "oee.hourlyEmpty": "No full hour of data in this shift yet.",
  "oee.warnings": "Notes",

  "panel.loading": "Loading…",
  "panel.error": "Could not load this information. Retrying automatically.",
  "panel.empty": "Nothing to show yet.",

  "detail.timeline": "State timeline — current shift",
  "detail.timelineNote": "Stops shorter than the factory's minimum stop length are not shown.",
  "detail.downtime": "Downtime this shift",
  "detail.noDowntime": "No downtime in this shift.",
  "detail.colStart": "Start",
  "detail.colDuration": "Duration",
  "detail.colCategory": "Category",
  "detail.colClassification": "Classification",
  "detail.notClassified": "Not classified",
  "detail.ongoing": "ongoing",
  "detail.segment": "{state} from {start} for {duration}",

  "category.breakdown": "Breakdown",
  "category.blocked": "Blocked",
  "category.starved": "Starved",
  "category.planned": "Planned stop",
  "category.no_data": "No data",

  "time.zone": "Times in {zone}",
  "duration.seconds": "{s} s",
  "duration.minutes": "{m} min {s} s",
  "duration.hours": "{h} h {mm} min",
  "duration.days": "{d} d {h} h",
  "duration.shortMinutes": "{m} min",
} as const;

export type MessageKey = keyof typeof en;
