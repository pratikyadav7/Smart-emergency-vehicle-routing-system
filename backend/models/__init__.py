"""Domain models shared by the routing engine and the simulation layer."""

from .emergency import Emergency, MEDICAL_REQUIREMENTS
from .hospital import Hospital
from .incident import ChaosEvent, ChaosEventType, Incident
from .road import Node, Road, RoadStatus, TrafficLevel
from .simulation_state import (
    AmbulanceState,
    AmbulanceStatus,
    GreenCorridorState,
    JunctionSignal,
    SignalState,
)

__all__ = [
    "AmbulanceState",
    "AmbulanceStatus",
    "ChaosEvent",
    "ChaosEventType",
    "Emergency",
    "GreenCorridorState",
    "Hospital",
    "Incident",
    "JunctionSignal",
    "MEDICAL_REQUIREMENTS",
    "Node",
    "Road",
    "RoadStatus",
    "SignalState",
    "TrafficLevel",
]
