import { useEffect, useState } from "react";

import { fetchHealth, type HealthResponse } from "./api/health.ts";

type HealthState =
  | { kind: "loading" }
  | { kind: "loaded"; health: HealthResponse }
  | { kind: "unreachable" };

interface StatusRowProps {
  label: string;
  value: string;
  ok: boolean;
}

function StatusRow({ label, value, ok }: StatusRowProps) {
  return (
    <li className="status-row">
      <span>{label}:</span>
      <strong className={ok ? "status-ok" : "status-error"}>{value}</strong>
    </li>
  );
}

function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((health) => setState({ kind: "loaded", health }))
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ kind: "unreachable" });
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="app">
      <h1>LineMind</h1>
      {state.kind === "loading" && <p>Checking services…</p>}
      {state.kind === "unreachable" && (
        <ul className="status-list">
          <StatusRow label="backend" value="unreachable" ok={false} />
          <StatusRow label="database" value="unknown" ok={false} />
        </ul>
      )}
      {state.kind === "loaded" && (
        <ul className="status-list">
          <StatusRow label="backend" value="ok" ok={true} />
          <StatusRow
            label="database"
            value={state.health.database}
            ok={state.health.database === "ok"}
          />
        </ul>
      )}
    </main>
  );
}

export default App;
