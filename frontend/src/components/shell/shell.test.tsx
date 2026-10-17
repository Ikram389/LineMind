import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLocation } from "react-router";

import * as alerts from "../../api/alerts.ts";
import * as endpoints from "../../api/endpoints.ts";
import * as maintenance from "../../api/maintenance.ts";
import { renderWithProviders } from "../../test/render.tsx";
import { AppBar, AppLayout } from "../AppBar.tsx";
import { UserMenu } from "./TopBarParts.tsx";

vi.mock("../../live/useUserLive.ts", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../live/useUserLive.ts")>()),
  useUserLive: () => {},
}));

beforeEach(() => {
  vi.spyOn(alerts, "getUnreadCount").mockResolvedValue(0);
  vi.spyOn(alerts, "listAlerts").mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
  vi.spyOn(alerts, "getHealth").mockResolvedValue({ status: "ok", database: "ok", alerts: "ok" });
  vi.spyOn(maintenance, "getMyOpenCount").mockResolvedValue(0);
  vi.spyOn(endpoints, "listLines").mockResolvedValue([
    { id: 1, factory: 1, name: "Line 1", counting_machine: null },
    { id: 2, factory: 1, name: "Line 2", counting_machine: null },
  ]);
});

afterEach(() => {
  document.documentElement.className = "";
});

function Where() {
  const { pathname } = useLocation();
  return <p data-testid="where">{pathname}</p>;
}

describe("theme", () => {
  it("switches to dark from the account menu and remembers it for this user", () => {
    const first = renderWithProviders(<UserMenu />);
    fireEvent.click(screen.getByRole("button", { name: /Account menu/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dark" }));

    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("linemind.theme.1")).toBe("dark");
    first.unmount();

    // A new visit: the stored choice is applied again.
    document.documentElement.className = "";
    renderWithProviders(<UserMenu />);
    expect(document.documentElement).toHaveClass("dark");
    fireEvent.click(screen.getByRole("button", { name: /Account menu/ }));
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps each user's choice separate", () => {
    localStorage.setItem("linemind.theme.99", "dark");
    renderWithProviders(<UserMenu />); // user 1
    expect(document.documentElement).not.toHaveClass("dark");
  });
});

describe("TV mode", () => {
  it("hides the menu and the top bar, and turns on dark and large type", async () => {
    renderWithProviders(<AppLayout />, { route: "/lines/1?tv=1", path: "/lines/:lineId" });

    expect(screen.getByTestId("tv-mode")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("button", { name: /Notifications/ })).toBeNull();
    await waitFor(() => expect(document.documentElement).toHaveClass("tv", "dark"));
  });

  it("shows the menu and the top bar outside TV mode", async () => {
    renderWithProviders(<AppLayout />, { route: "/lines/1", path: "/lines/:lineId" });

    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.queryByTestId("tv-mode")).toBeNull();
    expect(document.documentElement).not.toHaveClass("tv");
    expect(await screen.findByRole("button", { name: /Notifications/ })).toBeInTheDocument();
  });
});

describe("sidebar and line selector", () => {
  it("links the line pages to the current line", () => {
    renderWithProviders(<AppBar />, { route: "/lines/2/quality", path: "/lines/:lineId/*" });

    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/lines/2");
    expect(screen.getByRole("link", { name: "Downtime" })).toHaveAttribute("href", "/lines/2/downtime");
    expect(screen.getByRole("link", { name: "Quality" })).toHaveAttribute("href", "/lines/2/quality");
  });

  it("switches line and stays on the same page", async () => {
    renderWithProviders(
      <>
        <AppBar />
        <Where />
      </>,
      { route: "/lines/1/downtime" },
    );

    const select = await screen.findByRole("combobox", { name: "Line" });
    fireEvent.change(select, { target: { value: "2" } });
    expect(screen.getByTestId("where")).toHaveTextContent("/lines/2/downtime");
  });

  it("shows Manage links by role", () => {
    const operator = renderWithProviders(<AppBar />, { route: "/lines/1", role: "machine_operator" });
    expect(screen.queryByRole("link", { name: "Reasons" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Quality setup" })).toBeNull();
    operator.unmount();

    renderWithProviders(<AppBar />, { route: "/lines/1", role: "factory_manager" });
    expect(screen.getByRole("link", { name: "Reasons" })).toHaveAttribute("href", "/lines/1/reasons");
    expect(screen.getByRole("link", { name: "Quality setup" })).toHaveAttribute("href", "/lines/1/quality-setup");
  });

  it("keeps link names when collapsed", () => {
    renderWithProviders(<AppBar />, { route: "/lines/1" });
    fireEvent.click(screen.getByRole("button", { name: "Collapse the menu" }));

    expect(screen.getByRole("button", { name: "Expand the menu" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: "Downtime" })).toBeInTheDocument();
  });
});
