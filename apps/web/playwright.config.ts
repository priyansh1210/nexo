import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against a running stack (`make demo`), as a person would use it.
// BASE_URL points elsewhere when needed. Browsers: `pnpm exec playwright install chromium`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000, // the Acme conversation is three assistant turns; slow machines need the room
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
