"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  createOrchestratorClient,
  OrchestratorError,
  type TurnResponse,
} from "./orchestrator";
import {
  chatReducer,
  initialChatState,
  pickCustomer,
  canSend,
  storageKey,
  shouldStartFresh,
  isValidCustomerId,
  type ChatState,
  type ChatEntry,
  type PendingAction,
} from "./orchestrator-state";

interface StoredSession {
  sessionId: string;
  customerId: string;
}

function parseStoredSession(value: string | null): StoredSession | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    if (
      typeof parsed === "object" &&
      typeof parsed.sessionId === "string" &&
      typeof parsed.customerId === "string" &&
      isValidCustomerId(parsed.customerId)
    ) {
      return parsed;
    }
  } catch {
    // Invalid JSON
  }
  return null;
}

export function useOrchestratorChat(lumaCustomerId: string | undefined) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const initForRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const actionLockRef = useRef(false);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startFresh = useCallback(
    (key: string, currentEpoch: number) => {
      const newCustomerId = pickCustomer();
      const client = createOrchestratorClient(newCustomerId);
      client
        .createSession()
        .then((response) => {
          // Ignore if epoch changed (restart or user change happened)
          if (epochRef.current !== currentEpoch) return;

          dispatch({ type: "started", customerId: newCustomerId, response });
          sessionStorage.setItem(
            key,
            JSON.stringify({
              sessionId: response.session_id,
              customerId: newCustomerId,
            })
          );
          actionLockRef.current = false;
        })
        .catch((error) => {
          // Ignore if epoch changed
          if (epochRef.current !== currentEpoch) return;

          dispatch({
            type: "failed",
            error:
              error instanceof OrchestratorError
                ? error
                : new OrchestratorError(
                    0,
                    "unknown",
                    false,
                    "Failed to start session"
                  ),
          });
          actionLockRef.current = false;
        });
    },
    []
  );

  const resumeOrStart = useCallback(
    (key: string, currentEpoch: number) => {
      const stored = parseStoredSession(sessionStorage.getItem(key));

      if (stored) {
        // Try to resume existing session
        const client = createOrchestratorClient(stored.customerId);
        client
          .getSession(stored.sessionId)
          .then((view) => {
            // Ignore if epoch changed
            if (epochRef.current !== currentEpoch) return;

            dispatch({
              type: "resumed",
              customerId: stored.customerId,
              sessionId: stored.sessionId,
              view,
            });
            actionLockRef.current = false;
          })
          .catch((error) => {
            // Ignore if epoch changed
            if (epochRef.current !== currentEpoch) return;

            // Only clear storage and start fresh on 404/403
            if (error instanceof OrchestratorError && shouldStartFresh(error)) {
              sessionStorage.removeItem(key);
              startFresh(key, currentEpoch);
            } else {
              // Other errors: dispatch failed, keep stored session, allow retry
              dispatch({
                type: "failed",
                error:
                  error instanceof OrchestratorError
                    ? error
                    : new OrchestratorError(
                        0,
                        "unknown",
                        false,
                        "Failed to resume session"
                      ),
              });
              actionLockRef.current = false;
            }
          });
      } else {
        // Start new session
        startFresh(key, currentEpoch);
      }
    },
    [startFresh]
  );

  // Initialize or reinitialize on lumaCustomerId change
  useEffect(() => {
    // Handle undefined: reset state
    if (!lumaCustomerId) {
      if (initForRef.current !== undefined) {
        dispatch({ type: "reset" });
        initForRef.current = undefined;
        epochRef.current++;
        actionLockRef.current = false;
      }
      return;
    }

    // Handle change: reset and start for new id
    if (initForRef.current !== lumaCustomerId) {
      dispatch({ type: "reset" });
      initForRef.current = lumaCustomerId;
      epochRef.current++;
      actionLockRef.current = true; // Lock during init

      const key = storageKey(lumaCustomerId);
      resumeOrStart(key, epochRef.current);
    }

    // Cleanup: clear retry timer
    return () => {
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [lumaCustomerId, resumeOrStart]);

  const executeAction = useCallback(
    async (
      action: PendingAction,
      localEntry?: ChatEntry
    ): Promise<boolean> => {
      if (actionLockRef.current || !state.customerId) {
        return false;
      }

      // Handle start action (for retry when orchestrator was down at mount)
      if (action.kind === "start") {
        if (!lumaCustomerId) return false;
        actionLockRef.current = true;
        const key = storageKey(lumaCustomerId);
        resumeOrStart(key, epochRef.current);
        return true;
      }

      // Other actions require sessionId
      if (!canSend(state)) {
        return false;
      }

      actionLockRef.current = true;
      dispatch({ type: "requested", action, localEntry });

      const client = createOrchestratorClient(state.customerId);
      const currentEpoch = epochRef.current;

      const performRequest = async (isRetry: boolean = false) => {
        try {
          let response: TurnResponse;
          switch (action.kind) {
            case "message":
              response = await client.sendMessage(state.sessionId!, action.text);
              break;
            case "upload":
              response = await client.uploadDocument(
                state.sessionId!,
                action.docType,
                action.file,
                action.filename
              );
              break;
            case "offer":
              response = await client.selectOffer(
                state.sessionId!,
                action.offerId
              );
              break;
            case "confirm":
              response = await client.confirm(
                state.sessionId!,
                action.summaryVersion,
                action.decision
              );
              break;
            default:
              return;
          }

          // Ignore if epoch changed (restart happened)
          if (epochRef.current !== currentEpoch) return;

          dispatch({ type: "succeeded", response });
          actionLockRef.current = false;
        } catch (error) {
          // Ignore if epoch changed
          if (epochRef.current !== currentEpoch) return;

          if (error instanceof OrchestratorError) {
            // Handle 409 session_busy with automatic retry (except for confirm)
            if (
              error.status === 409 &&
              error.code === "session_busy" &&
              !isRetry &&
              action.kind !== "confirm"
            ) {
              retryTimerRef.current = setTimeout(() => {
                retryTimerRef.current = null;
                performRequest(true).catch(() => {
                  // Retry failed
                });
              }, 1000);
              return;
            }

            dispatch({ type: "failed", error });
          } else {
            dispatch({
              type: "failed",
              error: new OrchestratorError(
                0,
                "unknown",
                false,
                "An unexpected error occurred"
              ),
            });
          }
          actionLockRef.current = false;
        }
      };

      await performRequest();
      return true;
    },
    [state, lumaCustomerId, resumeOrStart]
  );

  const send = useCallback(
    async (text: string): Promise<boolean> => {
      const localEntry: ChatEntry = {
        id: `customer-${Date.now()}`,
        role: "customer",
        text,
        citations: [],
      };
      return executeAction({ kind: "message", text }, localEntry);
    },
    [executeAction]
  );

  const upload = useCallback(
    async (docType: string, file: File): Promise<boolean> => {
      return executeAction({
        kind: "upload",
        docType,
        file,
        filename: file.name,
      });
    },
    [executeAction]
  );

  const chooseOffer = useCallback(
    async (offerId: string): Promise<boolean> => {
      return executeAction({ kind: "offer", offerId });
    },
    [executeAction]
  );

  const confirm = useCallback(
    async (
      summaryVersion: string,
      decision: "confirm" | "decline"
    ): Promise<boolean> => {
      return executeAction({ kind: "confirm", summaryVersion, decision });
    },
    [executeAction]
  );

  const retry = useCallback(async (): Promise<boolean> => {
    // If orchestrator was down at mount, retry start
    if (!state.sessionId && !state.lastAction) {
      return executeAction({ kind: "start" });
    }

    if (!state.lastAction || state.lastAction.kind === "confirm") {
      return false;
    }

    // For message actions, don't append a new local entry (already in state)
    if (state.lastAction.kind === "message") {
      return executeAction(state.lastAction);
    }

    return executeAction(state.lastAction);
  }, [state.lastAction, state.sessionId, executeAction]);

  const restart = useCallback(() => {
    if (!lumaCustomerId) return;

    // Respect lock
    if (actionLockRef.current) return;

    // Clear retry timer
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }

    // Increment epoch to drop stale responses
    epochRef.current++;
    actionLockRef.current = true;

    // Clear storage
    const key = storageKey(lumaCustomerId);
    sessionStorage.removeItem(key);

    // Reset state
    dispatch({ type: "reset" });

    // Start new session
    startFresh(key, epochRef.current);
  }, [lumaCustomerId, startFresh]);

  return {
    state,
    send,
    upload,
    chooseOffer,
    confirm,
    retry,
    restart,
  };
}
