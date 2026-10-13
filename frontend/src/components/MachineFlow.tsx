import { ChevronRight } from "lucide-react";
import { Fragment } from "react";

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
    <ol className="grid grid-cols-[repeat(3,minmax(0,1fr))] items-stretch gap-3 xl:flex xl:gap-1">
      {ordered.map((machine, index) => (
        <Fragment key={machine.id}>
          <li className="xl:flex-1">
            <MachineCard
              machine={machine}
              staleAfterSeconds={staleAfterSeconds}
              nowMs={nowMs}
              shiftStart={shiftStart}
              isFirstStop={firstStops.has(machine.id)}
              href={machineHref(machine)}
            />
          </li>
          {index < ordered.length - 1 && (
            <li aria-hidden className="hidden items-center text-gray-400 xl:flex">
              <ChevronRight className="h-8 w-8" />
            </li>
          )}
        </Fragment>
      ))}
    </ol>
  );
}
