"""
Timestamped decision log.

Every decision the engine makes appends an event here, which is what
``GET /history`` returns and what Person B persists to DynamoDB. Events are
plain JSON-safe dicts; ids are sequential so a demo replay is reproducible.
"""

import itertools
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class EventType:
    """Stable event-type strings consumed by the History panel."""

    EMERGENCY_CREATED = "emergency_created"
    HOSPITAL_REJECTED = "hospital_rejected"
    RECOMMENDATION = "recommendation"
    NO_FEASIBLE_OPTION = "no_feasible_option"
    DISPATCH_CONFIRMED = "dispatch_confirmed"
    AMBULANCE_MOVED = "ambulance_moved"
    CORRIDOR_GRANTED = "corridor_granted"
    CORRIDOR_RELEASED = "corridor_released"
    ARRIVED = "arrived"
    CHAOS_INJECTED = "chaos_injected"
    REROUTE_PROPOSED = "reroute_proposed"
    REROUTE_CONFIRMED = "reroute_confirmed"
    REROUTE_FAILED = "reroute_failed"


class HistoryLog:
    """Append-only event log feeding the History panel / audit trail."""

    def __init__(self, clock: Optional[Any] = None) -> None:
        self.events: List[Dict[str, Any]] = []
        self._counter = itertools.count(1)
        # Injectable clock keeps end-to-end tests deterministic.
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def add(self, event_type: str, message: str, **extra: Any) -> Dict[str, Any]:
        event: Dict[str, Any] = {
            "id": f"EVT{next(self._counter):03d}",
            "timestamp": self._clock().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event_type": event_type,
            "message": message,
        }
        event.update(extra)
        self.events.append(event)
        return event

    def as_list(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self.events]

    def __len__(self) -> int:
        return len(self.events)

    def __bool__(self) -> bool:
        # A log object always *exists*, even when empty. Without this, the
        # __len__ above would make an empty log falsy and idioms like
        # `history or HistoryLog()` would silently fork the audit trail.
        return True
