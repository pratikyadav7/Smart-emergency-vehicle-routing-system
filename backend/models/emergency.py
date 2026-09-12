"""The emergency request, with defensive validation at the API boundary."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..errors import EngineError, ErrorCode

#: Medical requirements the engine understands. Anything else is rejected
#: rather than silently ignored - routing a patient on a misread requirement
#: is worse than refusing the request.
MEDICAL_REQUIREMENTS = ("icu", "trauma", "cardiac")

MIN_PRIORITY = 1
MAX_PRIORITY = 10


@dataclass
class Emergency:
    """A dispatcher-created emergency case."""

    id: str
    origin_node: str
    priority: int
    requirements: List[str] = field(default_factory=list)
    preferred_hospital_id: Optional[str] = None
    ambulance_id: str = "A01"
    description: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> "Emergency":
        if not isinstance(raw, dict):
            raise EngineError(
                ErrorCode.INVALID_EMERGENCY,
                "Emergency payload must be a JSON object.",
                received=type(raw).__name__,
            )

        origin = raw.get("origin_node") or raw.get("origin")
        if not origin:
            raise EngineError(
                ErrorCode.MISSING_ORIGIN,
                "Emergency is missing an origin node.",
            )

        raw_priority = raw.get("priority", 5)
        try:
            priority = int(raw_priority)
        except (TypeError, ValueError) as exc:
            raise EngineError(
                ErrorCode.INVALID_EMERGENCY,
                f"Priority {raw_priority!r} is not an integer.",
            ) from exc
        if not MIN_PRIORITY <= priority <= MAX_PRIORITY:
            raise EngineError(
                ErrorCode.INVALID_EMERGENCY,
                f"Priority must be between {MIN_PRIORITY} and {MAX_PRIORITY}, got {priority}.",
            )

        raw_requirements = raw.get("requirements", raw.get("needs", []))
        if isinstance(raw_requirements, str):
            raw_requirements = [raw_requirements]
        if not isinstance(raw_requirements, (list, tuple, set)):
            raise EngineError(
                ErrorCode.INVALID_EMERGENCY,
                "'requirements' must be a list of medical requirement strings.",
            )

        requirements: List[str] = []
        for item in raw_requirements:
            key = str(item).strip().lower()
            if key not in MEDICAL_REQUIREMENTS:
                raise EngineError(
                    ErrorCode.UNSUPPORTED_REQUIREMENT,
                    f"Unsupported medical requirement {item!r}.",
                    supported=list(MEDICAL_REQUIREMENTS),
                )
            if key not in requirements:
                requirements.append(key)
        # Deterministic ordering keeps explanations and JSON stable.
        requirements.sort(key=MEDICAL_REQUIREMENTS.index)

        return cls(
            id=str(raw.get("id") or raw.get("emergency_id") or "E001"),
            origin_node=str(origin),
            priority=priority,
            requirements=requirements,
            preferred_hospital_id=raw.get("preferred_hospital_id") or raw.get("preferred_hospital"),
            ambulance_id=str(raw.get("ambulance_id", "A01")),
            description=str(raw.get("description", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "origin_node": self.origin_node,
            "priority": self.priority,
            "requirements": list(self.requirements),
            "preferred_hospital_id": self.preferred_hospital_id,
            "ambulance_id": self.ambulance_id,
            "description": self.description,
        }
