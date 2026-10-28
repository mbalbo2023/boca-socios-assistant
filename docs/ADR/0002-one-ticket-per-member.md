# ADR 0002: Exactly one ticket per member per event

Status: Accepted, 2026-10-28.

Decision: quantity is exactly 1; database enforces CHECK(quantity=1),
UNIQUE(member_id,event_id) and foreign-key integrity.

Reason: explicit owner product rule; browser/queue session count must never
change the quantity of ticket purchases a member is allowed to request.

Consequence: exceptions require an explicit owner decision and a new ADR,
not a feature flag or bypass in the UI.

