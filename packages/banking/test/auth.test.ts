import { test } from "node:test";
import assert from "node:assert/strict";
import { DEMO_ACCOUNTS } from "../src/demo-accounts";
import { CUSTOMER_ACTOR, REVIEWER_ACTOR } from "../src/seed";
import { sessionSchema, storedSessionSchema } from "../src/schemas";
import { DEMO_SESSION_LIFETIME_MS, DemoSessions } from "../server/auth";
import { DomainError } from "../src/workflow";

test("demo credentials are validated and bound to the selected customer or bank-agent role", () => {
  const sessions = new DemoSessions();
  for (const role of ["customer", "reviewer"] as const) {
    const { email, password } = DEMO_ACCOUNTS[role];
    const input = sessionSchema.parse({ role, email: `  ${email.toUpperCase()}  `, password });
    const session = sessions.create(input);
    assert.deepEqual(session.actor, role === "customer" ? CUSTOMER_ACTOR : REVIEWER_ACTOR);
    assert.deepEqual(sessions.require(session.token), session.actor);
    assert.equal(storedSessionSchema.safeParse(session).success, true);
    assert.equal("password" in session, false);
    assert.throws(() => sessions.create({ ...input, password: "incorrect" }), (error) => error instanceof DomainError && error.code === "INVALID_CREDENTIALS");
    assert.throws(() => sessions.create({ ...input, email: "unknown@example.test" }), /does not match/);
    assert.throws(() => sessions.create({ ...input, role: role === "customer" ? "reviewer" : "customer" }), /does not match/);
  }
  assert.equal(sessionSchema.safeParse({ role: "reviewer" }).success, false);
  assert.equal(sessionSchema.safeParse({ role: "customer", email: "not-an-email", password: "demo" }).success, false);
  assert.equal(sessionSchema.safeParse({ role: "customer", email: DEMO_ACCOUNTS.customer.email, password: "" }).success, false);
});

test("opaque demo sessions expire, can be revoked and are not shared across server restarts", () => {
  const sessions = new DemoSessions();
  const now = Date.parse("2026-10-28T10:00:00Z");
  const { email, password } = DEMO_ACCOUNTS.customer;
  const input = sessionSchema.parse({ role: "customer", email, password });
  const session = sessions.create(input, now);
  assert.equal(Date.parse(session.expiresAt), now + DEMO_SESSION_LIFETIME_MS);
  assert.deepEqual(sessions.require(session.token, now + DEMO_SESSION_LIFETIME_MS - 1), CUSTOMER_ACTOR);
  assert.throws(() => sessions.require(session.token, now + DEMO_SESSION_LIFETIME_MS), /session has ended/);
  const next = sessions.create(input, now);
  assert.notEqual(next.token, session.token);
  sessions.revoke(next.token);
  assert.throws(() => sessions.require(next.token, now), /session has ended/);
  const active = sessions.create(input, now);
  assert.throws(() => new DemoSessions().require(active.token, now), /session has ended/);
  assert.throws(() => sessions.require("forged-token", now), /session has ended/);
});