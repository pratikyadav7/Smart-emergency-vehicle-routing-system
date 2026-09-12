"""
Simulated green corridor.

This models *requested* signal priority for a demonstration. It does not
connect to, and makes no claim to control, any real traffic infrastructure -
:attr:`GreenCorridorState.simulated` is always ``True`` and the serialised
state carries that disclaimer to the frontend.

Behaviour: junctions on the remaining route are held at PRIORITY_GRANTED; a
junction the ambulance has already cleared returns to CLEARED, and junctions
dropped by a reroute return to NORMAL.
"""

from typing import Dict, Iterable, List, Optional

from ..history import EventType, HistoryLog
from ..models.simulation_state import (
    AmbulanceState,
    GreenCorridorState,
    JunctionSignal,
    SignalState,
)
from ..routing.graph import RoadGraph


class GreenCorridorController:
    """Owns the signal state of every junction on the active route."""

    def __init__(self, graph: RoadGraph, history: Optional[HistoryLog] = None) -> None:
        self.graph = graph
        self.history = history if history is not None else HistoryLog()
        self.state = GreenCorridorState()
        self._signals: Dict[str, JunctionSignal] = {}

    # -- lifecycle -----------------------------------------------------

    def activate(self, route_nodes: Iterable[str], step: int = 0) -> GreenCorridorState:
        """Request priority for every junction on the route, in travel order."""
        nodes = list(route_nodes)
        self._signals = {
            node_id: JunctionSignal(
                node_id=node_id,
                node_name=self.graph.node_name(node_id),
                state=SignalState.PRIORITY_GRANTED,
                granted_at_step=step,
            )
            for node_id in nodes
        }
        self.state = GreenCorridorState(
            active=bool(nodes), junctions=[self._signals[n] for n in nodes]
        )
        if nodes:
            self.history.add(
                EventType.CORRIDOR_GRANTED,
                "Simulated signal priority granted at "
                + ", ".join(self.graph.node_name(n) for n in nodes)
                + ".",
                nodes=nodes,
            )
        return self.state

    def deactivate(self) -> GreenCorridorState:
        for signal in self._signals.values():
            signal.state = SignalState.NORMAL
        self.state.active = False
        return self.state

    # -- progression ---------------------------------------------------

    def sync(self, ambulance: AmbulanceState) -> GreenCorridorState:
        """Re-derive signal states from where the ambulance actually is."""
        remaining = set(ambulance.remaining_nodes)
        cleared: List[str] = []

        for node_id, signal in self._signals.items():
            if node_id in remaining:
                if signal.state != SignalState.PRIORITY_GRANTED:
                    signal.state = SignalState.PRIORITY_GRANTED
                    signal.granted_at_step = ambulance.step
            elif signal.state == SignalState.PRIORITY_GRANTED:
                signal.state = SignalState.CLEARED
                cleared.append(node_id)

        if cleared:
            self.history.add(
                EventType.CORRIDOR_RELEASED,
                "Simulated signal priority released at "
                + ", ".join(self.graph.node_name(n) for n in cleared)
                + ".",
                nodes=cleared,
            )

        if ambulance.has_arrived:
            self.state.active = False
        return self.state

    def to_dict(self) -> Dict[str, object]:
        return self.state.to_dict()
