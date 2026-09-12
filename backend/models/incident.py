"""Incidents and the Chaos Mode events that create them."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .. import config
from ..errors import EngineError, ErrorCode


class ChaosEventType:
    ACCIDENT = "ACCIDENT"
    ROAD_CLOSURE = "ROAD_CLOSURE"
    TRAFFIC_SPIKE = "TRAFFIC_SPIKE"
    HOSPITAL_CAPACITY = "HOSPITAL_CAPACITY"

    ROAD_EVENTS = (ACCIDENT, ROAD_CLOSURE, TRAFFIC_SPIKE)
    HOSPITAL_EVENTS = (HOSPITAL_CAPACITY,)
    ALL = ROAD_EVENTS + HOSPITAL_EVENTS


@dataclass
class Incident:
    """An active disruption attached to a road."""

    type: str
    severity: str = config.DEFAULT_INCIDENT_SEVERITY
    description: str = ""
    active: bool = True

    @property
    def delay_minutes(self) -> float:
        return config.INCIDENT_DELAY_MINUTES.get(
            self.severity, config.INCIDENT_DELAY_MINUTES[config.DEFAULT_INCIDENT_SEVERITY]
        )

    @property
    def score_penalty(self) -> float:
        return config.INCIDENT_SEVERITY_PENALTY.get(
            self.severity, config.INCIDENT_SEVERITY_PENALTY[config.DEFAULT_INCIDENT_SEVERITY]
        )

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Incident":
        return cls(
            type=raw.get("type", "incident"),
            severity=raw.get("severity", config.DEFAULT_INCIDENT_SEVERITY),
            description=raw.get("description", ""),
            active=bool(raw.get("active", True)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "description": self.description,
            "active": self.active,
            "delay_minutes": self.delay_minutes,
        }


@dataclass
class ChaosEvent:
    """A validated Chaos Mode instruction from ``POST /chaos/inject``."""

    type: str
    road_id: Optional[str] = None
    hospital_id: Optional[str] = None
    severity: str = config.DEFAULT_INCIDENT_SEVERITY
    emergency_beds: Optional[int] = None
    accepting: Optional[bool] = None
    description: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> "ChaosEvent":
        """Parse and validate. Raises :class:`EngineError` on malformed input."""
        if not isinstance(raw, dict):
            raise EngineError(
                ErrorCode.INVALID_CHAOS_EVENT,
                "Chaos event must be a JSON object.",
                received=type(raw).__name__,
            )

        event_type = str(raw.get("type", "")).upper().strip()
        if event_type not in ChaosEventType.ALL:
            raise EngineError(
                ErrorCode.INVALID_CHAOS_EVENT,
                f"Unsupported chaos event type {raw.get('type')!r}.",
                supported=list(ChaosEventType.ALL),
            )

        road_id = raw.get("road_id") or raw.get("edge_id")
        hospital_id = raw.get("hospital_id")

        if event_type in ChaosEventType.ROAD_EVENTS and not road_id:
            raise EngineError(
                ErrorCode.INVALID_CHAOS_EVENT,
                f"{event_type} requires a 'road_id'.",
                event_type=event_type,
            )
        if event_type in ChaosEventType.HOSPITAL_EVENTS and not hospital_id:
            raise EngineError(
                ErrorCode.INVALID_CHAOS_EVENT,
                f"{event_type} requires a 'hospital_id'.",
                event_type=event_type,
            )

        severity = str(raw.get("severity", config.DEFAULT_INCIDENT_SEVERITY)).lower()
        if severity not in config.INCIDENT_DELAY_MINUTES:
            raise EngineError(
                ErrorCode.INVALID_CHAOS_EVENT,
                f"Unknown severity {raw.get('severity')!r}.",
                supported=sorted(config.INCIDENT_DELAY_MINUTES),
            )

        beds = raw.get("emergency_beds")
        if beds is not None:
            try:
                beds = int(beds)
            except (TypeError, ValueError) as exc:
                raise EngineError(
                    ErrorCode.INVALID_CHAOS_EVENT,
                    "'emergency_beds' must be an integer.",
                ) from exc
            if beds < 0:
                raise EngineError(
                    ErrorCode.INVALID_CHAOS_EVENT,
                    "'emergency_beds' cannot be negative.",
                )

        accepting = raw.get("accepting")
        if accepting is not None:
            accepting = bool(accepting)

        return cls(
            type=event_type,
            road_id=road_id,
            hospital_id=hospital_id,
            severity=severity,
            emergency_beds=beds,
            accepting=accepting,
            description=str(raw.get("description", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "road_id": self.road_id,
            "hospital_id": self.hospital_id,
            "severity": self.severity,
            "emergency_beds": self.emergency_beds,
            "accepting": self.accepting,
            "description": self.description,
        }
