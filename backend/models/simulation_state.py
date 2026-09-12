"""Ambulance and green-corridor state exposed to the frontend."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class AmbulanceStatus:
    IDLE = "IDLE"
    EN_ROUTE = "EN_ROUTE"
    REROUTING = "REROUTING"
    ARRIVED = "ARRIVED"
    BLOCKED = "BLOCKED"


class SignalState:
    """Simulated signal state at a junction. Not connected to real hardware."""

    NORMAL = "NORMAL"
    PRIORITY_GRANTED = "PRIORITY_GRANTED"
    CLEARED = "CLEARED"


@dataclass
class JunctionSignal:
    node_id: str
    node_name: str
    state: str = SignalState.NORMAL
    granted_at_step: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "state": self.state,
            "granted_at_step": self.granted_at_step,
            "priority_granted": self.state == SignalState.PRIORITY_GRANTED,
        }


@dataclass
class GreenCorridorState:
    """Which junctions along the active route currently hold signal priority."""

    active: bool = False
    simulated: bool = True  # never claim control of real traffic infrastructure
    junctions: List[JunctionSignal] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "simulated": self.simulated,
            "note": "Simulated signal priority. No real traffic infrastructure is controlled.",
            "junctions": [j.to_dict() for j in self.junctions],
            "priority_nodes": [
                j.node_id for j in self.junctions if j.state == SignalState.PRIORITY_GRANTED
            ],
        }


@dataclass
class AmbulanceState:
    """Deterministic node-by-node position of a dispatched ambulance."""

    ambulance_id: str
    origin_node: str
    destination_node: str
    destination_hospital_id: Optional[str] = None
    route_id: Optional[str] = None
    route_nodes: List[str] = field(default_factory=list)
    current_index: int = 0
    status: str = AmbulanceStatus.IDLE
    elapsed_min: float = 0.0
    remaining_eta_min: float = 0.0
    total_eta_min: float = 0.0
    step: int = 0
    reroute_count: int = 0

    @property
    def current_node(self) -> str:
        if not self.route_nodes:
            return self.origin_node
        return self.route_nodes[min(self.current_index, len(self.route_nodes) - 1)]

    @property
    def next_node(self) -> Optional[str]:
        nxt = self.current_index + 1
        if nxt < len(self.route_nodes):
            return self.route_nodes[nxt]
        return None

    @property
    def remaining_nodes(self) -> List[str]:
        return list(self.route_nodes[self.current_index:])

    @property
    def has_arrived(self) -> bool:
        return bool(self.route_nodes) and self.current_index >= len(self.route_nodes) - 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ambulance_id": self.ambulance_id,
            "status": self.status,
            "origin_node": self.origin_node,
            "current_node": self.current_node,
            "next_junction": self.next_node,
            "destination_node": self.destination_node,
            "destination_hospital_id": self.destination_hospital_id,
            "route_id": self.route_id,
            "route": list(self.route_nodes),
            "remaining_route": self.remaining_nodes,
            "current_route_index": self.current_index,
            "step": self.step,
            "elapsed_min": round(self.elapsed_min, 2),
            "remaining_eta_min": round(self.remaining_eta_min, 2),
            "total_eta_min": round(self.total_eta_min, 2),
            "reroute_count": self.reroute_count,
            "arrived": self.has_arrived,
        }
