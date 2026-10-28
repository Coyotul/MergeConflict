import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  STEP_LABELS,
  stepLabel,
  stepStatusText,
  documentStatusLabel,
  humaniseStatus,
  chooseOfferLabel,
  confirmFieldLabel,
  confirmFieldMessage,
  documentValueLabel,
  documentValueMessage,
} from "../src/orchestrator-labels.js";

const examplesDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../contracts/http/examples/chat"
);

function collectStages(value: unknown, stages: Set<string>): void {
  if (Array.isArray(value)) {
    value.forEach((item) => collectStages(item, stages));
    return;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const progress = record.progress as { steps?: Array<{ stage: string }> } | undefined;
    if (progress && Array.isArray(progress.steps)) {
      progress.steps.forEach((step) => stages.add(step.stage));
    }
    Object.values(record).forEach((child) => collectStages(child, stages));
  }
}

describe("STEP_LABELS", () => {
  it("has a label for every progress stage in the contract examples", () => {
    const stages = new Set<string>();
    for (const file of readdirSync(examplesDir).filter((f) => f.endsWith(".json"))) {
      collectStages(JSON.parse(readFileSync(join(examplesDir, file), "utf8")), stages);
    }
    assert.ok(stages.size >= 7, `expected the 7 contract stages, found ${[...stages].join(",")}`);
    for (const stage of stages) {
      assert.ok(STEP_LABELS[stage], `missing label for stage ${stage}`);
    }
  });

  it("uses the customer-facing labels", () => {
    assert.deepEqual(
      [
        "discovery",
        "collecting_information",
        "eligibility",
        "documents",
        "offer_selection",
        "awaiting_confirmation",
        "submitted",
      ].map(stepLabel),
      ["Discovery", "Your details", "Eligibility", "Documents", "Offers", "Confirm", "Submitted"]
    );
  });

  it("humanises unknown stages instead of showing snake_case", () => {
    assert.equal(stepLabel("future_stage"), "Future stage");
  });

  it("gives screen-reader text for each step status", () => {
    assert.equal(stepStatusText("done"), "completed");
    assert.equal(stepStatusText("current"), "current step");
    assert.equal(stepStatusText("todo"), "not started");
  });
});

describe("status labels", () => {
  it("shows document statuses human-readably", () => {
    assert.equal(documentStatusLabel("accepted"), "Accepted");
    assert.equal(documentStatusLabel("rejected"), "Rejected");
    assert.equal(documentStatusLabel("requested"), "Requested");
    assert.equal(documentStatusLabel("processing"), "Processing");
    assert.equal(documentStatusLabel("uploaded"), "Uploaded");
  });

  it("humanises application statuses neutrally, never inventing a decision", () => {
    assert.equal(humaniseStatus("PENDING_HUMAN_REVIEW"), "Pending human review");
    assert.equal(humaniseStatus("SOME_NEW_STATUS"), "Some new status");
  });
});

describe("action labels", () => {
  it("names the offer Choose button uniquely with its visible text", () => {
    assert.equal(
      chooseOfferLabel(60, "630.06 RON"),
      "Choose 60-month offer (630.06 RON/month)"
    );
  });

  it("includes the field label in confirm buttons and messages", () => {
    assert.equal(confirmFieldLabel("Net income"), "Confirm Net income");
    assert.equal(confirmFieldMessage("Net income"), "Yes, Net income is correct");
    assert.equal(documentValueLabel("Net income"), "Use document value for Net income");
    assert.equal(
      documentValueMessage("Net income"),
      "Yes, use the document value for Net income"
    );
  });
});
