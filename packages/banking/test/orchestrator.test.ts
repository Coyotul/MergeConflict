import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { createOrchestratorClient, OrchestratorError, isKnownBlock } from "../src/orchestrator";

type RequestLog = { method: string; url: string; headers: Record<string, string | string[] | undefined>; body: string };

function fixture() {
  const logs: RequestLog[] = [];
  let handler: ((req: IncomingMessage, res: ServerResponse) => void) | null = null;

  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      logs.push({ method: req.method!, url: req.url!, headers: req.headers, body });
      if (handler) handler(req, res);
      else { res.writeHead(404); res.end(); }
    });
  });

  return new Promise<{
    url: string;
    logs: RequestLog[];
    setHandler: (h: (req: IncomingMessage, res: ServerResponse) => void) => void;
    close: () => Promise<void>;
  }>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
      resolve({
        url,
        logs,
        setHandler: (h) => { handler = h; },
        close: () => new Promise<void>((res, rej) => server.close((err) => err ? rej(err) : res())),
      });
    });
  });
}

test("sends X-Customer-Id and JSON body", async () => {
  const f = await fixture();
  try {
    f.setHandler((req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        session_id: "sess_1",
        turn_id: "turn_1",
        session_version: 1,
        messages: [{ role: "assistant", text: "Hello", citations: [], created_at: new Date().toISOString() }],
        awaiting: { kind: "text" },
        progress: { flow: "none", stage: null, steps: [] },
        blocks: [],
        simulated: true,
      }));
    });

    const client = createOrchestratorClient("customer-123", f.url);
    await client.sendMessage("sess_1", "Hello");

    assert.equal(f.logs.length, 1);
    const log = f.logs[0];
    assert.equal(log.method, "POST");
    assert.equal(log.url, "/chat/sessions/sess_1/messages");
    assert.equal(log.headers["x-customer-id"], "customer-123");
    assert.equal(log.headers["content-type"], "application/json");
    assert.deepEqual(JSON.parse(log.body), { text: "Hello" });
  } finally { await f.close(); }
});

test("upload sends multipart doc_type and file", async () => {
  const f = await fixture();
  try {
    f.setHandler((req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        session_id: "sess_1",
        turn_id: "turn_2",
        session_version: 2,
        messages: [{ role: "assistant", text: "Received", citations: [], created_at: new Date().toISOString() }],
        awaiting: { kind: "text" },
        progress: { flow: "none", stage: null, steps: [] },
        blocks: [],
        simulated: true,
      }));
    });

    const client = createOrchestratorClient("customer-123", f.url);
    const blob = new Blob(["test file content"], { type: "application/pdf" });
    await client.uploadDocument("sess_1", "pay_stub", blob, "stub.pdf");

    assert.equal(f.logs.length, 1);
    const log = f.logs[0];
    assert.equal(log.method, "POST");
    assert.equal(log.url, "/chat/sessions/sess_1/documents");
    assert.equal(log.headers["x-customer-id"], "customer-123");
    assert.match(log.headers["content-type"] as string, /^multipart\/form-data; boundary=/);
    assert.match(log.body, /doc_type/);
    assert.match(log.body, /pay_stub/);
    assert.match(log.body, /filename="stub\.pdf"/);
  } finally { await f.close(); }
});

test("maps ErrorBody to OrchestratorError", async () => {
  const f = await fixture();
  try {
    f.setHandler((req, res) => {
      res.writeHead(503, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ code: "service_unavailable", message: "Service down", retryable: true }));
    });

    const client = createOrchestratorClient("customer-123", f.url);

    await assert.rejects(
      async () => client.createSession(),
      (err: OrchestratorError) => {
        assert.equal(err.status, 503);
        assert.equal(err.code, "service_unavailable");
        assert.equal(err.retryable, true);
        assert.equal(err.message, "Service down");
        return true;
      }
    );
  } finally { await f.close(); }
});

test("client maps network failure to unavailable", async () => {
  const client = createOrchestratorClient("customer-123", "http://127.0.0.1:9");

  await assert.rejects(
    async () => client.createSession(),
    (err: OrchestratorError) => {
      assert.equal(err.status, 0);
      assert.equal(err.code, "unavailable");
      assert.equal(err.retryable, true);
      assert.match(err.message, /not reachable/);
      return true;
    }
  );
});

test("client tolerates unknown block types", async () => {
  const f = await fixture();
  try {
    f.setHandler((req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        session_id: "sess_1",
        turn_id: "turn_1",
        session_version: 1,
        messages: [{ role: "assistant", text: "Hello", citations: [], created_at: new Date().toISOString() }],
        awaiting: { kind: "text" },
        progress: { flow: "none", stage: null, steps: [] },
        blocks: [
          { type: "offers", offers: [], selected_offer_id: null },
          { type: "future_block", some_field: "value" }
        ],
        simulated: true,
      }));
    });

    const client = createOrchestratorClient("customer-123", f.url);
    const response = await client.createSession();

    assert.equal(response.blocks.length, 2);
    assert.equal(isKnownBlock(response.blocks[0]), true);
    assert.equal(isKnownBlock(response.blocks[1]), false);
    assert.equal(response.blocks[1].type, "future_block");
  } finally { await f.close(); }
});

test("confirm sends summary_version and decision", async () => {
  const f = await fixture();
  try {
    f.setHandler((req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        session_id: "sess_1",
        turn_id: "turn_3",
        session_version: 3,
        messages: [{ role: "assistant", text: "Confirmed", citations: [], created_at: new Date().toISOString() }],
        awaiting: { kind: "none" },
        progress: { flow: "credit_application", stage: "submitted", steps: [] },
        blocks: [],
        simulated: true,
      }));
    });

    const client = createOrchestratorClient("customer-123", f.url);
    await client.confirm("sess_1", "v1", "confirm");

    assert.equal(f.logs.length, 1);
    const log = f.logs[0];
    assert.equal(log.method, "POST");
    assert.equal(log.url, "/chat/sessions/sess_1/confirmation");
    assert.deepEqual(JSON.parse(log.body), { summary_version: "v1", decision: "confirm" });
  } finally { await f.close(); }
});

test("client maps 2xx invalid JSON to invalid_response", async () => {
  const f = await fixture();
  try {
    f.setHandler((req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end("not json");
    });

    const client = createOrchestratorClient("customer-123", f.url);

    await assert.rejects(
      async () => client.createSession(),
      (err: OrchestratorError) => {
        assert.equal(err.status, 200);
        assert.equal(err.code, "invalid_response");
        assert.equal(err.retryable, true);
        assert.match(err.message, /unreadable response/);
        return true;
      }
    );
  } finally { await f.close(); }
});

test("getSession parses SessionView", async () => {
  const f = await fixture();
  try {
    const now = new Date().toISOString();
    f.setHandler((req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        session_id: "sess_1",
        created_at: now,
        messages: [
          { role: "customer", text: "Hello", citations: [], created_at: now },
          { role: "assistant", text: "Hi", citations: [], created_at: now }
        ],
        latest: {
          session_id: "sess_1",
          turn_id: "turn_1",
          session_version: 1,
          messages: [{ role: "assistant", text: "Hi", citations: [], created_at: now }],
          awaiting: { kind: "text" },
          progress: { flow: "none", stage: null, steps: [] },
          blocks: [],
          simulated: true,
        }
      }));
    });

    const client = createOrchestratorClient("customer-123", f.url);
    const session = await client.getSession("sess_1");

    assert.equal(session.session_id, "sess_1");
    assert.equal(session.messages.length, 2);
    assert.equal(session.latest.turn_id, "turn_1");
    assert.equal(f.logs[0].method, "GET");
    assert.equal(f.logs[0].url, "/chat/sessions/sess_1");
  } finally { await f.close(); }
});

test("selectOffer sends offer_id", async () => {
  const f = await fixture();
  try {
    f.setHandler((req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        session_id: "sess_1",
        turn_id: "turn_4",
        session_version: 4,
        messages: [{ role: "assistant", text: "Offer selected", citations: [], created_at: new Date().toISOString() }],
        awaiting: { kind: "confirmation", summary_version: "v1" },
        progress: { flow: "credit_application", stage: "summary", steps: [] },
        blocks: [],
        simulated: true,
      }));
    });

    const client = createOrchestratorClient("customer-123", f.url);
    await client.selectOffer("sess_1", "offer-123");

    assert.equal(f.logs.length, 1);
    const log = f.logs[0];
    assert.equal(log.method, "POST");
    assert.equal(log.url, "/chat/sessions/sess_1/offer-selection");
    assert.deepEqual(JSON.parse(log.body), { offer_id: "offer-123" });
  } finally { await f.close(); }
});
