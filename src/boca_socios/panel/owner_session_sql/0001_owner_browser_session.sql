CREATE TABLE owner_browser_session (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  token_sha256 BLOB NOT NULL CHECK (length(token_sha256) = 32),
  verifier_sha256 BLOB NOT NULL CHECK (length(verifier_sha256) = 32),
  owner_sha256 BLOB NOT NULL CHECK (length(owner_sha256) = 32),
  authenticated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE owner_session_schema (
  version INTEGER PRIMARY KEY CHECK (version = 1),
  checksum TEXT NOT NULL CHECK (length(checksum) = 64)
);
