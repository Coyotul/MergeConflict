"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { createOrchestratorClient, OrchestratorError } from "./orchestrator";
import {
  chatReducer,
  initialChatState,
  pickCustomer,
  canSend,
  storageKey,
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
      typeof parsed.customerId === "string"
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
  const initRef = useRef(false);
  const actionLockRef = useRef(false);

  // Initialize session on mount
  useEffect(() => {
    if (!lumaCustomerId || initRef.current) return;
    initRef.current = true;

    const key = storageKey(lumaCustomerId);
    const stored = parseStoredSession(sessionStorage.getItem(key));

    if (stored) {
      // Try to resume existing session
      const client = createOrchestratorClient(stored.customerId);
      client
        .getSession(stored.sessionId)
        .then((view) => {
          dispatch({
            type: "resumed",
            customerId: stored.customerId,
            sessionId: stored.sessionId,
            view,
          });
        })
        .catch((error) => {
          // On 404/403 or any error, clear storage and start fresh
          if (
            error instanceof OrchestratorError &&
            (error.status === 404 || error.status === 403)
          ) {
            sessionStorage.removeItem(key);
          }
          // Start fresh session
          const newCustomerId = pickCustomer();
          const newClient = createOrchestratorClient(newCustomerId);
          newClient
            .createSession()
            .then((response) => {
              dispatch({ type: "started", customerId: newCustomerId, response });
              sessionStorage.setItem(
                key,
                JSON.stringify({
                  sessionId: response.session_id,
                  customerId: newCustomerId,
                })
              );
            })
            .catch((startError) => {
              dispatch({
                type: "failed",
                error:
                  startError instanceof OrchestratorError
                    ? startError
                    : new OrchestratorError(
                        0,
                        "unknown",
                        false,
                        "Failed to start session"
                      ),
              });
            });
        });
    } else {
      // Start new session
      const newCustomerId = pickCustomer();
      const client = createOrchestratorClient(newCustomerId);
      client
        .createSession()
        .then((response) => {
          dispatch({ type: "started", customerId: newCustomerId, response });
          sessionStorage.setItem(
            key,
            JSON.stringify({
              sessionId: response.session_id,
              customerId: newCustomerId,
            })
          );
        })
        .catch((error) => {
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
        });
    }
  }, [lumaCustomerId]);

  const executeAction = useCallback(
    async (
      action: PendingAction,
      localEntry?: ChatEntry
    ): Promise<boolean> => {
      if (!canSend(state) || actionLockRef.current || !state.customerId) {
        return false;
      }

      actionLockRef.current = true;
      dispatch({ type: "requested", action, localEntry });

      const client = createOrchestratorClient(state.customerId);

      const performRequest = async (isRetry: boolean = false) => {
        try {
          let response;
          switch (action.kind) {
            case "start":
              // Start is handled in useEffect
              return;
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
          }

          dispatch({ type: "succeeded", response });
          actionLockRef.current = false;
        } catch (error) {
          if (error instanceof OrchestratorError) {
            // Handle 409 session_busy with automatic retry (except for confirm)
            if (
              error.status === 409 &&
              error.code === "session_busy" &&
              !isRetry &&
              action.kind !== "confirm"
            ) {
              setTimeout(() => {
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
    [state]
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
    if (!state.lastAction || state.lastAction.kind === "confirm") {
      return false;
    }

    // For message actions, re-create the local entry
    if (state.lastAction.kind === "message") {
      const localEntry: ChatEntry = {
        id: `customer-retry-${Date.now()}`,
        role: "customer",
        text: state.lastAction.text,
        citations: [],
      };
      return executeAction(state.lastAction, localEntry);
    }

    return executeAction(state.lastAction);
  }, [state.lastAction, executeAction]);

  const restart = useCallback(() => {
    if (!lumaCustomerId) return;

    // Clear storage
    const key = storageKey(lumaCustomerId);
    sessionStorage.removeItem(key);

    // Reset state
    dispatch({ type: "reset" });

    // Start new session
    const newCustomerId = pickCustomer();
    const client = createOrchestratorClient(newCustomerId);
    client
      .createSession()
      .then((response) => {
        dispatch({ type: "started", customerId: newCustomerId, response });
        sessionStorage.setItem(
          key,
          JSON.stringify({
            sessionId: response.session_id,
            customerId: newCustomerId,
          })
        );
      })
      .catch((error) => {
        dispatch({
          type: "failed",
          error:
            error instanceof OrchestratorError
              ? error
              : new OrchestratorError(
                  0,
                  "unknown",
                  false,
                  "Failed to restart session"
                ),
        });
      });
  }, [lumaCustomerId]);

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
