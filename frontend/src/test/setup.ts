import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { resetClientState } from "../api/client.ts";
import { resetServerClock } from "../lib/serverClock.ts";

// findBy…/waitFor wait up to 5 s: with every file running in parallel on the slow
// Docker volume, 1 s (the default) is sometimes not enough. Assertions are unchanged.
configure({ asyncUtilTimeout: 5_000 });

afterEach(() => {
  cleanup();
  localStorage.clear();
  resetClientState();
  resetServerClock();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
