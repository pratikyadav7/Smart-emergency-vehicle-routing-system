"""
Emergency Green-Corridor Planner - routing & recommendation engine.

Person C deliverable. Owns the road graph, route generation, joint
hospital-route scoring, and the recalculation that powers dynamic rerouting.

Design rules:
  * Deterministic. No randomness, no ML - the same world state always yields
    the same recommendation, which is what makes it explainable and testable.
  * Never invents a destination or a route. Failure states are explicit
    :class:`~backend.errors.EngineError` values, not fabricated data.
  * Returns plain JSON-safe dicts, so Person A (frontend) and Person B (AWS)
    depend on a contract, not on these classes.

Both ``POST /analyze`` and ``POST /reroute`` are served by the same
:meth:`RoutingEngine.recommend_candidates` core; ``reroute`` simply re-runs it
from the ambulance's current node against the mutated world state.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .. import config
from ..errors import EngineError, ErrorCode
from ..history import EventType, HistoryLog
from ..models.emergency import Emergency
from ..models.hospital import Hospital
from .algorithms import Path, dijkstra, k_alternative_paths
from .explanations import (
    explain_alternative,
    explain_hospital,
    explain_preference_override,
    explain_reroute,
    explain_route,
)
from .graph import RoadGraph
from .hospitals import (
    EligibilityResult,
    evaluate_eligibility,
    load_hospitals,
    validate_preferred_hospital,
)
from .scoring import RouteMetrics, ScoreBreakdown, compute_route_metrics, score_candidate


@dataclass
class Candidate:
    """One (hospital, route) pair with its metrics, score and explanation."""

    hospital: Hospital
    path: Path
    metrics: RouteMetrics
    breakdown: ScoreBreakdown
    route_id: str
    node_names: List[str]

    def sort_key(self):
        """Deterministic ranking: score desc, then ETA asc, then stable ids."""
        return (
            -round(self.breakdown.total, 6),
            round(self.metrics.eta_min, 6),
            self.hospital.id,
            tuple(self.path.road_ids),
        )

    def to_dict(self, recommended: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "route_id": self.route_id,
            "hospital_id": self.hospital.id,
            "hospital_name": self.hospital.name,
            "nodes": list(self.path.nodes),
            "node_names": list(self.node_names),
            "edges": list(self.path.road_ids),
            "score": round(self.breakdown.total, config.ROUND_DIGITS),
            "score_breakdown": self.breakdown.to_dict(),
            "recommended": recommended,
        }
        payload.update(self.metrics.to_dict())
        return payload


class RoutingEngine:
    """Stateless-per-call recommendation engine over a mutable world state."""

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

    # ------------------------------------------------------------------
    # Hospital shortlisting (Dijkstra)
    # ------------------------------------------------------------------

    def shortlist_hospitals(
        self,
        origin: str,
        eligible: Iterable[Hospital],
        limit: int = config.HOSPITAL_SHORTLIST_SIZE,
    ) -> List[Hospital]:
        """Rank medically eligible hospitals by reachable travel time.

        One Dijkstra sweep prices every destination in the network at once,
        which is why it is the right tool for shortlisting; A* then computes
        the actual path to the destinations that survive.
        """
        distances, _ = dijkstra(self.graph, origin)
        reachable = [h for h in eligible if h.node in distances]
        reachable.sort(key=lambda h: (round(distances[h.node], 6), h.id))
        return reachable[:limit]

    # ------------------------------------------------------------------
    # Candidate generation + joint scoring
    # ------------------------------------------------------------------

    def _build_candidates(
        self,
        origin: str,
        emergency: Emergency,
        hospitals: Iterable[Hospital],
        exclude_roads: Optional[Iterable[str]] = None,
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        for hospital in hospitals:
            paths = k_alternative_paths(
                self.graph,
                origin,
                hospital.node,
                k=config.MAX_ROUTES_PER_HOSPITAL,
                blocked_roads=exclude_roads,
            )
            for index, path in enumerate(paths, start=1):
                metrics = compute_route_metrics(self.graph, path)
                breakdown = score_candidate(hospital, metrics, emergency)
                candidates.append(
                    Candidate(
                        hospital=hospital,
                        path=path,
                        metrics=metrics,
                        breakdown=breakdown,
                        route_id=f"R-{hospital.id}-{index}",
                        node_names=[self.graph.node_name(n) for n in path.nodes],
                    )
                )
        candidates.sort(key=Candidate.sort_key)
        return candidates

    def recommend_candidates(
        self,
        emergency: Emergency,
        origin: Optional[str] = None,
        exclude_roads: Optional[Iterable[str]] = None,
        limit: int = config.MAX_CANDIDATE_ROUTES,
    ) -> Dict[str, Any]:
        """Core pipeline shared by ``/analyze`` and ``/reroute``.

        validate -> medical eligibility -> Dijkstra shortlist -> A* routes ->
        joint scoring -> ranking. Raises :class:`EngineError` rather than
        returning an empty or invented recommendation.
        """
        origin = origin or emergency.origin_node
        if not self.graph.has_node(origin):
            raise EngineError(
                ErrorCode.UNKNOWN_NODE,
                f"Origin node {origin!r} is not part of the road network.",
                node_id=origin,
            )
        validate_preferred_hospital(self.hospitals, emergency)

        eligibility = evaluate_eligibility(self.hospitals.values(), emergency)
        if not eligibility.has_eligible:
            raise EngineError(
                ErrorCode.NO_ELIGIBLE_HOSPITAL,
                "No hospital currently meets the required medical capabilities.",
                requirements=list(emergency.requirements),
                rejected=eligibility.rejected,
            )

        shortlist = self.shortlist_hospitals(origin, eligibility.eligible)
        if not shortlist:
            raise EngineError(
                ErrorCode.NO_FEASIBLE_ROUTE,
                "No medically suitable hospital is reachable from the current position.",
                origin=origin,
                eligible=[h.id for h in eligibility.eligible],
            )

        candidates = self._build_candidates(origin, emergency, shortlist, exclude_roads)
        if not candidates:
            raise EngineError(
                ErrorCode.NO_FEASIBLE_ROUTE,
                "Every route to a suitable hospital is currently closed or blocked.",
                origin=origin,
                closed_roads=self.graph.closed_roads(),
            )

        return {
            "eligibility": eligibility,
            "candidates": candidates[:limit],
            "all_candidates": candidates,
            "origin": origin,
        }

    # ------------------------------------------------------------------
    # POST /analyze
    # ------------------------------------------------------------------

    def analyze(
        self,
        emergency: Emergency,
        origin: Optional[str] = None,
        log: bool = True,
    ) -> Dict[str, Any]:
        """Full recommendation payload for ``POST /analyze`` (JSON-safe)."""
        result = self.recommend_candidates(emergency, origin=origin)
        eligibility: EligibilityResult = result["eligibility"]
        candidates: List[Candidate] = result["candidates"]

        best = candidates[0]
        alternatives = candidates[1:]

        recommended_route = best.to_dict(recommended=True)
        alternative_routes = [c.to_dict() for c in alternatives]

        warning = explain_preference_override(eligibility.preferred_rejected)
        if warning and log:
            self.history.add(
                EventType.HOSPITAL_REJECTED,
                warning,
                hospital_id=emergency.preferred_hospital_id,
            )

        why_not = {
            alt["route_id"]: explain_alternative(alt, recommended_route)
            for alt in alternative_routes
        }

        payload = {
            "status": "ok",
            "emergency": emergency.to_dict(),
            "origin_node": result["origin"],
            "hospital": best.hospital.to_dict(),
            "recommended_route": recommended_route,
            "alternatives": alternative_routes,
            "routes": [recommended_route] + alternative_routes,
            "eligibility": {
                "eligible_hospitals": [h.to_dict() for h in eligibility.eligible],
                "rejected_hospitals": eligibility.rejected,
                "preferred_hospital_used": (
                    emergency.preferred_hospital_id == best.hospital.id
                    if emergency.preferred_hospital_id
                    else None
                ),
            },
            "reasons": {
                "why_this_hospital": explain_hospital(best.hospital, emergency),
                "why_this_route": explain_route(
                    best.metrics, best.breakdown, best.node_names
                ),
                "why_not_alternatives": why_not,
                "rejected_hospitals": [r["detail"] for r in eligibility.rejected],
                "warning": warning,
            },
            "environment": {
                "closed_roads": self.graph.closed_roads(),
                "active_incidents": self.graph.active_incidents(),
            },
        }

        if log:
            self.history.add(
                EventType.RECOMMENDATION,
                f"Recommended {best.hospital.name} via {' -> '.join(best.node_names)} "
                f"(score {recommended_route['score']}, ETA {recommended_route['eta_minutes']} min).",
                emergency_id=emergency.id,
                hospital_id=best.hospital.id,
                route_id=best.route_id,
                eta_minutes=recommended_route["eta_minutes"],
                score=recommended_route["score"],
            )
        return payload

    # ------------------------------------------------------------------
    # POST /reroute
    # ------------------------------------------------------------------

    def reroute(
        self,
        emergency: Emergency,
        current_node: str,
        current_route: Optional[Dict[str, Any]] = None,
        trigger: Optional[Dict[str, Any]] = None,
        log: bool = True,
    ) -> Dict[str, Any]:
        """Recalculate from the ambulance's *current* position and world state.

        This is a genuine re-run of the same pipeline against the mutated
        graph - there is no "if accident then take route 3" shortcut anywhere.
        The previous route is re-measured under current conditions so the
        before/after comparison is honest.
        """
        analysis = self.analyze(emergency, origin=current_node, log=False)
        new_route = analysis["recommended_route"]

        # Compare like with like: the old plan's *remaining* leg from where the
        # ambulance actually is, not the whole route it started on.
        remaining_old = self._remaining_route(current_route, current_node)
        old_route = self._remeasure(remaining_old, emergency) if remaining_old else None
        old_eta = old_route["eta_minutes"] if old_route else None

        destination_changed = bool(
            current_route
            and current_route.get("hospital_id")
            and current_route["hospital_id"] != new_route["hospital_id"]
        )
        route_changed = bool(
            old_route is None or old_route.get("edges") != new_route["edges"]
        )

        explanation = (
            explain_reroute(
                old_route or new_route,
                new_route,
                trigger,
                destination_changed,
                analysis["hospital"]["name"],
            )
            if route_changed
            else (
                "Conditions changed but the current route is still the best available option; "
                f"ETA is now {new_route['eta_minutes']} minutes."
            )
        )

        payload = {
            "status": "ok",
            "rerouted": route_changed,
            "destination_changed": destination_changed,
            "from_node": current_node,
            "old_route": old_route,
            "new_route": new_route,
            "recommended_route": new_route,
            "alternatives": analysis["alternatives"],
            "hospital": analysis["hospital"],
            "old_eta_minutes": old_eta,
            "new_eta_minutes": new_route["eta_minutes"],
            "eta_delta_minutes": (
                round(new_route["eta_minutes"] - old_eta, config.ROUND_DIGITS)
                if old_eta is not None
                else None
            ),
            "trigger": trigger,
            "changed_conditions": {
                "closed_roads": self.graph.closed_roads(),
                "active_incidents": self.graph.active_incidents(),
            },
            "reasons": {
                "why_reroute": explanation,
                "why_this_hospital": analysis["reasons"]["why_this_hospital"],
                "why_this_route": analysis["reasons"]["why_this_route"],
                "why_not_alternatives": analysis["reasons"]["why_not_alternatives"],
            },
        }

        if log:
            self.history.add(
                EventType.REROUTE_PROPOSED if route_changed else EventType.RECOMMENDATION,
                explanation,
                emergency_id=emergency.id,
                hospital_id=analysis["hospital"]["id"],
                route_id=new_route["route_id"],
                old_eta_minutes=old_eta,
                new_eta_minutes=new_route["eta_minutes"],
            )
        return payload

    @staticmethod
    def _remaining_route(
        route: Optional[Dict[str, Any]], current_node: str
    ) -> Optional[Dict[str, Any]]:
        """Trim a route to the leg the ambulance has not driven yet.

        Returns ``None`` when the ambulance is not on the route at all (for
        example after an earlier reroute), in which case there is no honest
        before/after comparison to make.
        """
        if not route:
            return None
        nodes = list(route.get("nodes") or [])
        road_ids = list(route.get("edges") or route.get("roads") or [])
        if current_node not in nodes:
            return None
        index = nodes.index(current_node)
        if index >= len(nodes) - 1:
            return None  # already at the destination of the old route
        return {
            **route,
            "nodes": nodes[index:],
            "edges": road_ids[index:],
        }

    def _remeasure(
        self, route: Dict[str, Any], emergency: Emergency
    ) -> Optional[Dict[str, Any]]:
        """Re-price a previously recommended route under current conditions.

        Returns ``None`` when the old route is no longer traversable, which is
        itself the answer: a closed road makes the old route infeasible.
        """
        road_ids = list(route.get("edges") or route.get("roads") or [])
        nodes = list(route.get("nodes") or [])
        if not road_ids or not nodes:
            return None
        try:
            roads = [self.graph.road(rid) for rid in road_ids]
        except EngineError:
            return None
        if any(not r.is_open for r in roads):
            return {
                "route_id": route.get("route_id"),
                "nodes": nodes,
                "edges": road_ids,
                "feasible": False,
                "eta_minutes": None,
                "reason": "One or more roads on this route are closed.",
            }

        path = Path(
            nodes=nodes,
            road_ids=road_ids,
            distance_km=sum(r.distance_km for r in roads),
            travel_time_min=sum(self.graph.travel_time_min(r) for r in roads),
        )
        hospital = self.hospitals.get(route.get("hospital_id"))
        metrics = compute_route_metrics(self.graph, path)
        payload: Dict[str, Any] = {
            "route_id": route.get("route_id"),
            "nodes": nodes,
            "edges": road_ids,
            "feasible": True,
            "node_names": [self.graph.node_name(n) for n in nodes],
        }
        payload.update(metrics.to_dict())
        if hospital is not None:
            breakdown = score_candidate(hospital, metrics, emergency)
            payload["hospital_id"] = hospital.id
            payload["hospital_name"] = hospital.name
            payload["score"] = round(breakdown.total, config.ROUND_DIGITS)
            payload["score_breakdown"] = breakdown.to_dict()
        return payload

