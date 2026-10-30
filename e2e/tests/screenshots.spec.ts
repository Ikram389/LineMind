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
/** A range with data for the analysis pages (the demo data is not always recent). */
/** The maintenance action on page 12 (demo_video_prep prints the demo one). */
const ACTION = process.env.SHOT_ACTION ?? "1";
const RANGE = process.env.SHOT_RANGE ?? "start=2026-10-17T05:00:00Z&end=2026-10-17T21:00:00Z";
/** SHOT_THEME=dark takes every shot in the dark theme. */
const THEME = process.env.SHOT_THEME === "dark" ? "Dark" : null;
/** Only some pages, e.g. SHOT_PAGES=01,15,16 (name prefixes); default all. */
const ONLY = (process.env.SHOT_PAGES ?? "").split(",").filter(Boolean);

const SIZES = [
  { name: "laptop", width: 1440, height: 900 },
  { name: "tablet", width: 1280, height: 800 },
  { name: "tv", width: 1920, height: 1080 },
];

// Which demo user looks at which page (each page as its main audience sees it).
type Target = {
  name: string;
  path: string;
  role: string;
  dark?: boolean;
  then?: (page: Page) => Promise<void>;
  /** Drawers and dialogs are fixed to the viewport: shoot the viewport, not the full page. */
  overlay?: boolean;
};

const PAGES: Target[] = [
  { name: "01-line-overview", path: `/lines/${LINE}`, role: "production_supervisor" },
  { name: "02-line-overview-operator", path: `/lines/${LINE}`, role: "machine_operator" },
  { name: "03-machine", path: `/lines/${LINE}/machines/5`, role: "production_supervisor" },
  { name: "04-downtime", path: `/lines/${LINE}/downtime?${RANGE}`, role: "production_supervisor" },
  { name: "04b-downtime-incident", path: `/lines/${LINE}/downtime?${RANGE}&incident=285`, role: "production_supervisor", overlay: true },
  {
    name: "04c-downtime-classify",
    path: `/lines/${LINE}/downtime?${RANGE}`,
    role: "production_supervisor",
    overlay: true,
    then: async (page) => {
      await page.getByRole("button", { name: /^(Classify|Change)$/ }).first().click();
    },
  },
  { name: "05-unclassified", path: `/lines/${LINE}/unclassified`, role: "machine_operator" },
  { name: "06-reasons", path: `/lines/${LINE}/reasons`, role: "factory_manager" },
  { name: "07-quality", path: `/lines/${LINE}/quality`, role: "quality_inspector" },
  { name: "08-quality-setup", path: `/lines/${LINE}/quality-setup`, role: "factory_manager" },
  { name: "09-alerts", path: "/alerts", role: "production_supervisor" },
  { name: "10-alert-rules", path: "/alert-rules", role: "factory_manager" },
  { name: "11-maintenance", path: "/maintenance", role: "maintenance_technician" },
  { name: "12-maintenance-action", path: `/maintenance/${ACTION}`, role: "maintenance_technician" },
  { name: "13-settings", path: "/settings", role: "production_supervisor" },
  { name: "14-lines", path: "/", role: "analyst" },
  { name: "15-line-overview-tv", path: `/lines/${LINE}?tv=1`, role: "production_supervisor" },
  { name: "16-line-overview-dark", path: `/lines/${LINE}`, role: "production_supervisor", dark: true },
  { name: "17-assistant", path: "/assistant", role: "production_supervisor" },
  {
    name: "18-notifications",
    path: `/lines/${LINE}`,
    role: "production_supervisor",
    overlay: true,
    then: async (page) => {
      await page.getByRole("button", { name: /^Notifications/ }).click();
      const list = page.getByTestId("bell-list");
      await list.waitFor();
      const box = await list.evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight, bottom: el.getBoundingClientRect().bottom }));
      console.log(`bell list: content ${box.scroll}px, visible ${box.client}px, bottom at ${Math.round(box.bottom)}px of ${page.viewportSize()?.height}px`);
    },
  },
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

/** Wait until the page has its data: no skeleton and no "Loading…" left (max 30 s). */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page
    .waitForFunction(
      () => !document.querySelector(".animate-pulse") && !document.body.innerText.includes("Loading…"),
      undefined,
      { timeout: 30_000 },
    )
    .catch(() => {});
  await page.waitForTimeout(1000); // charts animate in
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
      if (THEME) {
        await page.goto("/");
        await page.waitForLoadState("networkidle").catch(() => {});
        await setTheme(page, THEME);
      }
      for (const target of pages.filter((p) => p.role === role)) {
        await page.goto(target.path);
        await settle(page);
        if (target.dark && !(await setTheme(page, "Dark"))) continue;
        if (target.then) {
          await target.then(page).catch(() => {});
          await page.waitForTimeout(800);
        }
        await page.screenshot({ path: `screenshots/${LABEL}/${size.name}/${target.name}.png`, fullPage: !target.overlay });
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
