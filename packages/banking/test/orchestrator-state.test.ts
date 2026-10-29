import { describe, it } from "node:test";
import { strict as assert } from "node:assert";
import {
  initialChatState,
  chatReducer,
  canSend,
  canConfirm,
  hasCustomerMessages,
  storageKey,
  shouldStartFresh,
  isValidCustomerId,
  getRetryAction,
  retryNotice,
  lastAssistantEntryIndex,
  type ChatState,
  type ChatEntry,
} from "../src/orchestrator-state";
import type {
  TurnResponse,
  SessionView,
  ApplicationSummary,
  OrchestratorError,
} from "../src/orchestrator";

describe("orchestrator-state", () => {
  describe("chatReducer", () => {
    it("requested message appends customer entry and sets pending", () => {
      const state = {
        ...initialChatState,
        sessionId: "sess-123",
        customerId: "cust-001",
      };
      const customerEntry: ChatEntry = {
        id: "entry-1",
        role: "customer",
        text: "Hello",
        citations: [],
      };
      const next = chatReducer(state, {
        type: "requested",
        action: { kind: "message", text: "Hello" },
        localEntry: customerEntry,
      });

      assert.equal(next.pending, true);
      assert.deepEqual(next.lastAction, { kind: "message", text: "Hello" });
      assert.equal(next.entries.length, 1);
      assert.deepEqual(next.entries[0], customerEntry);
    });

    it("succeeded appends assistant messages and replaces latest", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        customerId: "cust-001",
        pending: true,
        entries: [
          { id: "entry-1", role: "customer", text: "Hello", citations: [] },
        ],
        lastAction: { kind: "message", text: "Hello" },
      };

      const response: TurnResponse = {
        session_id: "sess-123",
        turn_id: "turn-1",
        session_version: 1,
        messages: [
          {
            role: "assistant",
            text: "Hello! How can I help?",
            citations: [],
            created_at: "2026-10-28T10:00:00Z",
          },
        ],
        awaiting: { kind: "text" },
        progress: { flow: "none", stage: null, steps: [] },
        blocks: [],
        simulated: true,
      };

      const next = chatReducer(state, { type: "succeeded", response });

      assert.equal(next.pending, false);
      assert.equal(next.error, null);
      assert.deepEqual(next.latest, response);
      assert.equal(next.entries.length, 2);
      assert.equal(next.entries[1].role, "assistant");
      assert.equal(next.entries[1].text, "Hello! How can I help?");
    });

    it("reducer resumes from SessionView", () => {
      const view: SessionView = {
        session_id: "sess-123",
        created_at: "2026-10-28T09:00:00Z",
        messages: [
          {
            role: "assistant",
            text: "Hello!",
            citations: [],
            created_at: "2026-10-28T09:00:00Z",
          },
          {
            role: "customer",
            text: "Hi there",
            citations: [],
            created_at: "2026-10-28T09:01:00Z",
          },
        ],
        latest: {
          session_id: "sess-123",
          turn_id: "turn-2",
          session_version: 2,
          messages: [], // Contract: latest.messages is empty on GET
          awaiting: { kind: "text" },
          progress: { flow: "none", stage: null, steps: [] },
          blocks: [],
          simulated: true,
        },
      };

      const next = chatReducer(initialChatState, {
        type: "resumed",
        customerId: "cust-002",
        sessionId: "sess-123",
        view,
      });

      assert.equal(next.sessionId, "sess-123");
      assert.equal(next.customerId, "cust-002");
      assert.deepEqual(next.latest, view.latest);
      assert.equal(next.entries.length, 2); // Only from view.messages
    });

    it("succeeded ignores stale responses from different session", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        customerId: "cust-001",
        pending: true,
        entries: [
          { id: "entry-1", role: "customer", text: "Hello", citations: [] },
        ],
      };

      const staleResponse: TurnResponse = {
        session_id: "sess-old",
        turn_id: "turn-1",
        session_version: 1,
        messages: [
          {
            role: "assistant",
            text: "Stale response",
            citations: [],
            created_at: "2026-10-28T10:00:00Z",
          },
        ],
        awaiting: { kind: "text" },
        progress: { flow: "none", stage: null, steps: [] },
        blocks: [],
        simulated: true,
      };

      const next = chatReducer(state, { type: "succeeded", response: staleResponse });

      // Response ignored but pending cleared
      assert.equal(next.sessionId, "sess-123");
      assert.equal(next.entries.length, 1);
      assert.equal(next.pending, false); // Pending cleared
      assert.equal(next.latest, null);
    });
  });

  describe("canSend", () => {
    it("returns false while pending", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        pending: true,
      };
      assert.equal(canSend(state), false);
    });

    it("returns false when sessionId is null", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: null,
        pending: false,
      };
      assert.equal(canSend(state), false);
    });

    it("returns true when not pending and sessionId is set", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        pending: false,
      };
      assert.equal(canSend(state), true);
    });
  });

  describe("canConfirm", () => {
    it("requires matching summary_version and confirmation awaiting", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        latest: {
          session_id: "sess-123",
          turn_id: "turn-1",
          session_version: 1,
          messages: [],
          awaiting: { kind: "confirmation", summary_version: "v1" },
          progress: { flow: "none", stage: null, steps: [] },
          blocks: [],
          simulated: true,
        },
      };

      const summary: ApplicationSummary = {
        summary_version: "v1",
        application_id: "app-1",
        product_code: "personal_loan",
        product_name: "Personal Loan",
        amount: { amount: "10000.00", currency: "RON" },
        term_months: 24,
        offer: {
          offer_id: "offer-1",
          product_code: "personal_loan",
          amount: { amount: "10000.00", currency: "RON" },
          term_months: 24,
          annual_interest_rate_percent: "9.5",
          monthly_installment: { amount: "500.00", currency: "RON" },
          total_repayment: { amount: "12000.00", currency: "RON" },
          total_cost: { amount: "2000.00", currency: "RON" },
          fees: { amount: "0.00", currency: "RON" },
          assumptions: [],
        },
        fields: [],
        documents: [],
      };

      assert.equal(canConfirm(state, summary), true);

      // Wrong version
      const wrongVersionSummary = { ...summary, summary_version: "v2" };
      assert.equal(canConfirm(state, wrongVersionSummary), false);

      // Wrong awaiting kind
      const stateWrongAwaiting: ChatState = {
        ...state,
        latest: {
          ...state.latest!,
          awaiting: { kind: "text" },
        },
      };
      assert.equal(canConfirm(stateWrongAwaiting, summary), false);
    });
  });

  describe("hasCustomerMessages", () => {
    it("returns false when only the greeting exists", () => {
      const state: ChatState = {
        ...initialChatState,
        entries: [
          {
            id: "entry-greeting",
            role: "assistant",
            text: "Hello! Welcome!",
            citations: [],
          },
        ],
      };
      assert.equal(hasCustomerMessages(state), false);
    });

    it("returns true when customer has sent a message", () => {
      const state: ChatState = {
        ...initialChatState,
        entries: [
          {
            id: "entry-greeting",
            role: "assistant",
            text: "Hello!",
            citations: [],
          },
          {
            id: "entry-1",
            role: "customer",
            text: "Hi there",
            citations: [],
          },
        ],
      };
      assert.equal(hasCustomerMessages(state), true);
    });
  });

  describe("storageKey", () => {
    it("returns consistent format", () => {
      assert.equal(
        storageKey("luma-user-123"),
        "luma-orchestrator-chat-v1-luma-user-123"
      );
    });
  });

  describe("resume fallback", () => {
    it("failed event clears pending and sets error", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        pending: true,
        lastAction: { kind: "message", text: "Hello" },
      };

      const error = {
        status: 404,
        code: "not_found",
        retryable: false,
        message: "Session not found",
      } as OrchestratorError;

      const next = chatReducer(state, { type: "failed", error });

      assert.equal(next.pending, false);
      assert.deepEqual(next.error, error);
    });
  });

  describe("shouldStartFresh", () => {
    it("returns true for 404", () => {
      const error = {
        status: 404,
        code: "not_found",
        retryable: false,
        message: "Not found",
      } as OrchestratorError;
      assert.equal(shouldStartFresh(error), true);
    });

    it("returns true for 403", () => {
      const error = {
        status: 403,
        code: "forbidden",
        retryable: false,
        message: "Forbidden",
      } as OrchestratorError;
      assert.equal(shouldStartFresh(error), true);
    });

    it("returns false for 500", () => {
      const error = {
        status: 500,
        code: "internal_error",
        retryable: true,
        message: "Server error",
      } as OrchestratorError;
      assert.equal(shouldStartFresh(error), false);
    });

    it("returns false for 0/unavailable", () => {
      const error = {
        status: 0,
        code: "unavailable",
        retryable: true,
        message: "Service unavailable",
      } as OrchestratorError;
      assert.equal(shouldStartFresh(error), false);
    });
  });

  describe("isValidCustomerId", () => {
    it("returns true for demo customer ids", () => {
      assert.equal(isValidCustomerId("cust-dan-ionescu"), true);
      assert.equal(isValidCustomerId("cust-alex-morgan"), true);
    });

    it("returns false for invalid customers", () => {
      assert.equal(isValidCustomerId("../x"), false);
      assert.equal(isValidCustomerId("cust-Dan"), false);
      assert.equal(isValidCustomerId("invalid"), false);
      assert.equal(isValidCustomerId(""), false);
    });
  });

  describe("getRetryAction", () => {
    it("returns start action when session failed to initialize", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: null,
        lastAction: null,
        error: {
          status: 0,
          code: "unavailable",
          retryable: true,
          message: "Service unavailable",
        } as OrchestratorError,
      };
      const action = getRetryAction(state);
      assert.deepEqual(action, { kind: "start" });
    });

    it("returns null for confirm actions", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        lastAction: {
          kind: "confirm",
          summaryVersion: "v1",
          decision: "confirm",
        },
      };
      const action = getRetryAction(state);
      assert.equal(action, null);
    });

    it("returns lastAction for other actions", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        lastAction: { kind: "message", text: "Hello" },
      };
      const action = getRetryAction(state);
      assert.deepEqual(action, { kind: "message", text: "Hello" });
    });

    it("returns null when no action to retry", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        lastAction: null,
      };
      const action = getRetryAction(state);
      assert.equal(action, null);
    });
  });

  describe("retryNotice", () => {
    it("explains that nothing was submitted after a failed confirm", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        lastAction: { kind: "confirm", summaryVersion: "v1", decision: "confirm" },
        error: { status: 0, code: "unavailable", retryable: true, message: "down" } as OrchestratorError,
      };
      assert.equal(
        retryNotice(state),
        "Nothing was submitted. Review the summary and press Confirm again."
      );
    });

    it("is null for retryable non-confirm actions", () => {
      const state: ChatState = {
        ...initialChatState,
        sessionId: "sess-123",
        lastAction: { kind: "message", text: "Hello" },
      };
      assert.equal(retryNotice(state), null);
    });
  });

  describe("lastAssistantEntryIndex", () => {
    it("finds the last assistant entry even when a customer entry is last", () => {
      const entry = (id: string, role: "customer" | "assistant"): ChatEntry => ({ id, role, text: id, citations: [] });
      const state: ChatState = {
        ...initialChatState,
        entries: [entry("a1", "assistant"), entry("c1", "customer"), entry("a2", "assistant"), entry("c2", "customer")],
      };
      assert.equal(lastAssistantEntryIndex(state), 2);
      assert.equal(lastAssistantEntryIndex(initialChatState), -1);
    });
  });
});
