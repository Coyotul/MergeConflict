import type {
  TurnResponse,
  SessionView,
  ApplicationSummary,
  OrchestratorError,
  CitationRef,
  ChatMessageView,
} from "./orchestrator";

export interface ChatEntry {
  id: string;
  role: "customer" | "assistant";
  text: string;
  citations: CitationRef[];
}

export type PendingAction =
  | { kind: "message"; text: string }
  | { kind: "upload"; docType: string; file: File; filename: string }
  | { kind: "offer"; offerId: string }
  | { kind: "start" };

export interface ChatState {
  sessionId: string | null;
  customerId: string | null;
  entries: ChatEntry[];
  latest: TurnResponse | null;
  pending: boolean;
  error: OrchestratorError | null;
  lastAction: PendingAction | null;
}

export const initialChatState: ChatState = {
  sessionId: null,
  customerId: null,
  entries: [],
  latest: null,
  pending: false,
  error: null,
  lastAction: null,
};

export type ChatEvent =
  | { type: "started"; customerId: string; response: TurnResponse }
  | {
      type: "resumed";
      customerId: string;
      sessionId: string;
      view: SessionView;
    }
  | {
      type: "requested";
      action: PendingAction;
      localEntry?: ChatEntry;
    }
  | { type: "succeeded"; response: TurnResponse }
  | { type: "failed"; error: OrchestratorError }
  | { type: "reset" };

function messageViewToEntry(msg: ChatMessageView, index: number): ChatEntry {
  return {
    id: `${msg.role}-${msg.created_at}-${index}`,
    role: msg.role,
    text: msg.text,
    citations: msg.citations,
  };
}

export function chatReducer(state: ChatState, event: ChatEvent): ChatState {
  switch (event.type) {
    case "started":
      return {
        ...state,
        sessionId: event.response.session_id,
        customerId: event.customerId,
        latest: event.response,
        pending: false,
        error: null,
        entries: event.response.messages.map((msg, i) =>
          messageViewToEntry(msg, i)
        ),
      };

    case "resumed": {
      // Build entries from view.messages (contract: latest.messages is empty on GET)
      const entries = event.view.messages.map((msg, i) =>
        messageViewToEntry(msg, i)
      );

      return {
        ...state,
        sessionId: event.sessionId,
        customerId: event.customerId,
        latest: event.view.latest,
        entries,
        pending: false,
        error: null,
      };
    }

    case "requested": {
      const nextState: ChatState = {
        ...state,
        pending: true,
        error: null,
        lastAction: event.action,
      };

      // For message actions, append the customer's own entry immediately
      if (event.localEntry) {
        nextState.entries = [...state.entries, event.localEntry];
      }

      return nextState;
    }

    case "succeeded": {
      // Ignore responses from a different session (stale after restart)
      if (
        state.sessionId !== null &&
        event.response.session_id !== state.sessionId
      ) {
        return { ...state, pending: false };
      }

      // Append assistant messages from the response
      const newEntries = event.response.messages.map((msg, i) =>
        messageViewToEntry(msg, state.entries.length + i)
      );

      return {
        ...state,
        entries: [...state.entries, ...newEntries],
        latest: event.response,
        pending: false,
        error: null,
      };
    }

    case "failed":
      return {
        ...state,
        pending: false,
        error: event.error,
      };

    case "reset":
      return {
        ...initialChatState,
      };

    default:
      return state;
  }
}

export function canSend(state: ChatState): boolean {
  return !state.pending && state.sessionId !== null;
}

export function hasCustomerMessages(state: ChatState): boolean {
  return state.entries.some((entry) => entry.role === "customer");
}

/** Index of the latest assistant entry (blocks render under it), or -1. */
export function lastAssistantEntryIndex(state: ChatState): number {
  for (let i = state.entries.length - 1; i >= 0; i--) {
    if (state.entries[i].role === "assistant") return i;
  }
  return -1;
}

export function storageKey(lumaCustomerId: string): string {
  return `luma-orchestrator-chat-v1-${lumaCustomerId}`;
}

export function shouldStartFresh(error: OrchestratorError): boolean {
  return error.status === 404 || error.status === 403;
}

export function isValidCustomerId(customerId: string): boolean {
  return /^cust-[a-z0-9-]+$/.test(customerId);
}

export function getRetryAction(state: ChatState): PendingAction | null {
  // If session failed to start/resume, retry initialization
  if (!state.sessionId && !state.lastAction) {
    return { kind: "start" };
  }

  return state.lastAction;
}

