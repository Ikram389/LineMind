import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { type Column, DataTable } from "./DataTable.tsx";
import { StatusBadge } from "./StatusBadge.tsx";
import type { StatusKind } from "./status.ts";

describe("StatusBadge", () => {
  it.each<[StatusKind, string]>([
    ["running", "Running"],
    ["stopped", "Stopped"],
    ["blocked", "Blocked"],
    ["starved", "Starved"],
    ["planned_stop", "Planned stop"],
    ["unknown", "Unknown"],
    ["info", "Info"],
    ["warning", "Warning"],
    ["critical", "Critical"],
    ["improved", "Improved"],
    ["no_change", "No clear change"],
    ["worse", "Worse"],
    ["ok", "OK"],
  ])("shows %s with an icon and written text", (kind, text) => {
    const { container } = render(<StatusBadge kind={kind} />);

    const badge = container.querySelector(`[data-status="${kind}"]`);
    expect(badge).not.toBeNull();
    expect(badge).toHaveTextContent(text);
    expect(badge?.querySelector("svg")).not.toBeNull();
  });

  it("gives each machine state its own icon", () => {
    const states: StatusKind[] = ["running", "stopped", "blocked", "starved", "planned_stop", "unknown"];
    const icons = states.map((kind) => {
      const { container, unmount } = render(<StatusBadge kind={kind} />);
      const html = container.querySelector("svg")?.innerHTML ?? "";
      unmount();
      return html;
    });
    expect(new Set(icons).size).toBe(states.length);
  });

  it("keeps the icon when the text is replaced", () => {
    const { container } = render(<StatusBadge kind="warning" label="Reclassified" />);
    expect(container).toHaveTextContent("Reclassified");
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

interface Row {
  id: number;
  machine: string;
  minutes: number | null;
}

const rows: Row[] = [
  { id: 1, machine: "Labeler", minutes: 12 },
  { id: 2, machine: "Filler", minutes: null },
  { id: 3, machine: "Capper", minutes: 4 },
];
const columns: Column<Row>[] = [
  { key: "machine", header: "Machine", render: (r) => r.machine, sortValue: (r) => r.machine },
  { key: "minutes", header: "Minutes", render: (r) => String(r.minutes ?? "—"), sortValue: (r) => r.minutes },
  { key: "note", header: "Note", render: () => "" },
];

const machinesInOrder = () =>
  screen.getAllByRole("row").slice(1).map((row) => within(row).getAllByRole("cell")[0]?.textContent);

describe("DataTable", () => {
  it("sorts locally by a column, ascending then descending, empty values last", () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(machinesInOrder()).toEqual(["Labeler", "Filler", "Capper"]);

    fireEvent.click(screen.getByRole("button", { name: "Minutes" }));
    expect(machinesInOrder()).toEqual(["Capper", "Labeler", "Filler"]);
    expect(screen.getByRole("columnheader", { name: "Minutes" })).toHaveAttribute("aria-sort", "ascending");

    fireEvent.click(screen.getByRole("button", { name: "Minutes" }));
    expect(machinesInOrder()).toEqual(["Labeler", "Capper", "Filler"]);
    expect(screen.getByRole("columnheader", { name: "Minutes" })).toHaveAttribute("aria-sort", "descending");

    fireEvent.click(screen.getByRole("button", { name: "Machine" }));
    expect(machinesInOrder()).toEqual(["Capper", "Filler", "Labeler"]);
  });

  it("makes only sortable columns clickable", () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.queryByRole("button", { name: "Note" })).toBeNull();
  });

  it("leaves server-side sorting to the page", () => {
    const onSort = vi.fn();
    render(
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        sort={{ key: "minutes", direction: "asc" }}
        onSort={onSort}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Minutes" }));
    expect(onSort).toHaveBeenCalledWith({ key: "minutes", direction: "desc" });
    expect(machinesInOrder()).toEqual(["Labeler", "Filler", "Capper"]); // rows untouched
  });

  it("shows the empty state instead of an empty table", () => {
    render(<DataTable columns={columns} rows={[]} rowKey={(r) => r.id} empty={<p>No stops</p>} />);
    expect(screen.getByText("No stops")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
