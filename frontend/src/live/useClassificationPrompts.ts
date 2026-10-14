/**
 * When a line stop ends, ask why: first the first observed stop, then any secondary
 * breakdown in the same stop. Blocked and starved consequences never need a reason.
 * "Later" only hides the prompt; the stop stays in the unclassified queue.
 */
import { useCallback, useState } from "react";

import type { IncidentMember } from "../api/analysisTypes.ts";
import { getIncident } from "../api/downtime.ts";
import type { LiveMessage } from "../api/types.ts";

const NEEDS_REASON = new Set(["first_observed_stop", "secondary_breakdown"]);

export function promptsForIncident(members: IncidentMember[]): IncidentMember[] {
  const open = members.filter(
    (m) => m.classification === null && m.role_in_incident !== null && NEEDS_REASON.has(m.role_in_incident),
  );
  // First observed stop first, then secondary breakdowns in time order.
  return open.sort((a, b) => {
    const rank = (m: IncidentMember) => (m.role_in_incident === "first_observed_stop" ? 0 : 1);
    return rank(a) - rank(b) || Date.parse(a.started_at) - Date.parse(b.started_at);
  });
}

export function useClassificationPrompts() {
  const [prompts, setPrompts] = useState<IncidentMember[]>([]);

  const onMessage = useCallback((message: LiveMessage) => {
    if (message.type !== "incident_closed") return;
    getIncident(message.data.incident_id)
      .then((incident) => {
        const fresh = promptsForIncident(incident.events);
        setPrompts((current) => [
          ...current,
          ...fresh.filter((f) => !current.some((c) => c.id === f.id)),
        ]);
      })
      .catch(() => {
        // The stop is still in the unclassified queue; nothing is lost.
      });
  }, []);

  const dismiss = useCallback((eventId: number) => {
    setPrompts((current) => current.filter((p) => p.id !== eventId));
  }, []);

  return { prompts, onMessage, dismiss };
}
