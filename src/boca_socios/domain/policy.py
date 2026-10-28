"""One ticket per member and event. No client-side override is allowed."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TicketIntent:
    member_id: str
    event_id: str
    quantity: int = 1

    def validate(self) -> None:
        if not self.member_id or not self.event_id:
            raise ValueError("member_id and event_id are required")
        if self.quantity != 1:
            raise ValueError("exactly one ticket per member and event is permitted")
