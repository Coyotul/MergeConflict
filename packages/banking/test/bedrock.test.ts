import test from "node:test";
import assert from "node:assert/strict";
import { seedStore } from "../src/seed";
import { interpretWithBedrock } from "../server/bedrock";

test("interpretWithBedrock falls back to rule-based engine when API key is unset", async () => {
  const originalKey = process.env.BEDROCK_API_KEY;
  try {
    delete process.env.BEDROCK_API_KEY;
    const store = seedStore();
    const result = await interpretWithBedrock("I want a mortgage loan", store, store.customers[0].id);
    assert.equal(result.kind, "loan");
    assert.equal(result.params?.productId, "mortgage");
  } finally {
    if (originalKey) process.env.BEDROCK_API_KEY = originalKey;
  }
});

test("interpretWithBedrock invokes Bedrock when configured or falls back gracefully", async () => {
  const store = seedStore();
  const customerId = store.customers[0].id;

  const result = await interpretWithBedrock("Salut! Ce servicii imi poti oferi?", store, customerId);
  assert.ok(result.text.length > 0);
  assert.ok(typeof result.kind === "string");
});
