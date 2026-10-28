CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actors (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL CHECK (json_valid(payload))
);

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY REFERENCES actors(id),
    payload TEXT NOT NULL CHECK (json_valid(payload))
);

CREATE TABLE IF NOT EXISTS loans (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    payload TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS loans_owner ON loans(customer_id);

CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    reviewer_id TEXT NOT NULL REFERENCES actors(id),
    payload TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS applications_owner ON applications(customer_id);
CREATE INDEX IF NOT EXISTS applications_reviewer ON applications(reviewer_id);

CREATE TABLE IF NOT EXISTS consents (
    customer_id TEXT PRIMARY KEY REFERENCES customers(id),
    payload TEXT NOT NULL CHECK (json_valid(payload))
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    application_id TEXT REFERENCES applications(id),
    payload TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS notifications_owner ON notifications(customer_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL REFERENCES actors(id),
    object_id TEXT NOT NULL,
    action TEXT NOT NULL,
    payload TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS audit_object ON audit_events(object_id);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    payload TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS messages_owner ON conversation_messages(customer_id);

CREATE TABLE IF NOT EXISTS support_requests (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    application_id TEXT REFERENCES applications(id),
    payload TEXT NOT NULL CHECK (json_valid(payload))
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    actor_id TEXT NOT NULL REFERENCES actors(id),
    key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    response TEXT NOT NULL CHECK (json_valid(response)),
    PRIMARY KEY (actor_id, key)
);