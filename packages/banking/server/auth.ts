import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { DEMO_ACCOUNTS, DEMO_CUSTOMERS } from "../src/demo-accounts";
import { REVIEWER_ACTOR } from "../src/seed";
import type { SessionInput } from "../src/schemas";
import type { Actor, Session } from "../src/types";
import { DomainError } from "../src/workflow";

export const DEMO_SESSION_LIFETIME_MS = 8 * 60 * 60 * 1000;

export class DemoSessions {
  private readonly sessions = new Map<string, { actor: Actor; expiresAt: number }>();

  create(input: SessionInput, now = Date.now()): Session {
    const customer = input.role === "customer" ? DEMO_CUSTOMERS.find((c) => c.email === input.email) : undefined;
    const account = input.role === "customer" ? customer ?? DEMO_ACCOUNTS.customer : DEMO_ACCOUNTS.reviewer;
    const supplied = createHash("sha256").update(input.password).digest();
    const expected = createHash("sha256").update(account.password).digest();
    const passwordMatches = timingSafeEqual(supplied, expected);
    if (input.email !== account.email || !passwordMatches) {
      throw new DomainError("INVALID_CREDENTIALS", "The email or password does not match this demo workspace.", 401);
    }

    for (const [token, session] of this.sessions) {
      if (session.expiresAt <= now) this.sessions.delete(token);
    }
    const actor: Actor = customer ? { id: customer.customerId, name: customer.name, role: "customer" } : REVIEWER_ACTOR;
    const token = randomUUID();
    const expiresAt = now + DEMO_SESSION_LIFETIME_MS;
    this.sessions.set(token, { actor, expiresAt });
    return { token, actor, expiresAt: new Date(expiresAt).toISOString() };
  }

  require(token: string, now = Date.now()): Actor {
    const session = this.sessions.get(token);
    if (!session || session.expiresAt <= now) {
      this.sessions.delete(token);
      throw new DomainError("UNAUTHORIZED", "Your demo session has ended. Sign in again to continue.", 401);
    }
    return session.actor;
  }

  revoke(token: string) {
    this.sessions.delete(token);
  }
}