"""
Deterministic ambulance movement.

The ambulance advances one junction per :meth:`AmbulanceSimulator.advance`
call along its assigned route - it is a controlled demonstration, not GPS
tracking. Elapsed time and remaining ETA are computed from the live graph, so
a traffic spike injected mid-transit changes the remaining ETA of the
segments still ahead.
"""

from typing import Any, Dict, List, Optional

from ..errors import EngineError, ErrorCode
from ..history import EventType, HistoryLog
from ..models.simulation_state import AmbulanceState, AmbulanceStatus
from ..routing.graph import RoadGraph


class AmbulanceSimulator:
    """Moves one ambulance node-by-node along a route."""

    def __init__(self, graph: RoadGraph, history: Optional[HistoryLog] = None) -> None:
        self.graph = graph
        self.history = history if history is not None else HistoryLog()
        self.state: Optional[AmbulanceState] = None

    # -- lifecycle -----------------------------------------------------

    def dispatch(
        self,
        ambulance_id: str,
        route_nodes: List[str],
        destination_hospital_id: Optional[str] = None,
        route_id: Optional[str] = None,
    ) -> AmbulanceState:
        """Put an ambulance at the start of *route_nodes* and mark it en route."""
        if len(route_nodes) < 1:
            raise EngineError(
                ErrorCode.NO_FEASIBLE_ROUTE, "Cannot dispatch an ambulance without a route."
            )
        for node_id in route_nodes:
            self.graph.node(node_id)  # validates, raises UNKNOWN_NODE

        self.state = AmbulanceState(
            ambulance_id=ambulance_id,
            origin_node=route_nodes[0],
            destination_node=route_nodes[-1],
            destination_hospital_id=destination_hospital_id,
            route_id=route_id,
            route_nodes=list(route_nodes),
            current_index=0,
            status=AmbulanceStatus.EN_ROUTE if len(route_nodes) > 1 else AmbulanceStatus.ARRIVED,
        )
        self.state.total_eta_min = self.remaining_eta()
        self.state.remaining_eta_min = self.state.total_eta_min

        self.history.add(
            EventType.DISPATCH_CONFIRMED,
            f"Ambulance {ambulance_id} dispatched: "
            + " -> ".join(self.graph.node_name(n) for n in route_nodes)
            + f" (ETA {round(self.state.total_eta_min, 1)} min).",
            ambulance_id=ambulance_id,
            route=list(route_nodes),
            eta_minutes=round(self.state.total_eta_min, 2),
        )
        return self.state

    def _require_state(self) -> AmbulanceState:
        if self.state is None:
            raise EngineError(
                ErrorCode.SIMULATION_NOT_STARTED,
                "No ambulance has been dispatched yet.",
            )
        return self.state

    # -- movement ------------------------------------------------------

    def remaining_eta(self) -> float:
        """Minutes left, priced against the graph as it is *right now*."""
        state = self._require_state()
        total = 0.0
        for a, b in zip(state.remaining_nodes, state.remaining_nodes[1:]):
            road = self.graph.road_between(a, b)
            if road is None:
                raise EngineError(
                    ErrorCode.NO_FEASIBLE_ROUTE,
                    f"No road connects {a} to {b} on the assigned route.",
                    from_node=a,
                    to_node=b,
                )
            total += self.graph.travel_time_min(road)
        return total

    def advance(self) -> Dict[str, Any]:
        """Move one junction forward and return a movement record."""
        state = self._require_state()
        if state.has_arrived:
            state.status = AmbulanceStatus.ARRIVED
            return {"moved": False, "arrived": True, "ambulance": state.to_dict()}

        origin_node = state.current_node
        next_node = state.next_node
        road = self.graph.road_between(origin_node, next_node)
        if road is None or not road.is_open:
            state.status = AmbulanceStatus.BLOCKED
            raise EngineError(
                ErrorCode.NO_FEASIBLE_ROUTE,
                f"The road from {self.graph.node_name(origin_node)} to "
                f"{self.graph.node_name(next_node)} is not passable; a reroute is required.",
                from_node=origin_node,
                to_node=next_node,
            )

        segment_min = self.graph.travel_time_min(road)
        state.current_index += 1
        state.step += 1
        state.elapsed_min += segment_min
        state.remaining_eta_min = self.remaining_eta()
        state.status = (
            AmbulanceStatus.ARRIVED if state.has_arrived else AmbulanceStatus.EN_ROUTE
        )

        record = {
            "moved": True,
            "arrived": state.has_arrived,
            "step": state.step,
            "from_node": origin_node,
            "from_name": self.graph.node_name(origin_node),
            "to_node": next_node,
            "to_name": self.graph.node_name(next_node),
            "road_id": road.id,
            "road_name": road.name,
            "segment_minutes": round(segment_min, 2),
            "elapsed_min": round(state.elapsed_min, 2),
            "remaining_eta_min": round(state.remaining_eta_min, 2),
            "ambulance": state.to_dict(),
        }

        self.history.add(
            EventType.AMBULANCE_MOVED,
            f"Ambulance {state.ambulance_id} reached "
            f"{self.graph.node_name(next_node)} via {road.name} "
            f"(+{round(segment_min, 1)} min, {round(state.remaining_eta_min, 1)} min remaining).",
            ambulance_id=state.ambulance_id,
            node=next_node,
            road_id=road.id,
            elapsed_min=round(state.elapsed_min, 2),
            remaining_eta_min=round(state.remaining_eta_min, 2),
        )

        if state.has_arrived:
            self.history.add(
                EventType.ARRIVED,
                f"Ambulance {state.ambulance_id} arrived at "
                f"{self.graph.node_name(state.destination_node)} after "
                f"{round(state.elapsed_min, 1)} min.",
                ambulance_id=state.ambulance_id,
                node=state.destination_node,
                elapsed_min=round(state.elapsed_min, 2),
            )
        return record

    # -- rerouting -----------------------------------------------------

    def assign_route(
        self,
        route_nodes: List[str],
        destination_hospital_id: Optional[str] = None,
        route_id: Optional[str] = None,
    ) -> AmbulanceState:
        """Swap in a new route that must start at the current position."""
        state = self._require_state()
        if not route_nodes or route_nodes[0] != state.current_node:
            raise EngineError(
                ErrorCode.NO_FEASIBLE_ROUTE,
                "A replacement route must start at the ambulance's current node.",
                current_node=state.current_node,
                proposed_start=route_nodes[0] if route_nodes else None,
            )

        state.route_nodes = list(route_nodes)
        state.current_index = 0
        state.destination_node = route_nodes[-1]
        state.destination_hospital_id = destination_hospital_id or state.destination_hospital_id
        state.route_id = route_id or state.route_id
        state.reroute_count += 1
        state.remaining_eta_min = self.remaining_eta()
        state.total_eta_min = state.elapsed_min + state.remaining_eta_min
        state.status = (
            AmbulanceStatus.ARRIVED if state.has_arrived else AmbulanceStatus.EN_ROUTE
        )
        return state

    def to_dict(self) -> Dict[str, Any]:
        return self.state.to_dict() if self.state else {"status": AmbulanceStatus.IDLE}
