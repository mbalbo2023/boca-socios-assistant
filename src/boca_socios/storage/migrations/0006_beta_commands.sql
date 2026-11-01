CREATE TABLE beta_commands (
  command_id TEXT PRIMARY KEY CHECK (length(command_id) = 36),
  request_id TEXT NOT NULL UNIQUE REFERENCES ticket_requests(request_id) ON DELETE RESTRICT,
  state TEXT NOT NULL CHECK (state IN (
    'accepted', 'running', 'stop_requested', 'stopped', 'completed', 'failed', 'needs_review'
  )),
  created_at REAL NOT NULL CHECK (created_at >= 0),
  updated_at REAL NOT NULL CHECK (updated_at >= created_at),
  notice_enqueued INTEGER NOT NULL DEFAULT 0 CHECK (notice_enqueued IN (0, 1)),
  CHECK (notice_enqueued = 0 OR state = 'completed')
);

CREATE INDEX idx_beta_commands_pending ON beta_commands(state, created_at);

CREATE TABLE beta_command_keys (
  command_key TEXT PRIMARY KEY CHECK (length(command_key) = 36),
  command_id TEXT NOT NULL REFERENCES beta_commands(command_id) ON DELETE RESTRICT
);

CREATE INDEX idx_beta_command_keys_owner ON beta_command_keys(command_id);
