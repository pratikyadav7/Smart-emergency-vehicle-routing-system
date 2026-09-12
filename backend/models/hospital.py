"""Hospital model plus the capability checks medical eligibility relies on."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from .. import config
from ..errors import EngineError, ErrorCode


@dataclass
class Hospital:
    """A destination facility with live-ish capability and capacity state."""

    id: str
    name: str
    node: str
    emergency_beds: int
    icu_available: bool
    trauma_available: bool
    cardiac_available: bool
    accepting: bool = True

    #: Requirement key -> attribute on this dataclass.
    CAPABILITY_ATTRS = {
        "icu": "icu_available",
        "trauma": "trauma_available",
        "cardiac": "cardiac_available",
    }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Hospital":
        try:
            return cls(
                id=raw["id"],
                name=raw.get("name", raw["id"]),
                node=raw["node"],
                emergency_beds=int(raw.get("emergency_beds", 0)),
                icu_available=bool(raw.get("icu_available", False)),
                trauma_available=bool(raw.get("trauma_available", False)),
                cardiac_available=bool(raw.get("cardiac_available", False)),
                accepting=bool(raw.get("accepting", True)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EngineError(
                ErrorCode.INVALID_REQUEST,
                f"Malformed hospital record: {raw!r}",
            ) from exc

    def has_capability(self, requirement: str) -> bool:
        attr = self.CAPABILITY_ATTRS.get(requirement)
        if attr is None:
            raise EngineError(
                ErrorCode.UNSUPPORTED_REQUIREMENT,
                f"Unsupported medical requirement {requirement!r}.",
                supported=sorted(self.CAPABILITY_ATTRS),
            )
        return bool(getattr(self, attr))

    def missing_capabilities(self, requirements: Iterable[str]) -> List[str]:
        return [r for r in requirements if not self.has_capability(r)]

    @property
    def available_capabilities(self) -> List[str]:
        return [key for key in sorted(self.CAPABILITY_ATTRS) if self.has_capability(key)]

    @property
    def has_capacity(self) -> bool:
        return self.emergency_beds >= config.MIN_REQUIRED_EMERGENCY_BEDS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "node": self.node,
            "emergency_beds": self.emergency_beds,
            "icu_available": self.icu_available,
            "trauma_available": self.trauma_available,
            "cardiac_available": self.cardiac_available,
            "accepting": self.accepting,
            "capabilities": self.available_capabilities,
        }
