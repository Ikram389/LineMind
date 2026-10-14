import { describe, expect, it } from "vitest";

import type { MessageKey } from "./en.ts";
import { t } from "./t.ts";

describe("t", () => {
  it("fills in placeholders", () => {
    expect(t("maint.due", { date: "2026-10-20" })).toBe("due 2026-10-20");
  });

  it("shows a missing key instead of breaking the page", () => {
    expect(t("alerts.subject.something_new" as MessageKey)).toBe("alerts.subject.something_new");
  });
});
