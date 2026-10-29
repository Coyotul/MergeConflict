import { test, expect, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { DEMO_ACCOUNTS } from "../../packages/banking/src/demo-accounts";
import { CUSTOMER_ACTOR } from "../../packages/banking/src/seed";

const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_E2E_URL ?? "http://127.0.0.1:8000";

test.describe.configure({ mode: "serial" });
async function login(page: Page, role: "customer" | "reviewer") {
  await page.goto(role === "customer" ? "/" : "http://127.0.0.1:3001");
  await page.getByRole("button", { name: `Use ${role === "customer" ? "customer" : "bank agent"} demo account` }).click();
  await expect(page.getByLabel("Email address", { exact: true })).toHaveValue(DEMO_ACCOUNTS[role].email);
  await page.getByRole("button", { name: `Sign in as ${role === "customer" ? "customer" : "bank agent"}` }).click();
  await expect(page.getByRole("complementary", { name: role === "customer" ? "Primary navigation" : "Bank agent navigation", exact: true })).toBeVisible();
}
// Next dev compiles a route on its first visit and can force a full page reload ("Fast Refresh had
// to perform a full reload") that drops an in-flight client navigation; retry until the URL changes.
async function follow(page: Page, link: Locator, url: RegExp) {
  await expect(async () => {
    if (!url.test(page.url())) await link.click({ timeout: 5000 });
    await expect(page).toHaveURL(url, { timeout: 10000 });
  }).toPass({ timeout: 60000 });
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

test("assistant runs on the orchestrator", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, "customer");
  await expect(page.getByRole("heading", { name: /Hey Alex/ })).toBeVisible();
  // The chat picks a random synthetic customer per conversation, and the mock (demo) model's
  // outcomes differ per customer. Pin cust-001 deterministically: create its session through the
  // orchestrator API and store it under the hook's sessionStorage key, so the reload resumes it.
  const created = await page.request.post(`${ORCHESTRATOR_URL}/chat/sessions`, { headers: { "X-Customer-Id": "cust-001" }, data: {} });
  expect(created.status()).toBe(201);
  const { session_id: sessionId } = (await created.json()) as { session_id: string };
  await page.evaluate(([key, value]) => sessionStorage.setItem(key, value), [`luma-orchestrator-chat-v1-${CUSTOMER_ACTOR.id}`, JSON.stringify({ sessionId, customerId: "cust-001" })]);
  await page.reload();
  await expect(page.getByRole("heading", { name: /Hey Alex/ })).toBeVisible();
  await expect(page.getByLabel("Message the assistant")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("assistant-desktop.png"), fullPage: true });
  const assistantBubbles = page.getByText("LUMA · AI ASSISTANT", { exact: true });
  let replies = 1; // the greeting, kept behind the welcome screen until the first message
  const say = async (text: string) => {
    await page.getByLabel("Message the assistant").fill(text);
    await page.getByRole("button", { name: "Send message" }).click();
    replies += 1;
    await expect(assistantBubbles).toHaveCount(replies);
    await expect(page.getByLabel("Message the assistant")).toHaveValue("");
  };
  await say("Vreau un credit de 30000 lei pe 60 de luni pentru renovare");
  await expect(page.getByRole("heading", { name: /Hey Alex/ })).not.toBeVisible();
  await expect(page.getByRole("region", { name: "Application progress" })).toBeVisible();
  // The demo model collects one field per turn: same answers as the cust-001 happy path in
  // tests/e2e/test_chat_scenarios.py, then "ok" runs the preliminary check and requests documents.
  for (const text of ["pentru renovare", "30000 lei", "60 luni", "employed", "48", "7000", "TechCorp SRL", "400", "ok"]) await say(text);
  const uploadId = page.getByRole("button", { name: "Upload ID Card" });
  await expect(uploadId).toBeVisible();
  await expect(page.getByRole("button", { name: /^Upload Payslip/ })).toBeVisible();
  const chooser = page.waitForEvent("filechooser");
  await uploadId.click();
  const identityPdf = execFileSync(process.env.ORCHESTRATOR_PYTHON ?? "python", ["-c", "from tests.fixtures.documents import document_bytes; import sys; sys.stdout.buffer.write(document_bytes('id_card'))"]);
  await (await chooser).setFiles({ name: "synthetic-id-card.pdf", mimeType: "application/pdf", buffer: identityPdf });
  replies += 1;
  await expect(assistantBubbles).toHaveCount(replies);
  await expect(uploadId).not.toBeVisible();
  await expect(page.getByText("Accepted", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Synthetic data · simulated, based on public conditions")).toBeVisible();
  await page.getByRole("button", { name: "End chat", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "End chat & start fresh" }).click();
  await expect(page.getByRole("heading", { name: /Hey Alex/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test("orchestrator pricing disclosures survive offer selection and explicit confirmation", async ({ page }) => {
  await login(page, "customer");
  const headers = { "X-Customer-Id": "cust-001" };
  const created = await page.request.post(`${ORCHESTRATOR_URL}/chat/sessions`, { headers, data: {} });
  expect(created.status()).toBe(201);
  const { session_id: sessionId } = await created.json() as { session_id: string };
  const base = `${ORCHESTRATOR_URL}/chat/sessions/${sessionId}`;
  // Reach verified pricing via the real offline API/model; no seeded offer numbers.
  for (const text of ["Vreau un credit", "pentru renovare", "30000 lei", "60 luni", "employed", "48", "7000", "TechCorp SRL", "400"]) {
    const response = await page.request.post(`${base}/messages`, { headers, data: { text } });
    expect(response.status()).toBe(200);
  }
  for (const docType of ["id_card", "payslip", "bank_statement"]) {
    const response = await page.request.post(`${base}/documents`, {
      headers,
      multipart: { doc_type: docType, file: { name: `${docType}.pdf`, mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 synthetic") } },
    });
    expect(response.status()).toBe(200);
  }
  const calculated = await page.request.post(`${base}/messages`, { headers, data: { text: "da" } });
  expect(calculated.status()).toBe(200);
  expect((await calculated.json()).awaiting.kind).toBe("offer_choice");
  await page.evaluate(([key, value]) => sessionStorage.setItem(key, value), [`luma-orchestrator-chat-v1-${CUSTOMER_ACTOR.id}`, JSON.stringify({ sessionId, customerId: "cust-001" })]);
  await page.reload();

  const choose = page.getByRole("button", { name: "Choose 60-month offer (621.22 RON/month)", exact: true });
  await expect(choose).toBeVisible();
  // Verify the actual offer details, not just the assistant's narrative.
  const detailsToggle = page.getByRole("button", { name: "Show assumptions", exact: true }).first();
  const detailsId = await detailsToggle.getAttribute("aria-controls");
  expect(detailsId).toBeTruthy();
  await detailsToggle.click();
  const details = page.locator(`[id="${detailsId}"]`);
  await expect(details).toContainText("DAE/APR: 9.58%");
  await expect(details).toContainText("Net amount paid out: 29800.00 RON");
  await expect(details).toContainText("ANALYSIS_FEE: 200.00 RON");
  await expect(details).toContainText("not an offer, an approval or an authoritative settlement amount");
  await choose.click();
  const confirm = page.getByRole("button", { name: "Confirm & submit for human review", exact: true });
  await expect(confirm).toBeVisible();
  const selected = await page.request.get(base, { headers });
  expect((await selected.json()).latest.awaiting.kind).toBe("confirmation");
  await expect(page.getByText("Submitted for human review — no decision yet.", { exact: false })).not.toBeVisible();
  await confirm.click();
  await expect(page.getByText("Submitted for human review — no decision yet.", { exact: false })).toBeVisible();
  const submitted = await page.request.get(base, { headers });
  const latest = (await submitted.json()).latest;
  expect(latest.progress.stage).toBe("submitted");
  expect(latest.simulated).toBe(true);
});

test("assistant shows a retryable alert while the orchestrator is down", async ({ page }) => {
  await page.route(`${ORCHESTRATOR_URL}/**`, (route) => route.abort());
  await login(page, "customer");
  await expect(page.getByRole("heading", { name: /Hey Alex/ })).toBeVisible();
  const alert = page.getByRole("alert").filter({ hasText: "not reachable" });
  await expect(alert).toContainText("The AI assistant service is not reachable (or blocked by CORS)");
  const retry = alert.getByRole("button", { name: "Retry" });
  await expect(retry).toBeVisible();
  await page.unroute(`${ORCHESTRATOR_URL}/**`);
  await retry.click();
  await expect(alert).not.toBeVisible();
  await expect(page.getByRole("heading", { name: /Hey Alex/ })).toBeVisible();
  // The session now exists: a message goes through and the assistant replies.
  await page.getByLabel("Message the assistant").fill("Vreau un credit de 30000 lei pe 60 de luni pentru renovare");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByLabel("Message the assistant")).toHaveValue("");
  await expect(page.getByText("LUMA · AI ASSISTANT", { exact: true })).toHaveCount(2);
});


test("customer submission, reviewer information request, resumed application and final human outcome", async ({ page, context }, testInfo) => {
  // Several routes (/products, staff /applications/[id], /audit) are compiled on first visit by the dev servers.
  test.slow();
  await login(page, "customer");
  // The chat now runs on the orchestrator, so the demo application starts from the Products page.
  // A full navigation (not the sidebar link) waits for the dev server's first compile of /products.
  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "Big plans. Clear numbers." })).toBeVisible();
  await page.getByRole("button", { name: "Choose scenario & prepare application" }).click();
  await expect(page.getByText("LM-1002 · Personal loan", { exact: true })).toBeVisible();
  await follow(page, page.getByRole("link", { name: "Applications", exact: true }), /\/applications$/);
  const card = page.getByTestId("application-LM-1002");
  await addDocument(page, card, "identity");
  await addDocument(page, card, "income");
  await submitApplication(page, card);
  const reviewer = await context.newPage();
  await login(reviewer, "reviewer");
  await follow(reviewer, reviewer.getByRole("link", { name: "LM-1002", exact: true }), /\/applications\/./);
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
  await follow(reviewer, reviewer.getByRole("link", { name: "Audit history", exact: true }), /\/audit$/);
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
