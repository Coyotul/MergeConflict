import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { FileStore } from "./store";
import { createDemoServer } from "./http";

for (const envFile of [".env.local", ".env"]) {
  if (existsSync(envFile)) {
    try {
      process.loadEnvFile(envFile);
    } catch {
      // ignore
    }
  }
}

const path = resolve(process.env.DEMO_STORE_PATH ?? "data/local/frontend-demo.json");
const store = await FileStore.open(path);
const server = createDemoServer(store);
const port = Number(process.env.DEMO_API_PORT ?? "4010");
server.listen(port, "127.0.0.1", () => console.log(`Luma demo API: http://127.0.0.1:${port} · synthetic data only · ${path}`));
server.on("error", (error) => { console.error("Demo API failed:", error.message); process.exitCode = 1; });
process.on("SIGTERM", () => server.close());
process.on("SIGINT", () => server.close());
