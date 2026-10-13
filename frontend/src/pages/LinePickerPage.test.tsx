import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import * as endpoints from "../api/endpoints.ts";
import { LinePickerPage } from "./LinePickerPage.tsx";

function renderPicker() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<LinePickerPage />} />
          <Route path="/lines/:lineId" element={<p>Overview of line</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LinePickerPage", () => {
  it("goes straight to the only line", async () => {
    vi.spyOn(endpoints, "listLines").mockResolvedValue([
      { id: 1, factory: 1, name: "Bottling Line 1", counting_machine: null },
    ]);

    renderPicker();

    expect(await screen.findByText("Overview of line")).toBeInTheDocument();
  });

  it("lists several lines to choose from", async () => {
    vi.spyOn(endpoints, "listLines").mockResolvedValue([
      { id: 1, factory: 1, name: "Bottling Line 1", counting_machine: null },
      { id: 2, factory: 1, name: "Bottling Line 2", counting_machine: null },
    ]);

    renderPicker();

    expect(await screen.findByText("Bottling Line 2")).toBeInTheDocument();
    expect(screen.getByText("Choose a line")).toBeInTheDocument();
  });
});
