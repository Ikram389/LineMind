/**
 * Automatic accessibility check (axe, WCAG 2.1 A/AA) on the main pages, in light and dark.
 * Fails on "serious" or "critical" violations and prints every finding.
 *
 *   docker compose run --rm e2e npm run a11y
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";
const LINE = process.env.SHOT_LINE ?? "1";
/** Pages to check; set A11Y_PAGES=overview,tv to check only some. */
const ONLY = (process.env.A11Y_PAGES ?? "").split(",").filter(Boolean);

const PAGES: { name: string; path: string }[] = [
  { name: "overview", path: `/lines/${LINE}` },
  { name: "tv", path: `/lines/${LINE}?tv=1` },
  { name: "downtime", path: `/lines/${LINE}/downtime` },
  { name: "quality", path: `/lines/${LINE}/quality` },
  { name: "alerts", path: "/alerts" },
  { name: "maintenance", path: "/maintenance" },
  { name: "settings", path: "/settings" },
];

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill("production_supervisor@demo-beverages.test");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

async function setTheme(page: Page, theme: "Light" | "Dark"): Promise<void> {
  await page.getByRole("button", { name: /Account menu/ }).click();
  await page.getByRole("button", { name: theme, exact: true }).click();
  await page.keyboard.press("Escape");
}

for (const theme of ["Light", "Dark"] as const) {
  for (const target of PAGES.filter((p) => ONLY.length === 0 || ONLY.includes(p.name))) {
    test(`${target.name} (${theme.toLowerCase()}) has no serious accessibility violations`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await login(page);
      await page.goto(`/lines/${LINE}`);
      await setTheme(page, theme);
      await page.goto(target.path);
      await page.waitForLoadState("networkidle").catch(() => {});
      await page.waitForTimeout(1000);

      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      for (const v of results.violations) {
        console.log(`[${target.name}/${theme}] ${v.impact} ${v.id}: ${v.help} (${v.nodes.length})`);
        for (const node of v.nodes.slice(0, 3)) console.log(`    ${node.target.join(" ")}  ${node.failureSummary?.split("\n")[1] ?? ""}`);
      }
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious.map((v) => v.id)).toEqual([]);
    });
  }
}
