import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { z } from "zod";
import { FileStore } from "./store";
import { DemoSessions } from "./auth";
import { chatSchema, consentSchema, createApplicationSchema, noteSchema, reviewSchema, sessionSchema, submitSchema, supportSchema, uploadSchema } from "../src/schemas";
import { DomainError, requireRole } from "../src/workflow";
import { createApplication, submitApplication, uploadDocument } from "./applications";
import { addNote, reviewApplication } from "./reviews";
import { chat, requestSupport, resetChat, snapshot } from "./queries";
import { addAudit } from "./helpers";

const origins = new Set(["http://127.0.0.1:3000", "http://127.0.0.1:3001"]);
async function body(req: IncomingMessage): Promise<unknown> {
  let text = "";
  for await (const chunk of req) {
    text += chunk;
    if (Buffer.byteLength(text) > 32768) throw new DomainError("VALIDATION_ERROR", "Request is too large.", 413);
  }
  try { return JSON.parse(text || "{}"); } catch { throw new DomainError("VALIDATION_ERROR", "Invalid JSON request."); }
}
function send(res: ServerResponse, status: number, data: unknown) {
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
  res.end(JSON.stringify(data));
}
export function createDemoServer(store: FileStore) {
  const sessions = new DemoSessions();
  const server = createServer(async (req, res) => {
    const correlationId = crypto.randomUUID();
    try {
      const origin = req.headers.origin;
      if (origin && !origins.has(origin)) throw new DomainError("FORBIDDEN", "This origin is not allowed by the local demo.", 403);
      if (origin) { res.setHeader("Access-Control-Allow-Origin", origin); res.setHeader("Vary", "Origin"); }
      res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS");
      if (req.method === "OPTIONS") { res.writeHead(204); res.end(); return; }
      const path = new URL(req.url ?? "/", "http://127.0.0.1").pathname;
      if (path === "/health" && req.method === "GET") { send(res, 200, { status: "ok", mode: "synthetic-demo", persistence: "local-json" }); return; }
      if (path === "/api/session" && req.method === "POST") {
        const input = sessionSchema.parse(await body(req));
        send(res, 200, { data: sessions.create(input) }); return;
      }
      const token = req.headers.authorization?.replace(/^Bearer /, "") ?? "";
      const actor = sessions.require(token);
      if (path === "/api/session/logout" && req.method === "POST") {
        sessions.revoke(token);
        send(res, 200, { data: { signedOut: true } }); return;
      }
      if (path === "/api/snapshot" && req.method === "GET") { send(res, 200, { data: store.read((state) => snapshot(state, actor)) }); return; }
      const input = await body(req);
      let data: unknown;
      if (path === "/api/chat" && req.method === "POST") data = await store.transaction((s) => chat(s, actor, chatSchema.parse(input).text));
      else if (path === "/api/chat/reset" && req.method === "POST") data = await store.transaction((s) => resetChat(s, actor));
      else if (path === "/api/applications" && req.method === "POST") data = await store.transaction((s) => createApplication(s, actor, createApplicationSchema.parse(input)));
      else if (path === "/api/consent" && req.method === "PATCH") data = await store.transaction((s) => {
        requireRole(actor, "customer"); const consent = consentSchema.parse(input); s.consents[actor.id] = consent;
        addAudit(s, actor, "CONSENT_UPDATED", actor.id, JSON.stringify(consent)); return consent;
      });
      else if (path === "/api/notifications/read" && req.method === "POST") data = await store.transaction((s) => {
        requireRole(actor, "customer"); const records = s.notifications.filter((n) => n.customerId === actor.id); records.forEach((n) => { n.read = true; }); return records;
      });
      else if (path === "/api/support" && req.method === "POST") data = await store.transaction((s) => requestSupport(s, actor, supportSchema.parse(input).message));
      else {
        const match = path.match(/^\/api\/applications\/([^/]+)\/(documents|submit|review|notes)$/);
        if (!match || req.method !== "POST") throw new DomainError("NOT_FOUND", "Endpoint not found.", 404);
        const [, id, command] = match;
        data = await store.transaction((s) => {
          if (command === "documents") return uploadDocument(s, actor, id, uploadSchema.parse(input));
          if (command === "submit") return submitApplication(s, actor, id, submitSchema.parse(input));
          if (command === "review") return reviewApplication(s, actor, id, reviewSchema.parse(input));
          return addNote(s, actor, id, noteSchema.parse(input).text);
        });
      }
      if (actor.role === "customer" && data && typeof data === "object" && "notes" in data && Array.isArray(data.notes)) {
        data = { ...data, notes: data.notes.filter((note: { internal: boolean }) => !note.internal) };
      }
      send(res, 200, { data });
    } catch (error) {
      if (error instanceof z.ZodError) send(res, 400, { error: { code: "VALIDATION_ERROR", message: error.issues[0]?.message ?? "Invalid input.", correlationId } });
      else if (error instanceof DomainError) send(res, error.status, { error: { code: error.code, message: error.message, correlationId } });
      else { console.error(JSON.stringify({ level: "error", correlationId, message: "Demo command failed" })); send(res, 500, { error: { code: "INTERNAL_ERROR", message: "The demo service could not complete this action. Please retry.", correlationId } }); }
    }
  });
  return server;
}
