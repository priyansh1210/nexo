import { expect, test, type Page } from "@playwright/test";

// The Phase 6 gate: the full Acme conversation, as a CSM has it, against the demo stack.
// The demo data and the mock model are deterministic, so the same story comes out every time.

const PASSWORD = "nexo-demo";

async function signIn(page: Page, email: string) {
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Sign-ins for one email run one at a time (the rate limit), and both viewports use the same one.
  await expect(page).toHaveURL(/\/chat/, { timeout: 20_000 });
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Ask about an account").fill(question);
  await page.getByRole("button", { name: "Send" }).click();
  const turn = page.getByRole("listitem").filter({ hasText: question }).last();
  await expect(turn.getByText("Checking the data…")).toBeHidden({ timeout: 30_000 });
  return turn;
}

test("a CSM finds the at-risk renewal, investigates it, and approves an email", async ({ page }) => {
  await signIn(page, "maya.okafor@nexo.example");

  // 1. Which renewals need attention: Acme is among them, in the inline table.
  const renewals = await ask(page, "Which customers renewing next month need attention?");
  await expect(renewals.getByText("3 accounts renewing next month need attention").first()).toBeVisible();
  await expect(renewals.getByRole("link", { name: "Acme Corp" })).toBeVisible();

  // 2. Investigate: observed facts are cited, and the cause is marked as a possibility.
  const investigation = await ask(page, "Investigate Acme.");
  const observed = investigation.getByRole("region", { name: "Observed" });
  await expect(observed.getByText(/fell 40%/)).toBeVisible();
  await expect(investigation.getByRole("region", { name: "Possible cause, not confirmed" })).toBeVisible();

  // A source chip opens the evidence behind a claim, with how fresh it is.
  await observed.getByRole("button", { name: /^Source \d+$/ }).first().click();
  const panel = page.getByRole("complementary");
  await expect(panel.getByText("Data behind it")).toBeVisible();
  await expect(panel.getByText(/updated .* ago/).first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();

  // 3. Draft an email: nothing is sent until it is approved.
  const drafted = await ask(page, "Email Acme's admin about the import ticket.");
  const card = drafted.getByRole("region", { name: "Send an email" });
  await expect(card.getByText(/Re: Bulk CSV import/)).toBeVisible();
  await expect(card.getByText("Nothing happens until you approve.", { exact: false })).toBeVisible();
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByRole("status")).toContainText("The email is queued");

  // 4. The approval is in the audit trail.
  await card.getByRole("link", { name: "Audit trail" }).click();
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await expect(page.getByText("Approved the email")).toBeVisible();
  await expect(page.getByText("Checked the email took effect")).toBeVisible();
});

test("a viewer's request for an email is refused with the reason", async ({ page }) => {
  await signIn(page, "viewer@nexo.example");
  const drafted = await ask(page, "Email Acme's admin about the import ticket.");
  const card = drafted.getByRole("region", { name: "Send an email" });
  await expect(card.getByRole("status")).toContainText("Viewers cannot send email");
  await expect(card.getByRole("button", { name: "Approve" })).toHaveCount(0);
});
