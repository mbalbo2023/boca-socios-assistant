CREATE TABLE reservation_attempts_simulation (
  request_id TEXT PRIMARY KEY REFERENCES ticket_requests(request_id) ON DELETE RESTRICT,
  claim_token TEXT NOT NULL UNIQUE CHECK (length(claim_token) = 36),
  attempt_kind TEXT NOT NULL DEFAULT 'external' CHECK (attempt_kind IN ('external', 'simulation')),
  state TEXT NOT NULL CHECK (
    (attempt_kind = 'external' AND state IN ('in_flight', 'needs_review', 'provider_ack_reported'))
    OR (attempt_kind = 'simulation' AND state IN ('in_flight', 'needs_review', 'simulation_completed', 'simulation_failed'))
  ),
  started_at REAL NOT NULL,
  review_after REAL NOT NULL CHECK (review_after > started_at),
  closed_at REAL,
  CHECK (
    (state = 'in_flight' AND closed_at IS NULL)
    OR (state != 'in_flight' AND closed_at IS NOT NULL)
  )
);

INSERT INTO reservation_attempts_simulation
  (request_id, claim_token, state, started_at, review_after, closed_at)
  SELECT request_id, claim_token, state, started_at, review_after, closed_at
  FROM reservation_attempts;

DROP TABLE reservation_attempts;
ALTER TABLE reservation_attempts_simulation RENAME TO reservation_attempts;
CREATE INDEX idx_reservation_review ON reservation_attempts(state, review_after);
