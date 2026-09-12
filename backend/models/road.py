"""Road-graph primitives: junctions (nodes) and roads (edges)."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..errors import ErrorCode, EngineError
from .incident import Incident


class RoadStatus:
    OPEN = "open"
    CLOSED = "closed"


class TrafficLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    ALL = (LOW, MEDIUM, HIGH)


@dataclass
class Node:
    """A junction / landmark in the synthetic city graph."""

    id: str
    name: str
    lat: float
    lon: float

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Node":
        try:
            return cls(id=raw["id"], name=raw.get("name", raw["id"]),
                       lat=float(raw["lat"]), lon=float(raw["lon"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise EngineError(
                ErrorCode.INVALID_REQUEST,
                f"Malformed node record in road data: {raw!r}",
            ) from exc

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "lat": self.lat, "lon": self.lon}


@dataclass
class Road:
    """A directed-usable, physically bidirectional road segment.

    ``distance_km`` is derived from the endpoint coordinates by the graph at
    load time, so the data file only has to carry the attributes a dispatcher
    would realistically know about.
    """

    id: str
    from_node: str
    to_node: str
    name: str
    speed_kmph: float
    capacity: str
    traffic: str
    safety: float
    status: str = RoadStatus.OPEN
    distance_km: float = 0.0
    incident: Optional[Incident] = None
    #: Traffic level before any chaos event touched this road, so a spike can
    #: be described ("medium -> high") and cleared without guessing.
    baseline_traffic: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.baseline_traffic:
            self.baseline_traffic = self.traffic

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Road":
        try:
            return cls(
                id=raw["id"],
                from_node=raw["from"],
                to_node=raw["to"],
                name=raw.get("name", raw["id"]),
                speed_kmph=float(raw["speed_kmph"]),
                capacity=raw.get("capacity", "medium"),
                traffic=raw.get("traffic", TrafficLevel.LOW),
                safety=float(raw.get("safety", 75)),
                status=raw.get("status", RoadStatus.OPEN),
                incident=Incident.from_dict(raw["incident"]) if raw.get("incident") else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EngineError(
                ErrorCode.INVALID_REQUEST,
                f"Malformed road record in road data: {raw!r}",
            ) from exc

    @property
    def is_open(self) -> bool:
        return self.status == RoadStatus.OPEN

    @property
    def has_incident(self) -> bool:
        return self.incident is not None and self.incident.active

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from": self.from_node,
            "to": self.to_node,
            "name": self.name,
            "speed_kmph": self.speed_kmph,
            "capacity": self.capacity,
            "traffic": self.traffic,
            "safety": self.safety,
            "status": self.status,
            "distance_km": round(self.distance_km, 2),
            "incident": self.incident.to_dict() if self.incident else None,
        }
