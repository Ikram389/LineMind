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
      className="rounded-xl border-4 border-red-700 bg-red-50 p-4 text-red-900"
    >
      <p className="flex items-center gap-3 text-2xl font-bold">
        <TriangleAlert aria-hidden className="h-8 w-8 shrink-0" />
        <span data-testid="incident-headline">{incidentHeadline(incident, nowMs)}</span>
      </p>
      {affected.length > 0 && (
        <p className="mt-2 text-lg">
          <span className="font-semibold">{t("incident.affected")}: </span>
          {affected.map((m) => `${m.name} (${t(CATEGORY_KEY[m.category]).toLowerCase()})`).join(" · ")}
        </p>
      )}
      <p className="mt-1 text-sm text-red-800">{t("incident.clue")}</p>
    </section>
  );
}
