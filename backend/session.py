"""
Dispatch session: the one object the API layer talks to.

Person B's Lambda handlers construct a :class:`DispatchSession` from whatever
state store they use, call one method per endpoint, and serialise the result.
The session owns the shared world state (graph + hospitals) and wires the
routing engine to the simulation controllers so a Chaos Mode event injected
through ``/chaos/inject`` is visible to the very next ``/reroute`` call.

Endpoint -> method map:
    POST /emergencies     -> create_emergency
    POST /analyze         -> analyze
    POST /dispatch/confirm-> confirm_dispatch
    GET  /state           -> state
    POST /chaos/inject    -> inject_chaos
    POST /reroute         -> reroute
    POST /reroute/confirm -> confirm_reroute
    GET  /history         -> history_events
"""

from typing import Any, Dict, List, Optional

from .errors import EngineError, ErrorCode
from .history import EventType, HistoryLog
from .models.emergency import Emergency
from .models.hospital import Hospital
from .models.simulation_state import AmbulanceStatus
from .routing.engine import RoutingEngine
from .routing.graph import RoadGraph
from .routing.hospitals import load_hospitals
from .simulation.ambulance import AmbulanceSimulator
from .simulation.chaos import ChaosController
from .simulation.corridor import GreenCorridorController


class DispatchSession:
    """One emergency, one ambulance, one shared world state."""

    def __init__(
        self,
        graph: Optional[RoadGraph] = None,
        hospitals: Optional[Dict[str, Hospital]] = None,
        history: Optional[HistoryLog] = None,
        roads_path: Optional[str] = None,
        hospitals_path: Optional[str] = None,
    ) -> None:
        self.graph = graph or RoadGraph.from_files(roads_path)
        self.hospitals = hospitals if hospitals is not None else load_hospitals(hospitals_path)
        self.history = history if history is not None else HistoryLog()

        self.engine = RoutingEngine(
            graph=self.graph, hospitals=self.hospitals, history=self.history
        )
        self.ambulance = AmbulanceSimulator(self.graph, self.history)
        self.corridor = GreenCorridorController(self.graph, self.history)
        self.chaos = ChaosController(self.graph, self.hospitals, self.history)

        self.emergency: Optional[Emergency] = None
        self.current_analysis: Optional[Dict[str, Any]] = None
        self.active_route: Optional[Dict[str, Any]] = None
        self.pending_reroute: Optional[Dict[str, Any]] = None
        self.last_chaos_event: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # POST /emergencies
    # ------------------------------------------------------------------

    def create_emergency(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        emergency = Emergency.from_dict(payload)
        if not self.graph.has_node(emergency.origin_node):
            raise EngineError(
                ErrorCode.UNKNOWN_NODE,
                f"Origin node {emergency.origin_node!r} is not part of the road network.",
                node_id=emergency.origin_node,
            )
        self.emergency = emergency
        self.history.add(
            EventType.EMERGENCY_CREATED,
            f"Priority-{emergency.priority} emergency created at "
            f"{self.graph.node_name(emergency.origin_node)} "
            f"(requires {', '.join(emergency.requirements) or 'general care'}).",
            emergency_id=emergency.id,
            priority=emergency.priority,
            requirements=list(emergency.requirements),
        )
        return {"status": "ok", "emergency": emergency.to_dict()}

    def _require_emergency(self) -> Emergency:
        if self.emergency is None:
            raise EngineError(
                ErrorCode.INVALID_EMERGENCY,
                "No emergency has been created for this session.",
            )
        return self.emergency

    # ------------------------------------------------------------------
    # POST /analyze
    # ------------------------------------------------------------------

    def analyze(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Recommend a hospital + route. Accepts an inline emergency payload."""
        if payload and (payload.get("origin") or payload.get("origin_node")):
            self.create_emergency(payload)
        emergency = self._require_emergency()

        origin = self.ambulance.state.current_node if self.ambulance.state else None
        try:
            analysis = self.engine.analyze(emergency, origin=origin)
        except EngineError as error:
            # A dead end is a decision too: record it before surfacing it, so
            # the History panel shows why no dispatch happened.
            self.history.add(
                EventType.NO_FEASIBLE_OPTION,
                error.message,
                emergency_id=emergency.id,
                error_code=error.code,
            )
            raise
        self.current_analysis = analysis
        return analysis

    # ------------------------------------------------------------------
    # POST /dispatch/confirm
    # ------------------------------------------------------------------

    def confirm_dispatch(self, route_id: Optional[str] = None) -> Dict[str, Any]:
        """Dispatcher accepts a route: start the ambulance and the corridor."""
        if self.current_analysis is None:
            raise EngineError(
                ErrorCode.INVALID_REQUEST,
                "Call /analyze before confirming a dispatch.",
            )
        emergency = self._require_emergency()
        route = self._select_route(self.current_analysis["routes"], route_id)

        self.ambulance.dispatch(
            ambulance_id=emergency.ambulance_id,
            route_nodes=route["nodes"],
            destination_hospital_id=route["hospital_id"],
            route_id=route["route_id"],
        )
        self.active_route = route
        self.corridor.activate(route["nodes"], step=self.ambulance.state.step)
        self.corridor.sync(self.ambulance.state)

        return {
            "status": "ok",
            "confirmed_route": route,
            "ambulance": self.ambulance.to_dict(),
            "green_corridor": self.corridor.to_dict(),
        }

    @staticmethod
    def _select_route(routes: List[Dict[str, Any]], route_id: Optional[str]) -> Dict[str, Any]:
        if route_id is None:
            return routes[0]
        for route in routes:
            if route["route_id"] == route_id:
                return route
        raise EngineError(
            ErrorCode.INVALID_REQUEST,
            f"Route {route_id!r} is not one of the routes offered.",
            offered=[r["route_id"] for r in routes],
        )

    # ------------------------------------------------------------------
    # Simulation tick
    # ------------------------------------------------------------------

    def advance(self, steps: int = 1) -> Dict[str, Any]:
        """Move the ambulance forward *steps* junctions."""
        records = []
        for _ in range(max(1, steps)):
            record = self.ambulance.advance()
            records.append(record)
            self.corridor.sync(self.ambulance.state)
            if not record["moved"] or record["arrived"]:
                break
        return {
            "status": "ok",
            "movements": records,
            "ambulance": self.ambulance.to_dict(),
            "green_corridor": self.corridor.to_dict(),
        }

    # ------------------------------------------------------------------
    # POST /chaos/inject
    # ------------------------------------------------------------------

    def inject_chaos(self, payload: Any) -> Dict[str, Any]:
        """Apply a chaos event and report whether it hit the active route."""
        summary = self.chaos.inject(payload)
        self.last_chaos_event = summary

        affects_active_route = False
        if self.active_route and summary.get("road_id"):
            affects_active_route = summary["road_id"] in self.active_route["edges"]
        if self.active_route and summary.get("hospital_id"):
            affects_active_route = summary["hospital_id"] == self.active_route["hospital_id"]

        if affects_active_route and self.ambulance.state:
            self.ambulance.state.status = AmbulanceStatus.REROUTING

        return {
            "status": "ok",
            "event": summary,
            "affects_active_route": affects_active_route,
            "reroute_recommended": affects_active_route,
            "environment": self.chaos.to_dict(),
        }

    # ------------------------------------------------------------------
    # POST /reroute
    # ------------------------------------------------------------------

    def reroute(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Recalculate from the ambulance's current node under current conditions."""
        emergency = self._require_emergency()
        payload = payload or {}

        current_node = (
            payload.get("current_node")
            or (self.ambulance.state.current_node if self.ambulance.state else None)
            or emergency.origin_node
        )
        current_route = payload.get("current_route") or self.active_route
        trigger = payload.get("trigger") or self.last_chaos_event

        try:
            result = self.engine.reroute(
                emergency,
                current_node=current_node,
                current_route=current_route,
                trigger=trigger,
            )
        except EngineError as error:
            self.history.add(
                EventType.REROUTE_FAILED,
                error.message,
                emergency_id=emergency.id,
                current_node=current_node,
                error_code=error.code,
            )
            raise
        self.pending_reroute = result
        result["ambulance"] = self.ambulance.to_dict()
        result["green_corridor"] = self.corridor.to_dict()
        return result

    # ------------------------------------------------------------------
    # POST /reroute/confirm
    # ------------------------------------------------------------------

    def confirm_reroute(self, route_id: Optional[str] = None) -> Dict[str, Any]:
        """Dispatcher accepts the new route: re-point ambulance and corridor."""
        if self.pending_reroute is None:
            raise EngineError(
                ErrorCode.INVALID_REQUEST, "Call /reroute before confirming a reroute."
            )
        offered = [self.pending_reroute["new_route"]] + self.pending_reroute["alternatives"]
        route = self._select_route(offered, route_id)

        self.ambulance.assign_route(
            route["nodes"],
            destination_hospital_id=route["hospital_id"],
            route_id=route["route_id"],
        )
        self.active_route = route
        self.corridor.activate(route["nodes"], step=self.ambulance.state.step)
        self.corridor.sync(self.ambulance.state)

        self.history.add(
            EventType.REROUTE_CONFIRMED,
            f"Dispatcher confirmed reroute to {route['hospital_name']} via "
            + " -> ".join(route["node_names"])
            + f" (ETA {route['eta_minutes']} min).",
            route_id=route["route_id"],
            hospital_id=route["hospital_id"],
            eta_minutes=route["eta_minutes"],
        )
        self.pending_reroute = None

        return {
            "status": "ok",
            "confirmed_route": route,
            "ambulance": self.ambulance.to_dict(),
            "green_corridor": self.corridor.to_dict(),
            "updated_eta_minutes": route["eta_minutes"],
        }

    # ------------------------------------------------------------------
    # GET /state and GET /history
    # ------------------------------------------------------------------

    def state(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "emergency": self.emergency.to_dict() if self.emergency else None,
            "ambulance": self.ambulance.to_dict(),
            "green_corridor": self.corridor.to_dict(),
            "active_route": self.active_route,
            "environment": self.chaos.to_dict(),
            "hospitals": [self.hospitals[h].to_dict() for h in sorted(self.hospitals)],
        }

    def history_events(self) -> Dict[str, Any]:
        return {"status": "ok", "events": self.history.as_list()}
