CREATE TABLE credential_key_policy (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  key_id TEXT NOT NULL CHECK (length(key_id) BETWEEN 1 AND 64)
);

CREATE TRIGGER credential_key_insert BEFORE INSERT ON credentials
WHEN (SELECT key_id FROM credential_key_policy WHERE singleton=1) IS NULL
  OR NEW.key_id != (SELECT key_id FROM credential_key_policy WHERE singleton=1)
BEGIN
  SELECT RAISE(ABORT, 'credential key version inactive');
END;

CREATE TRIGGER credential_key_update BEFORE UPDATE OF key_id, nonce, ciphertext ON credentials
WHEN (SELECT key_id FROM credential_key_policy WHERE singleton=1) IS NULL
  OR NEW.key_id != (SELECT key_id FROM credential_key_policy WHERE singleton=1)
BEGIN
  SELECT RAISE(ABORT, 'credential key version inactive');
END;
