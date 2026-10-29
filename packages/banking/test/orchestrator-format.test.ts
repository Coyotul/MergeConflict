import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { formatMoneyString } from "../src/orchestrator-format.js";

describe("formatMoneyString", () => {
  it("formats integer amounts", () => {
    assert.equal(formatMoneyString("1234", "RON"), "1,234 RON");
    assert.equal(formatMoneyString("1000000", "RON"), "1,000,000 RON");
  });

  it("formats decimal amounts", () => {
    assert.equal(formatMoneyString("15000.50", "RON"), "15,000.50 RON");
    assert.equal(formatMoneyString("1234.99", "RON"), "1,234.99 RON");
  });

  it("preserves exact decimal places", () => {
    assert.equal(formatMoneyString("100.5", "RON"), "100.5 RON");
    assert.equal(formatMoneyString("100.500", "RON"), "100.500 RON");
  });

  it("handles small amounts", () => {
    assert.equal(formatMoneyString("0", "RON"), "0 RON");
    assert.equal(formatMoneyString("1", "RON"), "1 RON");
    assert.equal(formatMoneyString("0.50", "RON"), "0.50 RON");
  });
});
