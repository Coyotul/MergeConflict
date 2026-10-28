import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  { settings: { next: { rootDir: ["apps/customer/", "apps/staff/"] } } },
  globalIgnores(["**/.next/**", "**/next-env.d.ts", "**/node_modules/**", "test-results/**", "playwright-report/**", "data/**"]),
]);
