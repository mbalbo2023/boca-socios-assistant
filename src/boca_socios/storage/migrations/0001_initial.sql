PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS members (
  member_id TEXT PRIMARY KEY,
  email TEXT NOT NULL COLLATE NOCASE UNIQUE,
  display_name TEXT,
  consent_recorded_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS credentials (
  member_id TEXT PRIMARY KEY REFERENCES members(member_id) ON DELETE CASCADE,
  key_id TEXT NOT NULL,
  nonce BLOB NOT NULL CHECK (length(nonce) = 12),
  ciphertext BLOB NOT NULL CHECK (length(ciphertext) > 16),
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  reservation_starts_at TEXT,
  source_url TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ticket_requests (
  request_id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
  event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
  quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity = 1),
  status TEXT NOT NULL DEFAULT 'planned' CHECK (
    status IN ('planned', 'queued', 'admitted', 'reserved', 'rejected', 'cancelled')
  ),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (member_id, event_id)
);

CREATE TABLE IF NOT EXISTS queue_sessions (
  session_id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
  event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (
    state IN ('created', 'prequeue', 'waiting', 'admitted', 'expired', 'closed', 'failed')
  ),
  queue_reference_hash TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_event_member
  ON queue_sessions(event_id, member_id);

CREATE TABLE IF NOT EXISTS audit_events (
  audit_id TEXT PRIMARY KEY,
  action TEXT NOT NULL,
  member_id TEXT REFERENCES members(member_id) ON DELETE SET NULL,
  event_id TEXT REFERENCES events(event_id) ON DELETE SET NULL,
  recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

