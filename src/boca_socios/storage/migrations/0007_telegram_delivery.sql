CREATE TABLE telegram_delivery_attempts (
  idempotency_key TEXT PRIMARY KEY NOT NULL
    REFERENCES notification_outbox(idempotency_key),
  attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
  state TEXT NOT NULL CHECK (state IN ('prepared', 'api_accepted', 'ambiguous')),
  prepared_at REAL NOT NULL,
  settled_at REAL,
  provider_message_id INTEGER,
  CHECK ((state = 'prepared' AND settled_at IS NULL AND provider_message_id IS NULL)
    OR (state = 'api_accepted' AND settled_at IS NOT NULL
      AND provider_message_id > 0)
    OR (state = 'ambiguous' AND settled_at IS NOT NULL
      AND provider_message_id IS NULL))
);
