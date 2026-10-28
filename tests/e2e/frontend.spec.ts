import { test, expect, type Page, type Locator } from "@playwright/test";
import { DEMO_ACCOUNTS } from "../../packages/banking/src/demo-accounts";

test.describe.configure({ mode: "serial" });
async function login(page: Page, role: "customer" | "reviewer") {
  await page.goto(role === "customer" ? "/" : "http://127.0.0.1:3001");
  await page.getByRole("button", { name: `Use ${role === "customer" ? "customer" : "bank agent"} demo account` }).click();
  await expect(page.getByLabel("Email address", { exact: true })).toHaveValue(DEMO_ACCOUNTS[role].email);
  await page.getByRole("button", { name: `Sign in as ${role === "customer" ? "customer" : "bank agent"}` }).click();
  await expect(page.getByRole("complementary", { name: role === "customer" ? "Primary navigation" : "Bank agent navigation", exact: true })).toBeVisible();
}
async function addDocument(page: Page, card: Locator, kind: string) {
  await card.getByRole("button", { name: "Add file" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Synthetic document file").setInputFiles({ name: `synthetic-${kind}.pdf`, mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nSYNTHETIC DEMO ONLY\n%%EOF") });
  await dialog.getByRole("checkbox", { name: /I confirm this is a synthetic document/ }).check();
  await dialog.getByRole("button", { name: "Save document metadata" }).click();
  await expect(dialog).not.toBeVisible();
}
async function submitApplication(page: Page, card: Locator) {
  await card.getByRole("button", { name: "Review & submit" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Confirm submission" })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: "Confirm demo application submission" }).check();
  await dialog.getByRole("button", { name: "Confirm submission" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(card.getByText("In human review", { exact: true }).first()).toBeVisible();
}

test("separate customer and bank-agent sign-in, validation, session restoration and logout", async ({ page }, testInfo) => {
  await page.goto("/applications");
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await expect(page.getByRole("link", { name: "Customer", exact: true })).toHaveAttribute("aria-current", "page");
  const submit = page.getByRole("button", { name: "Sign in as customer" });
  await expect(submit).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("customer-sign-in.png"), fullPage: true });
  await page.getByLabel("Email address", { exact: true }).fill(DEMO_ACCOUNTS.customer.email);
  await page.getByLabel("Password", { exact: true }).fill("incorrect-password");
  await submit.click();
  await expect(page.getByRole("alert", { name: "Sign-in error" })).toContainText("does not match this demo workspace");
  await expect(page.getByRole("heading", { name: "Your applications." })).not.toBeVisible();
  await page.getByRole("button", { name: "Use customer demo account" }).click();
  await expect(page.getByRole("alert", { name: "Sign-in error" })).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await page.getByRole("button", { name: "Show password" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Hide password" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "password");
  await submit.click();
  await expect(page.getByRole("heading", { name: "Your applications." })).toBeVisible();
  const customerSession = await page.evaluate(() => JSON.parse(sessionStorage.getItem("luma-demo-session-v2-customer")!));
  expect(customerSession.actor.role).toBe("customer");
  expect(JSON.stringify(customerSession)).not.toContain(DEMO_ACCOUNTS.customer.password);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your applications." })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await expect(submit).toBeDisabled();
  const revoked = await page.request.get("http://127.0.0.1:4010/api/snapshot", { headers: { Authorization: `Bearer ${customerSession.token}` } });
  expect(revoked.status()).toBe(401);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await page.getByRole("link", { name: "Bank agent", exact: true }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  await expect(page.getByRole("heading", { name: "Sign in to review." })).toBeVisible();
  await page.getByLabel("Email address", { exact: true }).fill(DEMO_ACCOUNTS.customer.email);
  await page.getByLabel("Password", { exact: true }).fill(DEMO_ACCOUNTS.customer.password);
  await page.getByRole("button", { name: "Sign in as bank agent" }).click();
  await expect(page.getByRole("alert", { name: "Sign-in error" })).toContainText("does not match this demo workspace");
  await page.getByRole("button", { name: "Use bank agent demo account" }).click();
  await page.screenshot({ path: testInfo.outputPath("bank-agent-sign-in.png"), fullPage: true });
  await page.getByRole("button", { name: "Sign in as bank agent" }).click();
  await expect(page.getByRole("heading", { name: "Your application queue." })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your application queue." })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in to review." })).toBeVisible();
});

test("invalid or revoked browser sessions return to sign-in instead of exposing a workspace", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => sessionStorage.setItem("luma-demo-session-v2-customer", '{"token":"forged"}'));
  await page.reload();
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await login(page, "customer");
  const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem("luma-demo-session-v2-customer")!).token as string);
  const response = await page.request.post("http://127.0.0.1:4010/api/session/logout", { headers: { Authorization: `Bearer ${token}` }, data: {} });
  expect(response.ok()).toBe(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await expect(page.getByRole("alert", { name: "Sign-in error" })).toContainText("Your demo session has ended");
  expect(await page.evaluate(() => sessionStorage.getItem("luma-demo-session-v2-customer"))).toBeNull();
});

test("desktop guided assistant, free text, loan changes and existing information", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, "customer");
  await expect(page.getByRole("heading", { name: /Hey Alex/ })).toBeVisible();
  await expect(page.getByLabel("Message the assistant")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("assistant-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: /^I want a loan/ }).click();
  await expect(page.getByRole("button", { name: /^Personal loan/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Mortgage/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Car loan/ })).toBeVisible();
  await page.getByRole("button", { name: /^Mortgage/ }).click();
  await expect(page.getByRole("heading", { name: "Mortgage simulator" })).toBeVisible();
  await page.getByLabel("Message the assistant").fill("I want a personal loan of 40,000 RON for 3 years");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("heading", { name: "Personal loan simulator" })).toBeVisible();
  await expect(page.getByLabel("How much do you need? · RON").last()).toHaveValue("40000");
  await expect(page.getByLabel("Repayment period · months").last()).toHaveValue("36");
  await page.getByRole("button", { name: "Back to options" }).click();
  await page.getByRole("button", { name: /^Change my current loan/ }).last().click();
  await expect(page.getByRole("button", { name: /^Early repayment/ })).toBeVisible();
  await page.getByRole("button", { name: /^Early repayment/ }).click();
  await expect(page.getByRole("heading", { name: "Early repayment simulator" })).toBeVisible();
  await page.getByRole("button", { name: "Back to options" }).click();
  await page.getByRole("button", { name: /^My current loan details/ }).last().click();
  await expect(page.getByText("Outstanding principal").first()).toBeVisible();
  await page.getByLabel("Message the assistant").fill("Can you compare refinancing?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("heading", { name: "Refinancing comparison" })).toBeVisible();
  await expect(page.getByText(/Lower installments do not automatically/)).toBeVisible();
  await page.getByRole("button", { name: "End chat", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "End chat & start fresh" }).click();
  await expect(page.getByRole("heading", { name: /Hey Alex/ })).toBeVisible();
  expect(errors).toEqual([]);
});


test("customer submission, reviewer information request, resumed application and final human outcome", async ({ page, context }, testInfo) => {
  await login(page, "customer");
  await page.getByRole("button", { name: /^I want a loan/ }).click();
  await page.getByRole("button", { name: /^Personal loan/ }).click();
  await page.getByRole("button", { name: "Choose scenario & prepare application" }).click();
  await expect(page.getByText("LM-1002 · Personal loan", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Applications", exact: true }).click();
  const card = page.getByTestId("application-LM-1002");
  await addDocument(page, card, "identity");
  await addDocument(page, card, "income");
  await submitApplication(page, card);
  const reviewer = await context.newPage();
  await login(reviewer, "reviewer");
  await reviewer.getByRole("link", { name: "LM-1002", exact: true }).click();
  await expect(reviewer.getByRole("button", { name: "Approve demo application" })).toBeDisabled();
  await reviewer.getByRole("tab", { name: "Documents & evidence" }).click();
  await reviewer.getByRole("button", { name: "Inspect metadata" }).first().click();
  await expect(reviewer.getByRole("dialog").getByText(/NOT EXTRACTED/)).toBeVisible();
  await reviewer.keyboard.press("Escape");
  await reviewer.getByRole("checkbox", { name: "I inspected the underlying evidence" }).check();
  await reviewer.getByRole("button", { name: "Request more information", exact: true }).click();
  let dialog = reviewer.getByRole("dialog");
  await dialog.getByLabel("What clarification is needed, and why?").fill("Please add a fabricated account statement to clarify the synthetic obligations.");
  await dialog.getByRole("checkbox", { name: "Confirm independent evidence review" }).check();
  await dialog.getByRole("button", { name: "Record demo information request" }).click();
  await expect(dialog).not.toBeVisible();
  await page.reload();
  await expect(card.getByText("Information requested", { exact: true }).first()).toBeVisible();
  await addDocument(page, card, "statement");
  await submitApplication(page, card);
  await reviewer.reload();
  await reviewer.getByRole("tab", { name: "Documents & evidence" }).click();
  await reviewer.getByRole("checkbox", { name: "I inspected the underlying evidence" }).check();
  await reviewer.getByRole("button", { name: "Approve demo application", exact: true }).click();
  dialog = reviewer.getByRole("dialog");
  await dialog.getByLabel("Decision justification").fill("Independent inspection of the fabricated profile and document metadata completed for this demo only.");
  await dialog.getByRole("checkbox", { name: "Confirm independent evidence review" }).check();
  await dialog.getByRole("button", { name: "Record demo decision" }).click();
  await expect(dialog).not.toBeVisible();
  await page.reload();
  await expect(card.getByText("Approved · demo", { exact: true }).first()).toBeVisible();
  await expect(card.getByText(/nothing has been signed or funded/)).toBeVisible();
  await reviewer.screenshot({ path: testInfo.outputPath("reviewer-desktop.png"), fullPage: true });
  await reviewer.getByRole("link", { name: "Audit history", exact: true }).click();
  await expect(reviewer.getByText("REVIEW APPROVE", { exact: true })).toBeVisible();
  await reviewer.close();
});

test("desktop routes, consent preferences, keyboard dialogs and no horizontal page overflow", async ({ page }) => {
  await login(page, "customer");
  for (const route of ["/dashboard", "/products", "/loans", "/applications", "/settings"]) {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  const consent = page.getByRole("switch", { name: "Financial insight estimates" });
  await consent.click();
  await expect(consent).toBeChecked();
  await page.reload();
  await expect(consent).toBeChecked();
  await page.goto("/loans");
  await page.getByRole("button", { name: "View indicative repayment schedule" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Tab");
  expect(await page.getByRole("dialog").evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.getByLabel("Message the assistant")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("bank agent searches assigned cases, writes private notes and records a justified rejection", async ({ page, context }) => {
  await login(page, "reviewer");
  await page.getByLabel("Search application queue").fill("LM-1001");
  await expect(page.getByRole("link", { name: "LM-1001", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "LM-1002", exact: true })).not.toBeVisible();
  await page.getByLabel("Filter application status").selectOption("PENDING_HUMAN_REVIEW");
  await page.getByRole("link", { name: "LM-1001", exact: true }).click();
  await expect(page.getByRole("button", { name: "Reject demo application", exact: true })).toBeDisabled();
  await page.getByLabel("Add an internal observation").fill("Private review note: the fabricated evidence is insufficient for this demo decision.");
  await page.getByRole("button", { name: "Save internal note" }).click();
  await expect(page.getByText("Private review note:", { exact: false })).toBeVisible();
  const customer = await context.newPage();
  await login(customer, "customer");
  await customer.goto("/applications");
  await expect(customer.getByText("Private review note:", { exact: false })).not.toBeVisible();
  await page.getByRole("tab", { name: "Documents & evidence" }).click();
  await page.getByRole("button", { name: "Inspect metadata" }).first().click();
  await page.keyboard.press("Escape");
  await page.getByRole("checkbox", { name: "I inspected the underlying evidence" }).check();
  await page.getByRole("button", { name: "Reject demo application", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Record demo decision" })).toBeDisabled();
  await dialog.getByLabel("Decision justification").fill("The synthetic evidence does not support the requested scenario after independent inspection. Demo rejection only.");
  await dialog.getByRole("checkbox", { name: "Confirm independent evidence review" }).check();
  await dialog.getByRole("button", { name: "Record demo decision" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText("Rejected · demo", { exact: true })).toBeVisible();
  await customer.reload();
  const application = customer.getByTestId("application-LM-1001");
  await expect(application.getByText("Rejected · demo", { exact: true }).first()).toBeVisible();
  await expect(application.getByText("The synthetic evidence does not support", { exact: false }).first()).toBeVisible();
  await page.getByRole("link", { name: "Audit history", exact: true }).click();
  await expect(page.getByText("REVIEW REJECT", { exact: true })).toBeVisible();
  await customer.close();
});

test("sign-in is usable on mobile and preserves the yellow/black theme", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const url of ["http://127.0.0.1:3000", "http://127.0.0.1:3001"]) {
    await page.goto(url);
    await expect(page.getByLabel("Email address", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await page.locator('section[aria-label="About the prototype"]').evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgb(255, 237, 0)");
  }
});
