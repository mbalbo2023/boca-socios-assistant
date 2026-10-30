CREATE TABLE reservation_attempts (
  request_id TEXT PRIMARY KEY REFERENCES ticket_requests(request_id) ON DELETE RESTRICT,
  claim_token TEXT NOT NULL UNIQUE CHECK (length(claim_token) = 36),
  state TEXT NOT NULL CHECK (
    state IN ('in_flight', 'needs_review', 'provider_ack_reported')
  ),
  started_at REAL NOT NULL,
  review_after REAL NOT NULL CHECK (review_after > started_at),
  closed_at REAL,
  CHECK (
    (state = 'in_flight' AND closed_at IS NULL)
    OR (state IN ('needs_review', 'provider_ack_reported') AND closed_at IS NOT NULL)
  )
);

CREATE INDEX idx_reservation_review
  ON reservation_attempts(state, review_after);
