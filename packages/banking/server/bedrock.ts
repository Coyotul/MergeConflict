import type { ChatMessage, DemoStore } from "../src/types";
import { interpretMessage } from "../src/conversation";

export function isBedrockConfigured(): boolean {
  return Boolean(process.env.BEDROCK_API_KEY);
}

function buildSystemPrompt(state: DemoStore, customerId: string): string {
  const customer = state.customers.find((c) => c.id === customerId);
  const loans = state.loans.filter((l) => l.customerId === customerId);
  const products = state.products;

  const customerDesc = customer
    ? `Customer Profile: ${customer.name}, Employer: ${customer.employer}, Monthly Income: ${customer.monthlyIncome} RON, Monthly Expenses: ${customer.monthlyExpenses} RON, Account Balance: ${customer.balance} RON.`
    : "";

  const loansDesc = loans.length > 0
    ? `Existing Loans: ${loans.map((l) => `${l.name} (ID: ${l.id}, Principal Balance: ${l.principal} RON, Annual Rate: ${l.annualRate}%, Remaining: ${l.remainingMonths} months, Next payment: ${l.nextPaymentDate})`).join("; ")}`
    : "Existing Loans: None.";

  const productsDesc = products
    .map((p) => `- Product ID "${p.id}" (${p.name}): ${p.description}. Amount: ${p.minAmount} - ${p.maxAmount} RON, Duration: ${p.minMonths} - ${p.maxMonths} months, Interest rate: ${p.annualRate}%/year, Fee: ${p.fee} RON, Monthly Insurance: ${p.monthlyInsurance} RON. Policy ID: ${p.policyId}`)
    .join("\n");

  return `You are Luma, an intelligent, empathetic and precise banking companion for Luma Bank.
Your goal is to guide the customer with banking questions, synthetic loan simulations, early repayments, refinancing, and required documents.

Important principles:
1. Language: ALWAYS respond in English. Even if the user writes in Romanian or another language, understand their request accurately but provide your entire response strictly in English.
2. Persona: Friendly, polite, transparent, concise and professional.
3. Accurate Financial Information: Use the provided products and customer financial profile below.

${customerDesc}
${loansDesc}

Available Credit Products:
${productsDesc}

Credit Policies:
- Maximum Debt-to-Income (DTI) ratio allowed is 40% (Grad de îndatorare maxim 40%).
- Required documents for new applications: Identity document (CI / Pașaport) and Proof of income (Adeverință de venit / Acord ANAF).
- Early repayment (Rambursare anticipată): Customer can pay partially to reduce monthly installment or reduce loan duration.
- Refinancing (Refinanțare): Customer can consolidate existing debts or refinance to adjust rates or terms.
- Decision policy: This is a synthetic guided demo; credit agreements require final human reviewer verification.

Output format:
Respond ONLY with a valid JSON object matching this structure:
{
  "text": "Your helpful response message to the user in English.",
  "kind": "text" | "options" | "products" | "modify" | "loan-details" | "loan" | "repayment" | "refinance" | "documents" | "applications" | "support" | "contract",
  "productId": "personal" | "mortgage" | "car" | null,
  "amount": "20000" | null,
  "months": 36 | null,
  "sources": ["personal-policy"] | []
}

Instructions for "kind":
- "loan": When the user expresses interest in calculating, simulating, or taking out a specific loan (personal, mortgage, car). ALWAYS set productId to "personal", "mortgage", or "car". If user mentioned amount (e.g. 20000, 35k, 35.000, or 50000 lei) and/or term (e.g. 3 ani or 36 luni), set "amount" as a string number of pure digits (e.g. "35000", convert "35k" to "35000") and "months" as an integer (convert years to months).
- "products": When the user asks generally what loans or products are offered without picking one yet.
- "repayment": When the user asks about early repayment (rambursare anticipata) or paying down a loan.
- "refinance": When the user asks about refinancing (refinantare) or lowering payments.
- "loan-details": When the user asks about their current loan balance, monthly payment, or due date.
- "documents": When the user asks about required documents, checklist, or what papers to upload.
- "applications": When the user asks about their application status or history.
- "support": When the user requests human assistance, a consultant, or states they cannot pay.
- "options": When the user wants the main menu or starting points.
- "contract": When the user asks about contract clauses, legal terms, or agreement text.
- "text": For general greetings, questions (e.g., "Ce este DAE?", "Ce dobanda aveti?", general financial advice), explanations, or clarification.

Do NOT output any markdown tags (like \`\`\`json) if possible, just output the JSON object directly.`;
}

interface BedrockParsedResponse {
  text: string;
  kind: ChatMessage["kind"];
  productId?: string | null;
  amount?: string | null;
  months?: number | null;
  sources?: string[];
}

function parseBedrockJson(raw: string): BedrockParsedResponse | null {
  try {
    let cleaned = raw.trim();
    if (cleaned.startsWith("```")) {
      cleaned = cleaned.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
    }
    const jsonMatch = cleaned.match(/\{[\s\S]*\}/);
    if (!jsonMatch) return null;
    const parsed = JSON.parse(jsonMatch[0]);
    if (typeof parsed.text !== "string") return null;
    return parsed as BedrockParsedResponse;
  } catch {
    return null;
  }
}

function normalizeAmount(raw?: string | number | null): string | undefined {
  if (!raw) return undefined;
  const str = String(raw).trim().toLowerCase();
  const kMatch = str.match(/^(\d+(?:\.\d+)?)\s*k$/);
  if (kMatch) {
    return String(Math.round(Number(kMatch[1]) * 1000));
  }
  const clean = str.replace(/[ ,.]00$/, "").replace(/[ ,.]/g, "");
  return /^\d+$/.test(clean) ? clean : undefined;
}

export async function interpretWithBedrock(
  text: string,
  state: DemoStore,
  customerId: string
): Promise<Omit<ChatMessage, "id" | "at" | "role">> {
  const apiKey = process.env.BEDROCK_API_KEY;
  if (!apiKey) {
    return interpretMessage(text, state, customerId);
  }

  const region = process.env.BEDROCK_REGION || "us-east-1";
  const modelId = process.env.BEDROCK_MODEL_ID || "amazon.nova-lite-v1:0";

  try {
    const systemPrompt = buildSystemPrompt(state, customerId);

    // Collect previous messages for context (up to last 8 messages)
    const history = (state.messages[customerId] ?? []).slice(-8);
    const messages = history.map((m) => ({
      role: m.role === "assistant" ? "assistant" : "user",
      content: [{ text: m.text }],
    }));

    // Ensure alternating user/assistant roles required by Bedrock
    const sanitizedMessages: Array<{ role: "user" | "assistant"; content: [{ text: string }] }> = [];
    for (const msg of messages) {
      if (sanitizedMessages.length > 0 && sanitizedMessages[sanitizedMessages.length - 1].role === msg.role) {
        sanitizedMessages[sanitizedMessages.length - 1].content[0].text += `\n${msg.content[0].text}`;
      } else {
        sanitizedMessages.push(msg as { role: "user" | "assistant"; content: [{ text: string }] });
      }
    }

    if (sanitizedMessages.length > 0 && sanitizedMessages[sanitizedMessages.length - 1].role === "user") {
      sanitizedMessages[sanitizedMessages.length - 1].content[0].text += `\n${text}`;
    } else {
      sanitizedMessages.push({ role: "user", content: [{ text }] });
    }

    const endpoint = `https://bedrock-runtime.${region}.amazonaws.com/model/${encodeURIComponent(modelId)}/converse`;

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        system: [{ text: systemPrompt }],
        messages: sanitizedMessages,
        inferenceConfig: {
          maxTokens: 700,
          temperature: 0.2,
        },
      }),
      signal: AbortSignal.timeout(9000),
    });

    if (!response.ok) {
      const errBody = await response.text();
      console.warn(`[Bedrock] API error ${response.status}: ${errBody}`);
      return interpretMessage(text, state, customerId);
    }

    const data = await response.json();
    const rawOutput = data.output?.message?.content?.[0]?.text;
    if (!rawOutput) {
      return interpretMessage(text, state, customerId);
    }

    const parsed = parseBedrockJson(rawOutput);
    if (!parsed) {
      // If output is plain text, display it as a text message
      return {
        kind: "text",
        text: rawOutput,
      };
    }

    const validKinds: ChatMessage["kind"][] = [
      "text",
      "options",
      "products",
      "modify",
      "loan-details",
      "loan",
      "repayment",
      "refinance",
      "documents",
      "applications",
      "support",
      "contract",
    ];

    const kind: ChatMessage["kind"] = validKinds.includes(parsed.kind) ? parsed.kind : "text";

    const validProducts = ["personal", "mortgage", "car"];
    const productId = parsed.productId && validProducts.includes(parsed.productId)
      ? parsed.productId
      : undefined;

    let sources = Array.isArray(parsed.sources) ? parsed.sources : undefined;
    if (kind === "loan" && productId) {
      const prod = state.products.find((p) => p.id === productId);
      if (prod && !sources?.includes(prod.policyId)) {
        sources = [prod.policyId];
      }
    } else if (kind === "repayment" || kind === "refinance" || kind === "contract") {
      sources ??= ["repayment-policy"];
    } else if (kind === "documents") {
      sources ??= ["personal-policy"];
    }

    let params: ChatMessage["params"] | undefined;
    if (kind === "loan" && productId) {
      params = {
        productId,
        amount: normalizeAmount(parsed.amount),
        months: typeof parsed.months === "number" ? parsed.months : undefined,
      };
    }

    return {
      kind,
      text: parsed.text,
      sources,
      params,
    };
  } catch (error) {
    console.warn("[Bedrock] Fallback to rule engine:", error instanceof Error ? error.message : error);
    return interpretMessage(text, state, customerId);
  }
}
