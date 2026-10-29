CREATE TABLE notification_outbox (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (
    kind IN ('action_required', 'queue_admitted', 'state_changed', 'heartbeat')
  ),
  priority INTEGER NOT NULL CHECK (priority BETWEEN 0 AND 3),
  state TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'accepted', 'exhausted')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL CHECK (expires_at > created_at),
  next_attempt_at REAL,
  lease_token TEXT,
  lease_until REAL,
  accepted_at REAL,
  CHECK ((state = 'pending' AND next_attempt_at IS NOT NULL AND lease_token IS NULL
      AND lease_until IS NULL AND accepted_at IS NULL)
    OR (state = 'claimed' AND next_attempt_at IS NULL AND lease_token IS NOT NULL
      AND lease_until IS NOT NULL AND accepted_at IS NULL)
    OR (state = 'accepted' AND next_attempt_at IS NULL AND lease_token IS NULL
      AND lease_until IS NULL AND accepted_at IS NOT NULL)
    OR (state = 'exhausted' AND next_attempt_at IS NULL AND lease_token IS NULL
      AND lease_until IS NULL AND accepted_at IS NULL))
);

CREATE INDEX idx_notification_due
  ON notification_outbox(state, next_attempt_at, priority DESC, sequence);

CREATE INDEX idx_notification_lease
  ON notification_outbox(state, lease_until);

CREATE TABLE notification_claim_windows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  attempted_at REAL NOT NULL
);

CREATE INDEX idx_notification_claim_times ON notification_claim_windows(attempted_at);
