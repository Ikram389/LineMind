import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as alerts from "../api/alerts.ts";
import * as downtime from "../api/downtime.ts";
import * as endpoints from "../api/endpoints.ts";
import { RULE_TYPES_INFO } from "../test/alertFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { AlertRulesPage } from "./AlertRulesPage.tsx";

beforeEach(() => {
  vi.spyOn(endpoints, "listLines").mockResolvedValue([{ id: 1, factory: 1, name: "Bottling Line 1", counting_machine: null }]);
  vi.spyOn(downtime, "listLineMachines").mockResolvedValue([]);
  vi.spyOn(alerts, "getRuleTypes").mockResolvedValue(RULE_TYPES_INFO);
  vi.spyOn(alerts, "listAlertRules").mockResolvedValue([
    {
      id: 4, factory: 1, line: null, machine: null, name: "Long line stop", rule_type: "long_stop",
      parameters: { minutes: 10 }, severity: "warning", is_enabled: true,
      recipient_roles: ["machine_operator", "production_supervisor"], cooldown_minutes: 30,
      escalate_after_minutes: 15, escalation_roles: ["factory_manager"], active_outside_shifts: false,
    },
  ]);
});

describe("AlertRulesPage", () => {
  it("lists rules in plain language and turns one off", async () => {
    const update = vi.spyOn(alerts, "updateAlertRule").mockResolvedValue({} as never);
    renderWithProviders(<AlertRulesPage />, { role: "factory_manager" });

    const rule = await screen.findByTestId("rule-4");
    expect(rule).toHaveTextContent("Warning · notify Operators, Supervisors · escalate after 15 min");
    fireEvent.click(screen.getByRole("checkbox", { name: "Turn Long line stop on or off" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith(4, { is_enabled: false }));
  });

  it("adapts the form to the rule type and validates its parameters", async () => {
    const create = vi.spyOn(alerts, "createAlertRule").mockResolvedValue({} as never);
    renderWithProviders(<AlertRulesPage />, { role: "factory_manager" });

    fireEvent.click(await screen.findByRole("button", { name: "+ New rule" }));
    expect(screen.getByTestId("rule-help")).toHaveTextContent("Alert when a line stop has lasted more than");
    fireEvent.change(screen.getByLabelText("Minutes"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Must be at least 1.")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();

    // Another type: other fields and its own help text.
    fireEvent.change(screen.getByLabelText("What to watch"), { target: { value: "low_oee" } });
    expect(screen.getByTestId("rule-help")).toHaveTextContent("shift's OEE so far is below");
    expect(screen.queryByLabelText("Minutes")).toBeNull();
    fireEvent.change(screen.getByLabelText("OEE below (%)"), { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Must be at most 100.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("OEE below (%)"), { target: { value: "55" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          factory: 1, rule_type: "low_oee", parameters: { below_percent: 55 }, machine: null,
          recipient_roles: ["production_supervisor"], escalation_roles: ["factory_manager"],
        }),
      ),
    );
  });

  it("is closed to supervisors", () => {
    renderWithProviders(<AlertRulesPage />, { role: "production_supervisor" });

    expect(screen.getByText("Only factory managers can manage alert rules.")).toBeInTheDocument();
  });
});
