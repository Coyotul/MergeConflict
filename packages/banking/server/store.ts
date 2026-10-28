import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { DemoStore } from "../src/types";
import { seedStore } from "../src/seed";

export class FileStore {
  private tail: Promise<unknown> = Promise.resolve();
  private constructor(public readonly path: string, private state: DemoStore) {}
  static async open(path: string) {
    let state: DemoStore;
    try {
      state = JSON.parse(await readFile(path, "utf8"));
      if (state.version !== 1 || !Array.isArray(state.applications) || !Array.isArray(state.customers) || !Array.isArray(state.products) || !Array.isArray(state.loans) || !state.messages || !state.consents || !Array.isArray(state.audit) || !Array.isArray(state.notifications) || !Array.isArray(state.idempotency)) throw new Error("Invalid demo store structure. Restore or move the file explicitly; it will not be silently reset.");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      state = seedStore();
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, JSON.stringify(state, null, 2), { flag: "wx" });
    }
    return new FileStore(path, state);
  }
  read<T>(fn: (state: DemoStore) => T): T { return structuredClone(fn(this.state)); }
  transaction<T>(fn: (state: DemoStore) => Promise<T> | T): Promise<T> {
    const operation = this.tail.then(async () => {
      const draft = structuredClone(this.state);
      const result = await fn(draft);
      const temporary = `${this.path}.${crypto.randomUUID()}.tmp`;
      await writeFile(temporary, JSON.stringify(draft, null, 2));
      await rename(temporary, this.path);
      this.state = draft;
      return structuredClone(result);
    });
    this.tail = operation.catch(() => undefined);
    return operation;
  }
}
