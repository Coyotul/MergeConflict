import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AddressInfo } from "node:net";
import { FileStore } from "../server/store";
import { createDemoServer } from "../server/http";
import { DEMO_ACCOUNTS } from "../src/demo-accounts";

async function fixture() {
  const directory = await mkdtemp(join(tmpdir(), "luma-test-"));
  const path = join(directory, "demo.json");
  const store = await FileStore.open(path);
  const server = createDemoServer(store);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { path, store, url, close: async () => {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    await rm(directory, { recursive: true });
  } };
}
test("API: health, auth, owner/reviewer roles, invalid input, persistence and CORS", async () => {
  const f = await fixture();
  try {
    assert.equal((await fetch(`${f.url}/health`)).status, 200);
    assert.equal((await fetch(`${f.url}/api/snapshot`)).status, 401);
    assert.equal((await fetch(`${f.url}/health`, { headers: { Origin: "https://untrusted.example" } })).status, 403);
    const { email, password } = DEMO_ACCOUNTS.customer;
    const login = await fetch(`${f.url}/api/session`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: "customer", email, password }) });
    assert.equal(login.status, 200);
    const token = (await login.json()).data.token;
    const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
    const input = { amount: "30000", months: 36, productId: "personal", idempotencyKey: crypto.randomUUID() };
    const response = await fetch(`${f.url}/api/applications`, { method: "POST", headers, body: JSON.stringify(input) });
    assert.equal(response.status, 200);
    const app = (await response.json()).data;
    const duplicate = await fetch(`${f.url}/api/applications`, { method: "POST", headers, body: JSON.stringify(input) });
    assert.equal((await duplicate.json()).data.id, app.id);
    const denied = await fetch(`${f.url}/api/applications/${app.id}/review`, { method: "POST", headers, body: JSON.stringify({ action: "approve", reason: "This role must not approve.", evidenceReviewed: true, idempotencyKey: crypto.randomUUID() }) });
    assert.equal(denied.status, 403);
    const invalid = await fetch(`${f.url}/api/applications`, { method: "POST", headers, body: JSON.stringify({ ...input, amount: "NaN" }) });
    assert.equal(invalid.status, 400);
    const reopened = await FileStore.open(f.path);
    assert.ok(reopened.read((s) => s.applications.some((a) => a.id === app.id)));
    const persisted = JSON.parse(await readFile(f.path, "utf8"));
    assert.equal(persisted.applications.length, 2);
  } finally { await f.close(); }
});
test("API: credential sign-in rejects role spoofing, enforces bank-agent permissions and revokes logout", async () => {
  const f = await fixture();
  const signIn = (input: unknown) => fetch(`${f.url}/api/session`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  try {
    assert.equal((await signIn({ role: "reviewer" })).status, 400);
    const { email, password } = DEMO_ACCOUNTS.customer;
    const wrongPassword = await signIn({ role: "customer", email, password: "incorrect" });
    assert.equal(wrongPassword.status, 401);
    assert.equal((await wrongPassword.json()).error.code, "INVALID_CREDENTIALS");
    assert.equal((await signIn({ role: "reviewer", email, password })).status, 401);

    const account = DEMO_ACCOUNTS.reviewer;
    const response = await signIn({ role: "reviewer", email: account.email, password: account.password });
    assert.equal(response.status, 200);
    const { data: session } = await response.json();
    assert.equal(session.actor.role, "reviewer");
    assert.ok(Date.parse(session.expiresAt) > Date.now());
    const headers = { Authorization: `Bearer ${session.token}`, "Content-Type": "application/json" };
    const snapshot = await fetch(`${f.url}/api/snapshot`, { headers });
    assert.equal((await snapshot.json()).data.actor.role, "reviewer");
    const forbidden = await fetch(`${f.url}/api/chat`, { method: "POST", headers, body: JSON.stringify({ text: "I want a loan" }) });
    assert.equal(forbidden.status, 403);
    const logout = await fetch(`${f.url}/api/session/logout`, { method: "POST", headers, body: "{}" });
    assert.equal(logout.status, 200);
    assert.deepEqual((await logout.json()).data, { signedOut: true });
    assert.equal((await fetch(`${f.url}/api/snapshot`, { headers })).status, 401);
    assert.equal((await fetch(`${f.url}/api/session/logout`, { method: "POST", headers, body: "{}" })).status, 401);
    const persisted = await readFile(f.path, "utf8");
    assert.equal(persisted.includes(password), false);
    assert.equal(persisted.includes(account.password), false);
    assert.equal(persisted.includes(session.token), false);
  } finally { await f.close(); }
});
test("corrupt persistence never silently resets; failed transactions roll back", async () => {
  const f = await fixture();
  try {
    const count = f.store.read((s) => s.applications.length);
    await assert.rejects(f.store.transaction((s) => { s.applications = []; throw new Error("Failure"); }));
    assert.equal(f.store.read((s) => s.applications.length), count);
    await writeFile(f.path, "broken-json");
    await assert.rejects(FileStore.open(f.path));
  } finally { await f.close(); }
});
