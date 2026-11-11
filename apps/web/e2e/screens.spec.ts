import { expect, test } from "@playwright/test";

// Every screen renders against the real stack, and the workspace forms save. A page can build and
// still fail when it is served, so each one is opened here.

test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("aiko.tanaka@nexo.example"); // owns Belmark Analytics
  await page.getByLabel("Password").fill("nexo-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/chat/, { timeout: 20_000 });
});

test("every screen opens", async ({ page }) => {
  for (const [path, heading] of [
    ["/accounts", "Accounts"],
    ["/accounts/acct_acme", "Acme Corp"],
    ["/tasks", "Tasks"],
    ["/audit", "Audit log"],
    ["/health", "Data health"],
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(page.getByText("This screen could not load")).toHaveCount(0);
  }
  await page.goto("/accounts/acct_does_not_exist");
  await expect(page.getByText(/could not be found/i)).toBeVisible();
});

test("a note and a task added on an account appear on it", async ({ page }, testInfo) => {
  const stamp = `${testInfo.project.name} ${Date.now()}`;
  await page.goto("/accounts/acct_0002");

  await page.getByLabel("New note").fill(`Call booked with finance (${stamp})`);
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText(`Call booked with finance (${stamp})`)).toBeVisible();

  await page.getByLabel("New task").fill(`Send the renewal quote (${stamp})`);
  await page.getByRole("button", { name: "Add task" }).click();
  const task = page.getByRole("listitem").filter({ hasText: `Send the renewal quote (${stamp})` });
  await expect(task).toBeVisible();
  await task.getByRole("button", { name: /^Mark done/ }).click();
  await expect(task.getByRole("button", { name: /^Reopen/ })).toBeVisible();
});

test("signing in never leaves the site, and no site may frame it", async ({ page, context }) => {
  await context.clearCookies();
  const response = await page.goto("/login?next=/%5Cevil.example");
  expect(response?.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  await page.getByLabel("Email").fill("aiko.tanaka@nexo.example");
  await page.getByLabel("Password").fill("nexo-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/localhost:3000\/chat/, { timeout: 20_000 });
});
