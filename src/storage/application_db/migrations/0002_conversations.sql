-- Conversation sessions table
CREATE TABLE conversation_sessions (
    session_id text PRIMARY KEY,
    customer_id text NOT NULL,
    state jsonb NOT NULL,
    version integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversation_sessions_customer_id ON conversation_sessions (customer_id);

-- Conversation messages table
CREATE TABLE conversation_messages (
    id bigserial PRIMARY KEY,
    session_id text NOT NULL REFERENCES conversation_sessions ON DELETE CASCADE,
    message_id text NOT NULL UNIQUE,
    turn_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('customer', 'assistant', 'action', 'tool', 'event')),
    content text NOT NULL,
    citations jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL
);

CREATE INDEX idx_conversation_messages_session_id_id ON conversation_messages (session_id, id);
