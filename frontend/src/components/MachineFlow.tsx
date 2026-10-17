import { ChevronRight } from "lucide-react";

import type { Incident, MachineStatus } from "../api/types.ts";
import { MachineCard } from "./MachineCard.tsx";

interface MachineFlowProps {
  machines: MachineStatus[];
  incident: Incident | null;
  staleAfterSeconds: number;
  nowMs: number;
  shiftStart: string | null;
  machineHref: (machine: MachineStatus) => string;
}

/** The machines in line order, left to right, connected by arrows. */
export function MachineFlow({
  machines,
  incident,
  staleAfterSeconds,
  nowMs,
  shiftStart,
  machineHref,
}: MachineFlowProps) {
  const firstStops = new Set(incident?.first_observed_stop.machines.map((m) => m.id) ?? []);
  const ordered = [...machines].sort((a, b) => a.position - b.position);

  return (
    <ol className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-5">
      {ordered.map((machine, index) => (
        <li key={machine.id} className="relative min-w-0">
          <MachineCard
            machine={machine}
            staleAfterSeconds={staleAfterSeconds}
            nowMs={nowMs}
            shiftStart={shiftStart}
            isFirstStop={firstStops.has(machine.id)}
            href={machineHref(machine)}
          />
          {/* Line flow: the next machine is to the right. */}
          {index < ordered.length - 1 && (
            <ChevronRight aria-hidden className="absolute -right-[1.1rem] top-1/2 h-5 w-5 -translate-y-1/2 text-ink-muted" />
          )}
        </li>
      ))}
    </ol>
  );
}
