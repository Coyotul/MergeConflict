import type { Role } from "./types";

// Public synthetic credentials, intentionally shown on the sign-in screen.
// These accounts must never be used as a production authentication mechanism.
export interface DemoCustomerAccount {
  customerId: string;
  name: string;
  email: string;
  password: string;
  scenario: string;
  monthlyIncome: string;
}

const CUSTOMER_PASSWORD = "ClientDemo123!";

// One sign-in per synthetic credit customer. The customerId matches the record
// held by the orchestrator's credit sources, so each login drives its own scenario.
export const DEMO_CUSTOMERS: DemoCustomerAccount[] = [
  { customerId: "cust-alex-morgan", name: "Alex Morgan", email: "alex@example.test", password: CUSTOMER_PASSWORD, scenario: "Eligible", monthlyIncome: "8500.00" },
  { customerId: "cust-elena-popa", name: "Elena Popa", email: "elena@example.test", password: CUSTOMER_PASSWORD, scenario: "Eligible, no debt", monthlyIncome: "4500.00" },
  { customerId: "cust-radu-mihai", name: "Radu Mihai", email: "radu@example.test", password: CUSTOMER_PASSWORD, scenario: "Eligible, existing loans", monthlyIncome: "5000.00" },
  { customerId: "cust-dan-ionescu", name: "Dan Ionescu", email: "dan@example.test", password: CUSTOMER_PASSWORD, scenario: "Debt over 40%", monthlyIncome: "5996.25" },
  { customerId: "cust-andrei-stan", name: "Andrei Stan", email: "andrei@example.test", password: CUSTOMER_PASSWORD, scenario: "Income too low", monthlyIncome: "2300.00" },
  { customerId: "cust-ioana-marin", name: "Ioana Marin", email: "ioana@example.test", password: CUSTOMER_PASSWORD, scenario: "91 days late", monthlyIncome: "6000.00" },
  { customerId: "cust-victor-dobre", name: "Victor Dobre", email: "victor@example.test", password: CUSTOMER_PASSWORD, scenario: "Open insolvency", monthlyIncome: "5500.00" },
  { customerId: "cust-maria-stoica", name: "Maria Stoica", email: "maria@example.test", password: CUSTOMER_PASSWORD, scenario: "Restructured loan – review", monthlyIncome: "6500.00" },
  { customerId: "cust-mihai-ilie", name: "Mihai Ilie", email: "mihai@example.test", password: CUSTOMER_PASSWORD, scenario: "Self-employed – review", monthlyIncome: "7000.00" },
];

const ALEX = DEMO_CUSTOMERS[0];

export const DEMO_ACCOUNTS: Record<Role, { name: string; email: string; password: string }> = {
  customer: { name: ALEX.name, email: ALEX.email, password: ALEX.password },
  reviewer: { name: "Jamie Carter", email: "jamie@example.test", password: "AgentDemo123!" },
};
