import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const processes = [
  ["demo API", ["--import", "tsx", "packages/banking/server/index.ts"], root],
  ["customer", [resolve(root, "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", "3000", "--webpack"], resolve(root, "apps/customer")],
  ["reviewer", [resolve(root, "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", "3001", "--webpack"], resolve(root, "apps/staff")],
];
console.log("\nLuma · synthetic local prototype\nCustomer: http://127.0.0.1:3000\nReviewer: http://127.0.0.1:3001\nDemo API: http://127.0.0.1:4010/health\nAI orchestrator: http://127.0.0.1:8000/docs (start separately: uvicorn src.api.app:create_app --factory)\n");
const children = processes.map(([name, args, cwd]) => {
  const child = spawn(process.execPath, args, { cwd, stdio: "inherit", env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" } });
  child.on("error", (error) => { console.error(`${name} failed:`, error.message); shutdown(1); });
  child.on("exit", (code) => { if (!stopping) shutdown(code ?? 1); });
  return child;
});
let stopping = false;
function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill("SIGTERM");
  setTimeout(() => process.exit(code), 500).unref();
}
process.on("SIGINT", () => shutdown());
process.on("SIGTERM", () => shutdown());
