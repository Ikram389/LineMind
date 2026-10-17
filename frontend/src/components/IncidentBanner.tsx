import { TriangleAlert } from "lucide-react";

import type { Incident } from "../api/types.ts";
import { t } from "../i18n/t.ts";
import { incidentHeadline } from "../lib/incidents.ts";

const CATEGORY_KEY = {
  breakdown: "category.breakdown",
  blocked: "category.blocked",
  starved: "category.starved",
  planned: "category.planned",
  no_data: "category.no_data",
} as const;

export function IncidentBanner({ incident, nowMs }: { incident: Incident; nowMs: number }) {
  const affected = incident.affected_machines.filter((m) => !m.is_first_stop);
  return (
    <section
      role="alert"
      className="rounded-card border-2 border-l-8 border-critical bg-critical-soft p-4 text-ink"
    >
      <p className="flex items-center gap-3 text-title font-bold">
        <TriangleAlert aria-hidden className="h-7 w-7 shrink-0 text-critical" />
        <span data-testid="incident-headline">{incidentHeadline(incident, nowMs)}</span>
      </p>
      {affected.length > 0 && (
        <p className="mt-2 text-body">
          <span className="font-semibold">{t("incident.affected")}: </span>
          {affected.map((m) => `${m.name} (${t(CATEGORY_KEY[m.category]).toLowerCase()})`).join(" · ")}
        </p>
      )}
      <p className="mt-1 text-small text-ink-muted">{t("incident.clue")}</p>
    </section>
  );
}
