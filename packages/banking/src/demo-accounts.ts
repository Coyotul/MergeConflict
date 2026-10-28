import type { Role } from "./types";

// Public synthetic credentials, intentionally shown on the sign-in screen.
// These accounts must never be used as a production authentication mechanism.
export const DEMO_ACCOUNTS: Record<Role, { name: string; email: string; password: string }> = {
  customer: { name: "Alex Morgan", email: "alex@example.test", password: "ClientDemo123!" },
  reviewer: { name: "Jamie Carter", email: "jamie@example.test", password: "AgentDemo123!" },
};