import { defineConfig, devices } from "@playwright/test";

// E2E 覆盖桌面与移动视口；开发时先启动前端 (pnpm dev) 与后端 (uv run uvicorn)。
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5180",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-375", use: { ...devices["iPhone SE"] } },
  ],
});
