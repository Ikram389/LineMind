import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { resetClientState } from "../api/client.ts";
import { resetServerClock } from "../lib/serverClock.ts";

afterEach(() => {
  cleanup();
  localStorage.clear();
  resetClientState();
  resetServerClock();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
