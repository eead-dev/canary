import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

test("desktop evidence loads, reloads, and has an accessible chart", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "0x0AA", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Run Toyota RAV4 Demo", exact: true })
    .first()
    .click();
  await expect(page.getByTestId("reconstruction-chart")).toBeVisible();
  await expect(
    page.getByText("LAYOUT AMBIGUOUS", { exact: true }),
  ).toBeVisible();
  await expect(page).toHaveScreenshot("desktop-workspace.png");
  await mkdir(resolve("../docs/assets/screenshots"), { recursive: true });
  await page.screenshot({
    path: resolve("../docs/assets/screenshots/desktop-workspace.png"),
  });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(errors).toEqual([]);
});

test("candidate inspection is URL-backed without changing the conclusion", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "0x0AA", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Inspect rank 6", exact: true })
    .click();
  await expect(page).toHaveURL(/candidate=170-33-15-big-u/);
  await expect(page.locator("#layout")).toContainText("Inspecting rank #6");
  await expect(page.locator(".encoding")).toHaveText(
    "start 34 · 15-bit · big-endian · signed",
  );
  await page.reload();
  await expect(page.locator("#layout")).toContainText("Inspecting rank #6");
  await page.locator("#ambiguity").scrollIntoViewIfNeeded();
  await expect(page.locator(".encoding-grid")).toHaveScreenshot(
    "selected-ambiguity.png",
  );
  await page
    .getByRole("button", { name: "Inspect rank 2", exact: true })
    .click();
  await page.goBack();
  await expect(page.locator("#layout")).toContainText("Inspecting rank #6");
});

test("mobile portrait is intentional, keyboard usable and has no overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByTestId("reconstruction-chart")).toBeVisible();
  await expect(page).toHaveScreenshot("mobile-workspace.png", {
    fullPage: true,
  });
  await page.screenshot({
    path: resolve("../docs/assets/screenshots/mobile-workspace.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Session", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Session", exact: true }),
  ).toBeFocused();
  const slider = page.getByRole("slider");
  await slider.focus();
  await page.keyboard.press("End");
  await expect(slider).toHaveValue("578");
  await page.keyboard.press("Home");
  await expect(slider).toHaveValue("0");
  for (const width of [360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
});

test("expanded long affine content remains usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Explore all 12 layouts" }).click();
  await expect(page.locator(".layout-row")).toHaveCount(12);
  await page
    .getByText("Inspect recorded raw-to-raw relationships", { exact: true })
    .click();
  await expect(page.locator("#ambiguity")).toHaveScreenshot(
    "expanded-ambiguity.png",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("missing optional evidence has a truthful empty state", async ({
  page,
}) => {
  await page.route("**/agent_run_01.json", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.trace = [];
    body.turn_trace = [];
    delete body.conclusion.rationale;
    await route.fulfill({ json: body });
  });
  await page.route("**/blind_results.json", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.distinct_hypotheses = [];
    await route.fulfill({ json: body });
  });
  await page.goto("/");
  await expect(
    page.getByText("Tool trace not included in this evidence bundle."),
  ).toBeVisible();
  await expect(
    page.getByText("Decision reference not exported."),
  ).toBeVisible();
  await expect(page.locator("#agent")).toHaveScreenshot(
    "missing-optional-evidence.png",
  );
});

test("missing essential evidence fails clearly and can retry", async ({
  page,
}) => {
  await page.route("**/blind_results.json", (route) =>
    route.fulfill({ status: 404, body: "Missing" }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText(
    "Unable to open this capture.",
  );
  await page.unroute("**/blind_results.json");
  await page.getByRole("button", { name: "Retry loading evidence" }).click();
  await expect(
    page.getByRole("heading", { name: "0x0AA", exact: true }),
  ).toBeVisible();
});
