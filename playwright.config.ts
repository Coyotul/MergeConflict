import { defineConfig, devices } from "@playwright/test";

const orchestratorUrl = new URL(process.env.ORCHESTRATOR_E2E_URL ?? "http://127.0.0.1:8000");

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "frontend.spec.ts",
  timeout: 90000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 }, baseURL: "http://127.0.0.1:3000", trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    { command: "node --import tsx packages/banking/server/index.ts", url: "http://127.0.0.1:4010/health", reuseExistingServer: false, env: { DEMO_STORE_PATH: `data/local/frontend-e2e-${Date.now()}.json` } },
    {
      command: `"${process.env.ORCHESTRATOR_PYTHON ?? "python"}" -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port ${orchestratorUrl.port || "8000"}`,
      url: `${orchestratorUrl.origin}/health`,
      timeout: 60000,
      reuseExistingServer: false,
      env: { ORCHESTRATOR_MODEL: "fake", ORCHESTRATOR_SESSION_STORE: "memory", ORCHESTRATOR_UPLOADS_DIR: `data/local/e2e-uploads-${Date.now()}` },
    },
    { command: "npm run dev:customer", url: "http://127.0.0.1:3000", timeout: 120000, reuseExistingServer: false, env: { NEXT_TELEMETRY_DISABLED: "1", NEXT_PUBLIC_ORCHESTRATOR_URL: orchestratorUrl.origin } },
    { command: "npm run dev:staff", url: "http://127.0.0.1:3001", timeout: 120000, reuseExistingServer: false, env: { NEXT_TELEMETRY_DISABLED: "1" } },
  ],
});
