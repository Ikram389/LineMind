/**
 * Screenshots of every page at three sizes, as the demo users who use them.
 * Output: screenshots/<SHOT_LABEL>/<size>/<page>.png   (SHOT_LABEL defaults to "before")
 *
 *   docker compose run --rm e2e npm run screenshots
 *   docker compose run --rm -e SHOT_LABEL=after e2e npm run screenshots
 */
import { type Page, test } from "@playwright/test";

const LABEL = process.env.SHOT_LABEL ?? "before";
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";
const LINE = process.env.SHOT_LINE ?? "1";
/** Only some pages, e.g. SHOT_PAGES=01,15,16 (name prefixes); default all. */
const ONLY = (process.env.SHOT_PAGES ?? "").split(",").filter(Boolean);

const SIZES = [
  { name: "laptop", width: 1440, height: 900 },
  { name: "tablet", width: 1280, height: 800 },
  { name: "tv", width: 1920, height: 1080 },
];

// Which demo user looks at which page (each page as its main audience sees it).
const PAGES: { name: string; path: string; role: string; dark?: boolean }[] = [
  { name: "01-line-overview", path: `/lines/${LINE}`, role: "production_supervisor" },
  { name: "02-line-overview-operator", path: `/lines/${LINE}`, role: "machine_operator" },
  { name: "03-machine", path: `/lines/${LINE}/machines/5`, role: "production_supervisor" },
  { name: "04-downtime", path: `/lines/${LINE}/downtime`, role: "production_supervisor" },
  { name: "05-unclassified", path: `/lines/${LINE}/unclassified`, role: "machine_operator" },
  { name: "06-reasons", path: `/lines/${LINE}/reasons`, role: "factory_manager" },
  { name: "07-quality", path: `/lines/${LINE}/quality`, role: "quality_inspector" },
  { name: "08-quality-setup", path: `/lines/${LINE}/quality-setup`, role: "factory_manager" },
  { name: "09-alerts", path: "/alerts", role: "production_supervisor" },
  { name: "10-alert-rules", path: "/alert-rules", role: "factory_manager" },
  { name: "11-maintenance", path: "/maintenance", role: "maintenance_technician" },
  { name: "12-maintenance-action", path: "/maintenance/1", role: "maintenance_technician" },
  { name: "13-settings", path: "/settings", role: "production_supervisor" },
  { name: "14-lines", path: "/", role: "analyst" },
  { name: "15-line-overview-tv", path: `/lines/${LINE}?tv=1`, role: "production_supervisor" },
  { name: "16-line-overview-dark", path: `/lines/${LINE}`, role: "production_supervisor", dark: true },
  { name: "17-assistant", path: "/assistant", role: "production_supervisor" },
];

/** Switches the theme through the account menu (only exists after the redesign). */
async function setTheme(page: Page, theme: "Light" | "Dark"): Promise<boolean> {
  const menu = page.getByRole("button", { name: /Account menu/ });
  if ((await menu.count()) === 0) return false;
  await menu.click();
  await page.getByRole("button", { name: theme, exact: true }).click();
  await page.keyboard.press("Escape");
  return true;
}

async function login(page: Page, role: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(`${role}@demo-beverages.test`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

for (const size of SIZES) {
  test(`screenshots at ${size.name} (${size.width}x${size.height})`, async ({ browser }) => {
    const pages = PAGES.filter((p) => ONLY.length === 0 || ONLY.some((prefix) => p.name.startsWith(prefix)));
    const roles = [...new Set(pages.map((p) => p.role))];
    for (const role of roles) {
      const context = await browser.newContext({ viewport: { width: size.width, height: size.height } });
      const page = await context.newPage();
      await login(page, role);
      for (const target of pages.filter((p) => p.role === role)) {
        await page.goto(target.path);
        await page.waitForLoadState("networkidle").catch(() => {});
        if (target.dark && !(await setTheme(page, "Dark"))) continue;
        await page.waitForTimeout(1500); // charts and live data settle
        await page.screenshot({ path: `screenshots/${LABEL}/${size.name}/${target.name}.png`, fullPage: true });
        if (target.dark) await setTheme(page, "Light");
      }
      await context.close();
    }
    // The login page itself.
    const context = await browser.newContext({ viewport: { width: size.width, height: size.height } });
    const page = await context.newPage();
    await page.goto("/login");
    await page.screenshot({ path: `screenshots/${LABEL}/${size.name}/00-login.png` });
    await context.close();
  });
}
